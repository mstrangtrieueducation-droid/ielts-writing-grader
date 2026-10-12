import copy
import json
from types import SimpleNamespace as N

import pytest

from src.graders.essay_batch import (PROMPT_VERSION, grade_essay_batch,
                                     prepare_essay_requests)
from src.graders.essay_bundle import verify_saved_quality
from src.parsers import digest
from src.pro_batch import BatchPending
from src.schemas import LanguageCheck
from test_hybrid_bundle import originals, audited
from test_teacher_knowledge import corpus


def settings():
    return N(essay_model='gemini-3.1-pro-preview', essay_service_tier='batch')


def responses(binding):
    specs, texts, response = originals(binding)
    return specs, texts, {str(e.exercise): e for e in audited(response).essays}


def test_each_request_isolates_original_spec_and_matrix_but_keeps_entire_teacher_corpus(binding, monkeypatch):
    from src import lesson_packages
    from src.graders.essay_batch import QUALITY_CONTRACT, TEACHING_FAIRNESS
    specs, texts, _ = responses(binding)
    specs[0] = specs[0].model_copy(update={'task': 1, 'data_kind': 'static',
        'question': 'First separate chart question about course satisfaction.',
        'ground_truth': 'Columns Teaching/Tutor. Economics=95/90; Law=62/76.'})
    specs[1] = specs[1].model_copy(update={'task': 1, 'data_kind': 'static',
        'question': 'Second separate chart question about universities.',
        'ground_truth': 'Columns Biology/Medicine. USA=69/54; UK=30/24.'})
    c, reference = corpus()
    resolved = []
    def resolve(all_specs):
        resolved.append(all_specs)
        assert len(all_specs) == 2
        return {'id': 'TEST', 'version': 'v10', 'teaching_context': 'VERIFIED LESSON MAP',
                'full_teacher_sources': reference}
    monkeypatch.setattr(lesson_packages, 'resolve_package', resolve)
    requests = prepare_essay_requests(specs, texts, c)
    assert len(resolved) == 1 and len(requests) == 2
    for own, other in ((0, 1), (1, 0)):
        request = requests[own]
        prompt = request['prompt']
        assert 'CORRECTION LOCATIONS — ACTUAL STUDENT SOURCE' in prompt
        assert 'FINAL FEEDBACK AUDIT — COVERAGE, FAIRNESS, CONSISTENCY' in prompt
        assert 'An unannotated' in prompt and 'paragraph is not an absent paragraph' in prompt
        assert prompt.count(c['documents'][0]['text']) == 1
        assert 'VERIFIED LESSON MAP' in prompt and QUALITY_CONTRACT in prompt and TEACHING_FAIRNESS in prompt
        assert json.dumps(texts[str(specs[own].exercise)], ensure_ascii=False) in prompt
        assert json.dumps(texts[str(specs[other].exercise)], ensure_ascii=False) not in prompt
        assert specs[other].question not in prompt and specs[other].ground_truth not in prompt
        record = json.loads(prompt.split('\n')[-1])
        assert record['specification']['exercise'] == specs[own].exercise
        assert record['source_digest'] == request['source_digest'] == digest(record['original'])
        matrices = json.loads(prompt.split('TRUSTED CHART MATRICES:\n', 1)[1].split('\n', 1)[0])
        assert set(matrices) == {str(specs[own].exercise)}
        assert 'Grade exactly the ONE student essay' in prompt
        assert 'Grade BOTH essays' not in prompt
    with pytest.raises(ValueError, match='summary-only'):
        prepare_essay_requests(specs, texts)
    truncated = copy.deepcopy(c)
    truncated['documents'][0]['text'] = 'A summary.'
    with pytest.raises(ValueError, match='changed'):
        prepare_essay_requests(specs, texts, truncated)


def test_task2_does_not_use_chart_parser_and_count_is_not_hardcoded_to_two(binding, monkeypatch):
    from src.graders import essay_batch
    specs, texts, _ = responses(binding)
    def forbidden(_):
        raise AssertionError('Task2 must not be parsed as a chart')
    monkeypatch.setattr(essay_batch, 'chart_matrix', forbidden)
    assert len(prepare_essay_requests(specs[:1], texts)) == 1
    third = specs[0].model_copy(update={'exercise': 3})
    requests = prepare_essay_requests([*specs, third], {**texts, '3': 'Distinct third essay.'})
    assert len(requests) == 3
    assert all('"3"' not in r['prompt'].split('TRUSTED CHART MATRICES:\n')[1].split('\n')[0]
               for r in requests[:2])


