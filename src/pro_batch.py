"""One durable Pro Batch request. Polling never creates or retries a paid job.

Create has no provider idempotency key: persist intent before sending, then reconcile
an uncertain create by exact display name AND model. Absence is not permission to
submit again. All private request/result state lives in the existing cost ledger.
"""
import json
import os
from datetime import datetime, timezone
from google.genai import types
from .parsers import digest
from .schemas import ProEssayBundle

MODEL='gemini-3.1-pro-preview'
TERMINAL={'JOB_STATE_SUCCEEDED','JOB_STATE_FAILED','JOB_STATE_CANCELLED','JOB_STATE_EXPIRED'}

class BatchPending(Exception):
    """Saved job is pending; resume by polling, not by generating again."""

def now():
    return datetime.now(timezone.utc).isoformat()

def job_state(job):
    return getattr(job.state,'name',str(job.state))

def exact_model(model):
    return (model or '').removeprefix('models/')==MODEL

def request(ai, prompt, schema):
    if schema is not ProEssayBundle:
        raise ValueError('Pro Batch only accepts the approved two-essay schema')
    config=types.GenerateContentConfig(system_instruction=ai.trusted_system,
        temperature=0.1,max_output_tokens=8192,response_mime_type='application/json',
        response_json_schema=schema.model_json_schema(),
        thinking_config=types.ThinkingConfig(thinking_level='medium'))
    fingerprint=digest(json.dumps({'model':MODEL,'prompt':prompt,'system':ai.trusted_system,
        'schema':schema.model_json_schema(),'output_limit':8192,'thinking':'medium',
        'transport':'batch-v1'},sort_keys=True))
    budget=ai.budget
    if not budget:
        raise ValueError('Durable budget required for Pro Batch')
    key=budget.key(fingerprint)
    call=budget.data['calls'].get(key)
    if call and call.get('status')=='received':
        if call.get('batch',{}).get('validation_hold'):
            raise ValueError('Saved Batch response is incomplete; no paid retry')
        if call.get('tier_unverified'):
            raise ValueError('Batch price provenance unresolved')
        return schema.model_validate_json(call['response_text'] or '')
    if not call:
        if not all(os.getenv(k)=='true' for k in
                   ('GITHUB_ACTIONS','GEMINI_GENERATION_ENABLED','PILOT_BATCH_SUBMIT_AUTHORIZED')):
            raise ValueError('New Pro Batch requires explicit serialized pilot authorization')
        counted=ai.client.models.count_tokens(model=MODEL,contents=[prompt,ai.trusted_system,
            json.dumps(schema.model_json_schema(),ensure_ascii=False)])
        if counted.total_tokens is None:
            raise ValueError('Cannot count Batch input; submission held')
        budget.reserve(key,MODEL,counted.total_tokens,8192,'batch')
        call=budget.data['calls'][key]
        call['batch']={'status':'submission_intent','display_name':'ielts-'+key,
                       'request_key':key,'prompt_sha256':digest(prompt),'created_at':now()}
        budget.save()  # Must be durable before the ONLY create request.
        try:
            job=ai.client.batches.create(model=MODEL,src=[types.InlinedRequest(
                contents=[types.Content(role='user',parts=[types.Part.from_text(text=prompt)])],
                config=config,metadata={'key':key})],
                config=types.CreateBatchJobConfig(display_name=call['batch']['display_name'],
                    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))))
        except Exception as exc:
            call['batch']['status']='submission_unknown'
            failure={'type':type(exc).__name__,'at':now()}
            if isinstance(getattr(exc,'code',None),int):failure['http_code']=exc.code
            call['batch']['failure']=failure
            budget.save()
            raise BatchPending('Batch submission uncertain; reconcile saved intent only') from exc
        if not job.name:
            call['batch']['status']='submission_unknown';budget.save()
            raise BatchPending('Batch create returned no job identity; do not resubmit')
        call['batch'].update(name=job.name,status='submitted')
        budget.save()
        # Collection is always a separate read operation, even for an instant response.
        raise BatchPending('Pro Batch submitted; collect this saved job')
    batch=call.get('batch')
    if not batch or call.get('service_tier')!='batch':
        raise ValueError('Unresolved non-Batch paid attempt is preserved')
    if batch['status']=='terminal_failure':
        raise ValueError('Batch failed; preserve reserve and do not create another job')
    if not batch.get('name'):
        matches=[j for j in ai.client.batches.list(config=types.ListBatchJobsConfig(page_size=100))
            if j.display_name==batch['display_name'] and exact_model(j.model)]
        if len(matches)>1:
            raise ValueError('Ambiguous Batch identity; no automatic resubmission')
        if not matches:
            raise BatchPending('Submission intent unresolved; no new paid request')
        batch.update(name=matches[0].name,status='reconciled');budget.save()
    job=ai.client.batches.get(name=batch['name'])
    if job.name!=batch['name'] or not exact_model(job.model) or job.display_name!=batch['display_name']:
        raise ValueError('Batch response identity/model differs from saved intent')
    state=job_state(job)
    batch.update(provider_state=state,checked_at=now())
    if state not in TERMINAL:
        budget.save()
        raise BatchPending('Pro Batch pending; collection sent no generation request')
    # Persist raw provider evidence privately before parsing/quality checks.
    batch['provider_result']=job.model_dump(mode='json')
    if state!='JOB_STATE_SUCCEEDED':
        batch['status']='terminal_failure';budget.save()
        raise ValueError('Pro Batch terminal failure; no paid retry')
    responses=job.dest.inlined_responses if job.dest else None
    if not responses or len(responses)!=1 or responses[0].metadata!={'key':key}:
        batch['status']='terminal_failure';budget.save()
        raise ValueError('Batch must return exactly the saved single request identity')
    item=responses[0]
    if item.error or item.response is None:
        batch['status']='terminal_failure';budget.save()
        raise ValueError('Batch request has no usable response; no paid retry')
    batch['status']='received'
    usage=item.response.usage_metadata.model_dump(mode='json') if item.response.usage_metadata else {}
    budget.received(key,item.response.text,usage,'batch')
    candidates=item.response.candidates or []
    if len(candidates)!=1 or getattr(candidates[0].finish_reason,'name',None)!='STOP':
        batch['validation_hold']='Response did not finish normally'
        budget.save()
        raise ValueError('Batch response incomplete; preserve raw result, no paid retry')
    # Even invalid/truncated JSON is now durable and replays without spending again.
    return schema.model_validate_json(item.response.text or '')
