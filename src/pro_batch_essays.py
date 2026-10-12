"""Independent, text-only essay requests in a durable Gemini file Batch.

The provider job is a transport container, not a combined grading prompt. A lost
upload/create response is reconciled; it is never permission to submit again.
Legacy inline two-essay Batch jobs remain in pro_batch.py.
"""
import json
import math
import os
from pathlib import Path

from httpx import TransportError
from google.genai import types
from .cost_control import cost_vnd
from .parsers import digest
from .pro_batch import BatchPending, MODEL, TERMINAL, now, job_state, exact_model
from .schemas import AuditedBundledEssayFeedback

TRANSPORT = 'pro-per-essay-file-batch-v1'
MAX_OUTPUT = 16384
SCHEMA = AuditedBundledEssayFeedback


def generation_allowed():
    return all(os.getenv(key) == 'true' for key in
               ('GITHUB_ACTIONS', 'GRADING_ENABLED', 'GEMINI_GENERATION_ENABLED'))


def require_new_generation():
    if not generation_allowed():
        raise ValueError('New essay Batch requires enabled serialized Actions grading and generation')


def plan(ai, requests):
    if (getattr(ai, 'essay_model', None) != MODEL
            or getattr(ai, 'essay_service_tier', None) != 'batch'
            or getattr(ai, 'essay_request_mode', None) != 'per_essay_batch'
            or getattr(ai, 'pro_max_output_tokens', None) != MAX_OUTPUT):
        raise ValueError('Independent essay Batch requires its frozen Pro/Batch/output plan')
    if not ai.budget or not requests:
        raise ValueError('Private durable budget and essay requests are required')
    keys, entries = set(), []
    for item in requests:
        if (set(item) != {'exercise', 'prompt', 'source_digest'}
                or type(item['exercise']) is not int or item['exercise'] < 1
                or not isinstance(item['prompt'], str) or not item['prompt'].strip()
                or not isinstance(item['source_digest'], str) or len(item['source_digest']) != 64
                or any(c not in '0123456789abcdef' for c in item['source_digest'])):
            raise ValueError('Each essay requires only its exercise, text prompt and source digest')
        if item['exercise'] in keys:
            raise ValueError('Duplicate exercise in independent essay Batch')
        keys.add(item['exercise'])
        fingerprint = digest(json.dumps({
            'transport': TRANSPORT, 'job_id': ai.budget.job_id, 'exercise': item['exercise'],
            'source_digest': item['source_digest'], 'prompt': item['prompt'],
            'system': ai.trusted_system, 'schema': SCHEMA.model_json_schema(),
            'model': MODEL, 'output_limit': MAX_OUTPUT, 'thinking': 'medium'}, sort_keys=True))
        entries.append(dict(item, key=ai.budget.key(fingerprint)))
    entries.sort(key=lambda item: item['exercise'])
    batch_key = ai.budget.key(digest(TRANSPORT + '|' + '|'.join(item['key'] for item in entries)))
    prior = ai.budget.data.get('essay_batches', {})
    if any(batch.get('job_id') == ai.budget.job_id and key != batch_key for key, batch in prior.items()):
        raise ValueError('Frozen essay Batch changed; preserve the previous submission')
    return batch_key, entries


def count_plan(ai, entries):
    """Full teacher corpus is counted separately for every independent request."""
    counts, total = {}, 0
    for item in entries:
        counted = ai.client.models.count_tokens(model=MODEL, contents=[
            item['prompt'], ai.trusted_system,
            json.dumps(SCHEMA.model_json_schema(), ensure_ascii=False)])
        if counted.total_tokens is None:
            raise ValueError('Cannot count complete essay Batch input; submission held')
        counts[item['key']] = counted.total_tokens
        total += cost_vnd(MODEL, math.ceil(counted.total_tokens * 1.2) + 256,
                          MAX_OUTPUT, service_tier='batch')
    # Reserve the entire student plan before spending on either notebook or essays.
    ai.budget.ensure_capacity(total)
    limits = getattr(ai.budget, 'generation_limits', None)
    if limits is not None:
        used = sum(c.get('job_id') == ai.budget.job_id and c.get('model') == MODEL
                   for c in ai.budget.data['calls'].values())
        if used + len(entries) > limits.get(MODEL, 0):
            raise ValueError('Legacy one-call exception cannot authorize independent essay requests')
    return counts, total


def preflight(ai, requests):
    batch_key, entries = plan(ai, requests)
    if batch_key in ai.budget.data.get('essay_batches', {}):
        return 0  # Frozen requests are already reserved; collection makes no new plan.
    _, total = count_plan(ai, entries)
    return total