def test_freeze_before_submit_poll_same_requests_then_replay_without_api_or_source_reload(binding, monkeypatch):
    from src import lesson_packages
    specs, texts, returned = responses(binding)
    calls, states = [], []
    def submit(requests):
        assert states[-1]['status'] in ('reserved', 'queued')
        assert states[-1]['mode'] == PROMPT_VERSION
        assert all(r['prompt_sha256'] == digest(r['prompt']) for r in states[-1]['requests'])
        calls.append(copy.deepcopy(requests))
        if len(calls) == 1:
            raise BatchPending('Saved job is queued')
        return returned
    ai = N(structured_essay_batch=submit)
    with pytest.raises(BatchPending):
        grade_essay_batch(ai, settings(), specs, texts, states.append)
    assert states[-1]['status'] == 'queued'
    frozen = copy.deepcopy(states[-1])
    def forbidden(_):
        raise AssertionError('Frozen requests must not reload live lesson criteria')
    monkeypatch.setattr(lesson_packages, 'resolve_package', forbidden)
    result = grade_essay_batch(ai, settings(), specs, texts, states.append, frozen)
    assert states[-1]['status'] == 'validated' and calls[0] == calls[1]
    replay = grade_essay_batch(None, settings(), specs, texts, states.append, states[-1])
    assert [e.model_dump() for e in result] == [e.model_dump() for e in replay]
    assert len(calls) == 2
    assert states[0]['status'] == 'reserved' and 'result' not in states[0]


@pytest.mark.parametrize('failure', ['source', 'exercise', 'missing', 'extra', 'invalid_schema'])
def test_bad_response_mapping_or_schema_is_preserved_without_paid_retry(binding, failure):
    specs, texts, returned = responses(binding)
    returned = {k: v.model_dump(mode='json') for k, v in returned.items()}
    if failure == 'source':
        returned['1']['source_digest'] = returned['2']['source_digest']
    elif failure == 'exercise':
        returned['1']['exercise'] = 2
    elif failure == 'missing':
        del returned['2']
    elif failure == 'extra':
        returned['3'] = returned['2']
    else:
        del returned['1']['summary_vi']
    states, calls = [], []
    def submit(requests):
        calls.append(requests)
        return returned
    with pytest.raises(ValueError):
        grade_essay_batch(N(structured_essay_batch=submit), settings(), specs, texts, states.append)
    assert states[-1]['status'] == 'held' and states[-1]['result'] == returned
    with pytest.raises(ValueError):
        grade_essay_batch(None, settings(), specs, texts, states.append, states[-1])
    assert len(calls) == 1


def test_quality_failure_keeps_raw_and_does_not_regenerate(binding):
    specs, texts, returned = responses(binding)
    # A missing paragraph-final full stop must be explained explicitly, not
    # silently repaired by the model. This tests an actual quality gate.
    texts['1'] = 'This introduction omits its final full stop'
    returned['1'].source_digest = digest(texts['1'])
    returned['1'].language_checks = [LanguageCheck(unit_id=1, verdict='clear', correction_indices=[])]
    states, calls = [], []
    def submit(requests):
        calls.append(requests)
        return returned
    with pytest.raises(ValueError, match='punctuation'):
        grade_essay_batch(N(structured_essay_batch=submit), settings(), specs, texts, states.append)
    assert states[-1]['status'] == 'held' and 'result' in states[-1]
    with pytest.raises(ValueError, match='punctuation'):
        grade_essay_batch(None, settings(), specs, texts, states.append, states[-1])
    assert len(calls) == 1


def test_unresolved_transport_error_never_retries_and_mutated_saved_identity_never_polls(binding):
    specs, texts, _ = responses(binding)
    states, calls = [], []
    def failed(requests):
        calls.append(requests)
        raise TimeoutError('Transport interrupted')
    with pytest.raises(TimeoutError):
        grade_essay_batch(N(structured_essay_batch=failed), settings(), specs, texts, states.append)
    assert states[-1]['status'] == 'held' and 'result' not in states[-1]
    with pytest.raises(ValueError, match='no automatic paid regeneration'):
        grade_essay_batch(None, settings(), specs, texts, states.append, states[-1])
    for mutation in ('prompt', 'source', 'specification', 'duplicate'):
        frozen = copy.deepcopy(states[0])
        frozen['status'] = 'queued'
        changed_specs, changed_texts = specs, texts
        if mutation == 'prompt':
            frozen['requests'][0]['prompt'] += 'new instructions'
        elif mutation == 'source':
            changed_texts = {**texts, '1': 'Different student essay.'}
        elif mutation == 'specification':
            changed_specs = [specs[0].model_copy(update={'assigned_outline': 'New assigned outline'}), specs[1]]
        else:
            frozen['requests'][1] = copy.deepcopy(frozen['requests'][0])
        with pytest.raises(ValueError):
            grade_essay_batch(None, settings(), changed_specs, changed_texts, states.append, frozen)
    assert len(calls) == 1


def test_delivery_dispatch_rechecks_exact_new_payload_and_preserves_legacy_path(binding):
    specs, texts, returned = responses(binding)
    states = []
    result = grade_essay_batch(N(structured_essay_batch=lambda _: returned), settings(), specs, texts, states.append)
    state = {'batch_essay_work': states[-1], 'source': {'essay_texts': texts},
             'payload': {'essays': [r.model_dump(mode='json') for r in result]}}
    current = binding.model_copy(update={'essays': specs})
    verify_saved_quality(state, current)
    altered = copy.deepcopy(state)
    altered['payload']['essays'][0]['summary_vi'] = 'Unchecked replacement feedback.'
    with pytest.raises(ValueError, match='Delivery differs'):
        verify_saved_quality(altered, current)
    altered = copy.deepcopy(state)
    altered['batch_essay_work']['status'] = 'held'
    with pytest.raises(ValueError, match='checkpoint'):
        verify_saved_quality(altered, current)
    altered = copy.deepcopy(state)
    altered['bundle_work'] = {'mode': 'hybrid-two-essays-v01'}
    with pytest.raises(ValueError, match='Conflicting'):
        verify_saved_quality(altered, current)
    # No Batch state means historical criteria stay on their existing path.
    verify_saved_quality({'bundle_work': {'mode': 'hybrid-two-essays-v01'}}, binding)


def test_frozen_full_source_bundle_delivery_never_resolves_current_manifest(binding, monkeypatch):
    from src import lesson_packages
    from src.graders.essay_bundle import grade_bundle
    from src.schemas import AuditedProEssayBundle
    specs, texts, returned = responses(binding)
    work = []
    result = grade_bundle(N(structured=lambda *_: AuditedProEssayBundle(essays=list(returned.values()))),
                          N(essay_model='gemini-3.1-pro-preview'), specs, texts, work.append)
    state = {'bundle_work': work[-1], 'source': {'essay_texts': texts},
             'payload': {'essays': [r.model_dump(mode='json') for r in result]}}
    def forbidden(_):
        raise AssertionError('A returned historical result must not require the current lesson package')
    monkeypatch.setattr(lesson_packages, 'resolve_package', forbidden)
    verify_saved_quality(state, binding.model_copy(update={'essays': specs}))


@pytest.mark.parametrize('model,tier', [('gemini-3.8-flash', 'batch'),
                                      ('gemini-3.1-pro-preview', 'flex'),
                                      ('gemini-3.1-pro-preview', 'standard')])
def test_cannot_route_new_contract_to_flash_or_direct(model, tier, binding):
    specs, texts, _ = responses(binding)
    with pytest.raises(ValueError, match='explicitly configured'):
        grade_essay_batch(None, N(essay_model=model, essay_service_tier=tier), specs, texts, lambda _: None)