def jsonl(entries, system):
    config = {'temperature': 0.1, 'maxOutputTokens': MAX_OUTPUT,
              'responseMimeType': 'application/json',
              'responseJsonSchema': SCHEMA.model_json_schema(),
              'thinkingConfig': {'thinkingLevel': 'medium'}}
    return ''.join(json.dumps({'key': item['key'], 'request': {
        'contents': [{'role': 'user', 'parts': [{'text': item['prompt']}]}],
        'systemInstruction': {'parts': [{'text': system}]},
        'generationConfig': config}}, ensure_ascii=False) + '\n' for item in entries)


def failure(exc):
    data = {'type': type(exc).__name__, 'at': now()}
    if isinstance(getattr(exc, 'code', None), int):
        data['http_code'] = exc.code
    return data


def provider_read(ai, batch, operation, read):
    """Defer a transient read to the next collector run, never retry generation.

    A provider read can fail after a paid Batch was accepted. Keeping this as
    BatchPending preserves the queued grading checkpoint instead of freezing it
    as a semantic failure. Auth/input/identity errors are still held for review.
    """
    try:
        result = read()
    except Exception as exc:
        status = getattr(exc, 'code', None)
        if not isinstance(status, int):
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
        transient = (isinstance(exc, (TimeoutError, ConnectionError, OSError, TransportError))
                     or isinstance(status, int) and (status == 429 or 500 <= status <= 599))
        if not transient:
            raise
        diagnostic = failure(exc)
        diagnostic['operation'] = operation
        if isinstance(status, int):
            diagnostic['http_code'] = status
        batch['last_read_failure'] = diagnostic
        ai.budget.save()
        raise BatchPending('Essay Batch read temporarily unavailable; resume the same saved job') from exc
    if batch.pop('last_read_failure', None) is not None:
        ai.budget.save()
    return result


def local_export(ai, batch_key, content):
    directory = Path(getattr(ai, 'batch_export_dir', Path(__file__).resolve().parents[1] / 'local_evidence' / 'pro-batch'))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (batch_key + '.jsonl')
    path.write_text(content, encoding='utf-8', newline='\n')
    return path


def save_input(ai, batch_key, entries):
    content = jsonl(entries, ai.trusted_system)
    # The existing Drive client supports verified JSON state, so preserve the exact
    # JSONL string in that private document and export the same bytes for File API.
    source = {'transport': TRANSPORT, 'sha256': digest(content), 'jsonl': content}
    file_id = ai.budget.drive.write_json(ai.budget.folder, 'essay-batch-input-' + batch_key + '.json', source)
    return content, file_id


def progress_submission(ai, batch_key, batch, entries):
    budget = ai.budget
    if batch['status'] == 'reserved':
        require_new_generation()
        content, file_id = save_input(ai, batch_key, entries)
        batch.update(input_private_file=file_id, input_sha256=digest(content),
                     upload_display_name='ielts-essay-input-' + batch_key, status='upload_intent')
        budget.save()  # Durable intent precedes the sole File API upload attempt.
        path = local_export(ai, batch_key, content)
        try:
            uploaded = ai.client.files.upload(file=str(path), config=types.UploadFileConfig(
                display_name=batch['upload_display_name'], mime_type='jsonl',
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))))
        except Exception as exc:
            batch.update(status='upload_unknown', failure=failure(exc)); budget.save()
            raise BatchPending('Essay input upload uncertain; reconcile only') from exc
        if not uploaded.name:
            batch['status'] = 'upload_unknown'; budget.save()
            raise BatchPending('Essay upload returned no identity; do not upload again')
        batch.update(input_file_name=uploaded.name, status='uploaded'); budget.save()
    if batch['status'] in ('upload_intent', 'upload_unknown'):
        matches = provider_read(ai, batch, 'files.list', lambda: [item
            for item in ai.client.files.list(config=types.ListFilesConfig(page_size=100))
            if item.display_name == batch['upload_display_name']])
        if len(matches) > 1:
            raise ValueError('Ambiguous essay input upload; no automatic repeat')
        if not matches:
            raise BatchPending('Essay input upload unresolved; no new upload or generation')
        batch.update(input_file_name=matches[0].name, status='uploaded'); budget.save()
    if batch['status'] == 'uploaded':
        if not generation_allowed():
            raise BatchPending('Essay input saved; generation is disabled so no Batch is created')
        batch.update(status='submission_intent', create_started_at=now()); budget.save()
        try:
            job = ai.client.batches.create(model=MODEL, src=batch['input_file_name'],
                config=types.CreateBatchJobConfig(display_name=batch['display_name'],
                    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))))
        except Exception as exc:
            batch.update(status='submission_unknown', failure=failure(exc)); budget.save()
            raise BatchPending('Essay Batch create uncertain; reconcile saved intent only') from exc
        if not job.name:
            batch['status'] = 'submission_unknown'; budget.save()
            raise BatchPending('Essay Batch returned no identity; do not create again')
        batch.update(name=job.name, status='submitted'); budget.save()
        raise BatchPending('Independent essay Batch submitted; collect saved job separately')


def saved_results(ai, batch, entries):
    if batch.get('errors'):
        raise ValueError('Saved essay Batch has incomplete/invalid items; successful results preserved, no retry')
    output = {}
    for item in entries:
        call = ai.budget.data['calls'][item['key']]
        if call.get('status') != 'received' or call.get('tier_unverified') or call.get('validation_hold'):
            raise ValueError('Saved essay Batch item is held; no automatic paid retry')
        parsed = SCHEMA.model_validate_json(call['response_text'] or '')
        if parsed.exercise != item['exercise'] or parsed.source_digest != item['source_digest']:
            raise ValueError('Saved essay Batch source identity differs')
        output[str(item['exercise'])] = parsed
    return output


def parse_batch_response(raw):
    # File API JSON can gain metadata before the SDK's strict response model.
    # Preserve the exact provider row in the ledger; adapt this known metadata
    # field only. Batch billing is bound to the accepted Batch job, not its
    # internal execution tier (which Google can report as STANDARD).
    import copy
    adapted = copy.deepcopy(raw)
    metadata = adapted.get('usageMetadata', adapted.get('usage_metadata', {}))
    reported_tier = metadata.pop('serviceTier', metadata.pop('service_tier', None))
    if reported_tier is not None and reported_tier not in (
            'SERVICE_TIER_STANDARD', 'SERVICE_TIER_PRIORITY', 'SERVICE_TIER_FLEX',
            'SERVICE_TIER_UNSPECIFIED'):
        raise ValueError('Unknown provider usage service tier')
    response = types.GenerateContentResponse.model_validate(adapted)
    usage = response.usage_metadata.model_dump(mode='json') if response.usage_metadata else {}
    if reported_tier is not None:
        usage['provider_service_tier'] = reported_tier
    return response, usage


def reconcile_saved_metadata(ai, requests):
    """Reparse exact saved bytes after SDK metadata compatibility repair; no API call."""
    batch_key, entries = plan(ai, requests)
    batch = ai.budget.data.get('essay_batches', {}).get(batch_key)
    if not batch or batch['status'] != 'received_hold' or batch.get('provider_state') != 'JOB_STATE_SUCCEEDED':
        raise ValueError('No completed saved Batch eligible for metadata reconciliation')
    for item in entries:
        call = ai.budget.data['calls'][item['key']]
        rows = call.get('batch_output_items', [])
        if call.get('validation_hold') != 'ValidationError' or len(rows) != 1:
            raise ValueError('Saved failure is not the known metadata compatibility failure')
        response = rows[0].get('response', {})
        if 'serviceTier' not in response.get('usageMetadata', {}):
            raise ValueError('Known extra provider metadata absent')
        parse_batch_response(response)  # All strict response fields still checked.
    data, _ = ai.budget.drive.download(batch['output_private_file'])
    saved = json.loads(data)
    if digest(saved['jsonl']) != saved['sha256'] or saved['sha256'] != batch['output_sha256']:
        raise ValueError('Saved Batch output checksum differs')
    batch['metadata_reconciliation'] = {'at': now(), 'original_errors': batch['errors'],
        'output_sha256': saved['sha256'], 'generation_calls': 0}
    return collect_output(ai, batch, entries, saved['jsonl'])


def collect_output(ai, batch, entries, raw, terminal_error=None):
    budget = ai.budget
    # Preserve all bytes privately before parsing, including malformed/unknown keys.
    batch['output_private_file'] = budget.drive.write_json(budget.folder,
        'essay-batch-output-' + batch['batch_key'] + '.json', {'jsonl': raw, 'sha256': digest(raw)})
    batch['output_sha256'] = digest(raw)
    batch['errors'] = ([{'reason': 'provider_job_terminal_failure', 'state': terminal_error}]
                       if terminal_error else [])
    budget.save()
    expected = {item['key']: item for item in entries}
    grouped = {}
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            batch['errors'].append({'line': number, 'reason': 'invalid_json_line'}); continue
        if not isinstance(row, dict) or row.get('key') not in expected:
            batch['errors'].append({'line': number, 'reason': 'unknown_or_missing_key'}); continue
        grouped.setdefault(row['key'], []).append(row)
    for key, item in expected.items():
        rows = grouped.get(key, [])
        call = budget.data['calls'][key]
        call['batch_output_items'] = rows
        reason = None
        if len(rows) != 1:
            reason = 'missing_key' if not rows else 'duplicate_key'
        elif rows[0].get('error') or rows[0].get('status') and not rows[0].get('response'):
            reason = 'provider_item_error'
        elif not rows[0].get('response'):
            reason = 'missing_response'
        if reason:
            call['validation_hold'] = reason
            batch['errors'].append({'exercise': item['exercise'], 'reason': reason})
            budget.save(); continue
        try:
            response, usage = parse_batch_response(rows[0]['response'])
            text = response.text or ''
            budget.received(key, text, usage, 'batch')
            if (len(response.candidates or []) != 1
                    or getattr(response.candidates[0].finish_reason, 'name', None) != 'STOP'):
                raise ValueError('incomplete_provider_response')
            parsed = SCHEMA.model_validate_json(text)
            if parsed.exercise != item['exercise'] or parsed.source_digest != item['source_digest']:
                raise ValueError('source_identity_mismatch')
            call['validated_schema'] = SCHEMA.__name__
            call.pop('validation_hold', None)
        except Exception as exc:
            # Raw provider error/result is already private. Public logs get no essay text.
            call['validation_hold'] = type(exc).__name__
            batch['errors'].append({'exercise': item['exercise'], 'reason': 'invalid_response_or_identity'})
        budget.save()
    batch['status'] = 'received_hold' if batch['errors'] else 'received'
    batch['received_at'] = now(); budget.save()
    return saved_results(ai, batch, entries)