def test_crash_after_prompt_freeze_waits_without_generation_then_submits_original_once(binding, monkeypatch, tmp_path):
    from src import lesson_packages
    from src.pro_batch_essays import request
    from test_pro_batch_essays import setup, succeed
    ai, transport_requests, output, calls, saved, _, _ = setup(binding, monkeypatch, tmp_path)
    specs, texts, _ = responses(binding)
    transport_requests[:] = prepare_essay_requests(specs, texts)
    ai.structured_essay_batch = lambda requests: request(ai, requests)
    states = []
    def crash_after_freeze(work):
        states.append(copy.deepcopy(work))
        raise SystemExit('Process stopped after durable prompt freeze')
    with pytest.raises(SystemExit):
        grade_essay_batch(ai, settings(), specs, texts, crash_after_freeze)
    assert states[-1]['status'] == 'reserved' and not ai.budget.data['calls']
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'false')
    def forbidden(_):
        raise AssertionError('Recovery must use the original frozen prompt, not current sources')
    monkeypatch.setattr(lesson_packages, 'resolve_package', forbidden)
    for _ in range(2):
        with pytest.raises(BatchPending, match='await enabled submission'):
            grade_essay_batch(ai, settings(), specs, texts, states.append, states[-1])
    assert states[-1]['status'] == 'reserved'
    assert all(calls[key] == 0 for key in ('count', 'upload', 'create', 'get', 'list'))
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'true')
    with pytest.raises(BatchPending, match='submitted'):
        grade_essay_batch(ai, settings(), specs, texts, states.append, states[-1])
    assert states[-1]['status'] == 'queued' and calls['create'] == calls['upload'] == 1
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'false')
    succeed(saved, output)
    result = grade_essay_batch(ai, settings(), specs, texts, states.append, states[-1])
    assert len(result) == 2 and states[-1]['status'] == 'validated'
    assert calls['create'] == calls['upload'] == 1 and calls['count'] == 2


@pytest.mark.parametrize('transport_status', ['submitted', 'received'])
def test_reserved_prompt_checkpoint_reconciles_transport_after_crash_without_duplicate_job(binding, monkeypatch, tmp_path, transport_status):
    from src.pro_batch_essays import request
    from test_pro_batch_essays import setup, succeed
    ai, transport_requests, output, calls, saved, _, _ = setup(binding, monkeypatch, tmp_path)
    specs, texts, _ = responses(binding)
    transport_requests[:] = prepare_essay_requests(specs, texts)
    ai.structured_essay_batch = lambda requests: request(ai, requests)
    states = []
    def crash_before_queued_checkpoint(work):
        if work['status'] == 'queued':
            raise SystemExit('Transport accepted job, process died before queued checkpoint')
        states.append(copy.deepcopy(work))
    with pytest.raises(SystemExit):
        grade_essay_batch(ai, settings(), specs, texts, crash_before_queued_checkpoint)
    assert states[-1]['status'] == 'reserved' and calls['create'] == 1
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'false')
    if transport_status == 'submitted':
        with pytest.raises(BatchPending, match='pending'):
            grade_essay_batch(ai, settings(), specs, texts, states.append, states[-1])
        assert states[-1]['status'] == 'queued'
        succeed(saved, output)
    else:
        # The transport can have persisted the result before the app's received
        # checkpoint. Recovery must restore it directly without another read.
        succeed(saved, output)
        request(ai, transport_requests)
    result = grade_essay_batch(ai, settings(), specs, texts, states.append, states[-1])
    assert len(result) == 2 and states[-1]['status'] == 'validated'
    assert calls['create'] == calls['upload'] == calls['download'] == 1
    assert calls['count'] == 2


def test_reserved_transport_budget_waits_for_enabled_upload_after_process_crash(binding, monkeypatch, tmp_path):
    from src.pro_batch_essays import request
    from test_pro_batch_essays import setup
    ai, transport_requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    specs, texts, _ = responses(binding)
    transport_requests[:] = prepare_essay_requests(specs, texts)
    ai.structured_essay_batch = lambda requests: request(ai, requests)
    states = []
    real_save = ai.budget.save
    def crash_after_budget_reservation():
        real_save()
        if any(b['status'] == 'reserved' for b in ai.budget.data.get('essay_batches', {}).values()):
            raise SystemExit('Process stopped before File API upload')
    ai.budget.save = crash_after_budget_reservation
    with pytest.raises(SystemExit):
        grade_essay_batch(ai, settings(), specs, texts, states.append)
    ai.budget.save = real_save
    assert states[-1]['status'] == 'reserved' and calls['count'] == 2
    assert calls['upload'] == calls['create'] == 0
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'false')
    with pytest.raises(BatchPending, match='await enabled submission'):
        grade_essay_batch(ai, settings(), specs, texts, states.append, states[-1])
    assert states[-1]['status'] == 'reserved' and calls['upload'] == calls['create'] == 0
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'true')
    with pytest.raises(BatchPending, match='submitted'):
        grade_essay_batch(ai, settings(), specs, texts, states.append, states[-1])
    assert states[-1]['status'] == 'queued'
    assert calls['upload'] == calls['create'] == 1 and calls['count'] == 2