def request(ai, requests):
    batch_key, entries = plan(ai, requests)
    budget = ai.budget
    batches = budget.data.setdefault('essay_batches', {})
    batch = batches.get(batch_key)
    if batch is None:
        require_new_generation()
        if any(item['key'] in budget.data['calls'] for item in entries):
            raise ValueError('Prior essay reservation has no matching Batch intent; preserve it')
        counts, total = count_plan(ai, entries)
        batch = {'transport': TRANSPORT, 'batch_key': batch_key, 'job_id': budget.job_id,
                 'display_name': 'ielts-essays-' + batch_key, 'status': 'reserving',
                 'created_at': now(), 'reserved_plan_vnd': total,
                 'items': [{k: item[k] for k in ('exercise', 'key', 'source_digest')} for item in entries]}
        batches[batch_key] = batch; budget.save()
        for item in entries:
            budget.reserve(item['key'], MODEL, counts[item['key']], MAX_OUTPUT, 'batch')
            budget.data['calls'][item['key']].update(transport=TRANSPORT, exercise=item['exercise'],
                source_digest=item['source_digest'], prompt_sha256=digest(item['prompt']), batch_key=batch_key)
            budget.save()
        batch['status'] = 'reserved'; budget.save()
    if batch['status'] == 'reserving':
        raise ValueError('Interrupted essay budget reservation; no upload or generation sent')
    if batch['status'] in ('received', 'received_hold'):
        return saved_results(ai, batch, entries)
    if batch['status'] == 'terminal_failure':
        raise ValueError('Essay Batch failed; preserve reserve and do not resubmit')
    if batch['status'] in ('reserved', 'upload_intent', 'upload_unknown', 'uploaded'):
        progress_submission(ai, batch_key, batch, entries)
    if not batch.get('name'):
        matches = provider_read(ai, batch, 'batches.list', lambda: [job
            for job in ai.client.batches.list(config=types.ListBatchJobsConfig(page_size=100))
            if job.display_name == batch['display_name'] and exact_model(job.model)])
        if len(matches) > 1:
            raise ValueError('Ambiguous essay Batch identity; no automatic resubmission')
        if not matches:
            raise BatchPending('Essay Batch create unresolved; no new paid request')
        batch.update(name=matches[0].name, status='reconciled'); budget.save()
    job = provider_read(ai, batch, 'batches.get', lambda: ai.client.batches.get(name=batch['name']))
    if job.name != batch['name'] or not exact_model(job.model) or job.display_name != batch['display_name']:
        raise ValueError('Essay Batch identity/model differs from the saved intent')
    state = job_state(job)
    batch.update(provider_state=state, checked_at=now()); budget.save()
    if state not in TERMINAL:
        raise BatchPending('Essay Batch pending; collection made no generation request')
    batch['provider_result'] = job.model_dump(mode='json'); budget.save()
    output_file = job.dest.file_name if job.dest else None
    if not output_file:
        if state != 'JOB_STATE_SUCCEEDED':
            batch['status'] = 'terminal_failure'; budget.save()
            raise ValueError('Essay Batch terminal failure; no paid retry')
        batch.update(status='terminal_failure', failure={'type': 'MissingOutputFile'}); budget.save()
        raise ValueError('Essay Batch has no JSONL output file; preserve reserve')
    raw = provider_read(ai, batch, 'files.download', lambda: ai.client.files.download(file=output_file))
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    if not isinstance(raw, str):
        raise ValueError('Essay Batch output is not a text JSONL file')
    batch['output_file_name'] = output_file
    # A failed job can still carry partial output. Preserve successes and their
    # usage before holding the whole job; never pay to regenerate failed items.
    return collect_output(ai, batch, entries, raw,
                          terminal_error=state if state!='JOB_STATE_SUCCEEDED' else None)
