import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import types

from src.cost_control import ClassBudget, cost_vnd
from src.gemini_service import GeminiService, SYSTEM
from src.pro_batch import BatchPending, MODEL
from src.pro_batch_essays import request, preflight, MAX_OUTPUT, SCHEMA
from src.state import StateStore
from conftest import FakeDrive
from test_hybrid_bundle import originals, audited


def setup(binding, monkeypatch, tmp_path):
    for flag in ('GITHUB_ACTIONS', 'GRADING_ENABLED', 'GEMINI_GENERATION_ENABLED'):
        monkeypatch.setenv(flag, 'true')
    drive = FakeDrive()
    store = StateStore(drive, 'state')
    state = {'job_id': 'per-essay-job', 'student': {'id': 'S1'}, 'trial_cost_ceiling_vnd': 14000}
    ai = SimpleNamespace(budget=ClassBudget(store, binding, state, 14000), trusted_system=SYSTEM,
                         essay_model=MODEL, essay_service_tier='batch', essay_request_mode='per_essay_batch',
                         pro_max_output_tokens=MAX_OUTPUT, batch_export_dir=tmp_path)
    _, texts, output = originals(binding)
    output = audited(output)
    requests = [{'exercise': i.exercise, 'prompt': f'Complete teacher corpus and ONLY essay {i.exercise}: {texts[str(i.exercise)]}',
                 'source_digest': i.source_digest} for i in output.essays]
    calls = {'count': 0, 'upload': 0, 'create': 0, 'get': 0, 'list': 0, 'download': 0, 'files_list': 0}
    saved = {'jsonl': None, 'job': {}, 'files': []}

    def count(**kwargs):
        calls['count'] += 1
        assert len(kwargs['contents']) == 3
        return SimpleNamespace(total_tokens=6000)

    def upload(**kwargs):
        calls['upload'] += 1
        ledger = drive.state[ai.budget.filename]
        assert len(ledger['calls']) == 2
        assert all(item['status'] == 'reserved' for item in ledger['calls'].values())
        batch = next(iter(ledger['essay_batches'].values()))
        assert batch['status'] == 'upload_intent' and batch['input_private_file'] in drive.state
        assert kwargs['config'].http_options.retry_options.attempts == 1
        content = Path(kwargs['file']).read_text(encoding='utf-8')
        saved['input'] = [json.loads(line) for line in content.splitlines()]
        assert len(saved['input']) == 2
        for line, expected in zip(saved['input'], requests):
            req = line['request']
            assert req['contents'] == [{'role': 'user', 'parts': [{'text': expected['prompt']}]}]
            assert req['systemInstruction']['parts'] == [{'text': SYSTEM}]
            assert req['generationConfig']['maxOutputTokens'] == MAX_OUTPUT
            assert req['generationConfig']['responseJsonSchema'] == SCHEMA.model_json_schema()
            assert 'serviceTier' not in req['generationConfig']
        item = types.File(name='files/input1', display_name=kwargs['config'].display_name)
        saved['files'] = [item]
        if calls.get('upload_timeout'):
            raise TimeoutError()
        return item

    def create(**kwargs):
        calls['create'] += 1
        assert kwargs['model'] == MODEL and kwargs['src'] == 'files/input1'
        assert kwargs['config'].http_options.retry_options.attempts == 1
        ledger = drive.state[ai.budget.filename]
        assert next(iter(ledger['essay_batches'].values()))['status'] == 'submission_intent'
        saved['job'] = {'name': 'batches/file1', 'display_name': kwargs['config'].display_name,
                        'model': 'models/' + MODEL, 'state': 'JOB_STATE_PENDING'}
        if calls.get('create_timeout'):
            raise TimeoutError()
        return types.BatchJob(**saved['job'])

    def get(**kwargs):
        calls['get'] += 1
        error = calls.pop('get_error', None)
        if error: raise error
        return types.BatchJob(**saved['job'])

    def list_jobs(**kwargs):
        calls['list'] += 1
        error = calls.pop('list_error', None)
        if error: raise error
        if calls.get('invisible'):
            return []
        result = types.BatchJob(**saved['job'])
        return [result, result] if calls.get('ambiguous') else [result]

    def download(**kwargs):
        calls['download'] += 1
        error = calls.pop('download_error', None)
        if error: raise error
        assert kwargs['file'] == 'files/output1'
        return saved['jsonl'].encode('utf-8')

    def list_files(**kwargs):
        calls['files_list'] += 1
        return saved['files']

    ai.client = SimpleNamespace(models=SimpleNamespace(count_tokens=count),
        files=SimpleNamespace(upload=upload, download=download, list=list_files),
        batches=SimpleNamespace(create=create, get=get, list=list_jobs))
    return ai, requests, output, calls, saved, store, state


def succeed(saved, output, rows=None):
    saved['job'].update(state='JOB_STATE_SUCCEEDED', dest={'file_name': 'files/output1'})
    if rows is None:
        rows = []
        for line, essay in zip(saved['input'], output.essays):
            rows.append({'key': line['key'], 'response': {
                'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': essay.model_dump_json()}]}}],
                'usageMetadata': {'promptTokenCount': 6000, 'candidatesTokenCount': 3000, 'thoughtsTokenCount': 500}}})
    saved['jsonl'] = '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows)
    return rows


@pytest.mark.parametrize('flag', ['GITHUB_ACTIONS', 'GRADING_ENABLED', 'GEMINI_GENERATION_ENABLED'])
def test_each_gate_prevents_new_requests(binding, monkeypatch, tmp_path, flag):
    ai, requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    monkeypatch.setenv(flag, 'false')
    with pytest.raises(ValueError, match='enabled serialized'):
        request(ai, requests)
    assert calls['upload'] == calls['create'] == calls['count'] == 0
    assert not ai.budget.data['calls']


def test_full_plan_budget_held_before_any_upload(binding, monkeypatch, tmp_path):
    ai, requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    ai.budget.student_limit = 4000  # One request fits, both together do not.
    with pytest.raises(ValueError, match='ceiling'):
        request(ai, requests)
    assert calls['count'] == 2 and calls['create'] == calls['upload'] == 0
    assert not ai.budget.data['calls']


def test_preflight_counts_every_full_source_without_spending(binding, monkeypatch, tmp_path):
    ai, requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    amount = preflight(ai, requests)
    assert amount == pytest.approx(2 * cost_vnd(MODEL, 7456, MAX_OUTPUT, service_tier='batch'))
    assert calls['count'] == 2 and calls['upload'] == calls['create'] == 0
    assert not ai.budget.data['calls']


def test_independent_file_requests_reordered_results_and_durable_replay(binding, monkeypatch, tmp_path):
    ai, requests, output, calls, saved, store, state = setup(binding, monkeypatch, tmp_path)
    with pytest.raises(BatchPending, match='submitted'):
        request(ai, requests)
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'false')
    monkeypatch.setenv('GRADING_ENABLED', 'false')
    ai.budget = ClassBudget(store, binding, state, 14000)
    with pytest.raises(BatchPending, match='pending'):
        request(ai, requests)
    rows = succeed(saved, output)
    succeed(saved, output, list(reversed(rows)))
    result = request(ai, requests)
    assert result == {str(e.exercise): e for e in output.essays}
    ai.budget = ClassBudget(store, binding, state, 14000)
    assert request(ai, list(reversed(requests))) == result
    assert calls['upload'] == calls['create'] == calls['download'] == 1
    assert calls['get'] == 2 and calls['count'] == 2
    assert all(c['accounted_vnd'] == cost_vnd(MODEL, 6000, 3500, service_tier='batch') for c in ai.budget.data['calls'].values())


def test_unknown_create_reconciles_no_repeat(binding, monkeypatch, tmp_path):
    ai, requests, _, calls, saved, store, state = setup(binding, monkeypatch, tmp_path)
    calls['create_timeout'] = True
    with pytest.raises(BatchPending, match='uncertain'):
        request(ai, requests)
    ai.budget = ClassBudget(store, binding, state, 14000)
    calls['invisible'] = True
    with pytest.raises(BatchPending, match='unresolved'):
        request(ai, requests)
    calls['invisible'] = False
    with pytest.raises(BatchPending, match='pending'):
        request(ai, requests)
    assert calls['create'] == calls['upload'] == 1 and calls['list'] == 2


def test_unknown_upload_reconciles_and_collector_cannot_create(binding, monkeypatch, tmp_path):
    ai, requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    calls['upload_timeout'] = True
    with pytest.raises(BatchPending, match='upload uncertain'):
        request(ai, requests)
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'false')
    with pytest.raises(BatchPending, match='generation is disabled'):
        request(ai, requests)
    assert calls['upload'] == 1 and calls['create'] == 0
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED', 'true')
    with pytest.raises(BatchPending, match='submitted'):
        request(ai, requests)
    assert calls['upload'] == calls['create'] == 1


@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'provider_error', 'bad_json', 'truncated', 'wrong_source', 'unknown'])
def test_partial_invalid_output_preserves_success_without_retry(binding, monkeypatch, tmp_path, mode):
    ai, requests, output, calls, saved, store, state = setup(binding, monkeypatch, tmp_path)
    with pytest.raises(BatchPending):
        request(ai, requests)
    rows = succeed(saved, output)
    if mode == 'missing': rows.pop()
    elif mode == 'duplicate': rows.append(rows[-1])
    elif mode == 'provider_error': rows[-1] = {'key': rows[-1]['key'], 'error': {'code': 13, 'message': 'test error'}}
    elif mode == 'bad_json': rows[-1]['response']['candidates'][0]['content']['parts'][0]['text'] = '{'
    elif mode == 'truncated': rows[-1]['response']['candidates'][0]['finishReason'] = 'MAX_TOKENS'
    elif mode == 'wrong_source':
        wrong = output.essays[-1].model_copy(update={'source_digest': 'b'*64})
        rows[-1]['response']['candidates'][0]['content']['parts'][0]['text'] = wrong.model_dump_json()
    elif mode == 'unknown': rows.append({'key': 'not-requested', 'response': {}})
    succeed(saved, output, rows)
    with pytest.raises(ValueError, match='successful results preserved'):
        request(ai, requests)
    first = ai.budget.data['calls'][saved['input'][0]['key']]
    assert first['validated_schema'] == SCHEMA.__name__ and first['accounted_vnd'] > 0
    batch = next(iter(ai.budget.data['essay_batches'].values()))
    assert batch['output_private_file'] in store.drive.state and batch['errors']
    ai.budget = ClassBudget(store, binding, state, 14000)
    with pytest.raises(ValueError):
        request(ai, requests)
    assert calls['create'] == calls['upload'] == calls['get'] == calls['download'] == 1


def test_changed_source_is_not_another_paid_attempt(binding, monkeypatch, tmp_path):
    ai, requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    with pytest.raises(BatchPending): request(ai, requests)
    changed = [dict(item) for item in requests]
    changed[0]['source_digest'] = 'a'*64
    with pytest.raises(ValueError, match='Frozen essay Batch changed'):
        request(ai, changed)
    assert calls['count'] == 2 and calls['create'] == 1


def test_failed_job_partial_file_is_saved_and_successful_items_accounted(binding, monkeypatch, tmp_path):
    ai, requests, output, calls, saved, _, _ = setup(binding, monkeypatch, tmp_path)
    with pytest.raises(BatchPending): request(ai, requests)
    rows = succeed(saved, output)
    succeed(saved, output, rows[:1])
    saved['job']['state'] = 'JOB_STATE_FAILED'
    with pytest.raises(ValueError, match='successful results preserved'):
        request(ai, requests)
    first = ai.budget.data['calls'][saved['input'][0]['key']]
    assert first['validated_schema'] == SCHEMA.__name__ and first['accounted_vnd'] > 0
    assert next(iter(ai.budget.data['essay_batches'].values()))['errors'][0]['state'] == 'JOB_STATE_FAILED'
    with pytest.raises(ValueError): request(ai, requests)
    assert calls['create'] == calls['download'] == 1


def test_ambiguous_unknown_create_never_pays_again(binding, monkeypatch, tmp_path):
    ai, requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    calls['create_timeout'] = True
    with pytest.raises(BatchPending): request(ai, requests)
    calls['ambiguous'] = True
    with pytest.raises(ValueError, match='Ambiguous essay Batch identity'):
        request(ai, requests)
    assert calls['create'] == 1


@pytest.mark.parametrize('operation,error_type,status',[
    ('get','timeout',None), ('get','server',503), ('download','server',502),
    ('download','httpx_timeout',None), ('list','client',429)])
def test_transient_collection_read_resumes_same_paid_job(binding,monkeypatch,tmp_path,operation,error_type,status):
    from google.genai.errors import ServerError,ClientError
    from httpx import ReadTimeout
    ai,requests,output,calls,saved,store,state=setup(binding,monkeypatch,tmp_path)
    if operation=='list':calls['create_timeout']=True
    with pytest.raises(BatchPending):request(ai,requests)
    succeed(saved,output)
    original_batch=next(iter(ai.budget.data['essay_batches'].values()))
    identity={k:original_batch.get(k) for k in ('batch_key','display_name','name','items')}
    if error_type=='timeout':error=TimeoutError()
    elif error_type=='httpx_timeout':error=ReadTimeout('Private connection detail')
    elif error_type=='server':error=ServerError(status,{'error':{'message':'Private provider detail'}})
    else:error=ClientError(status,{'error':{'message':'Private quota detail'}})
    calls[operation+'_error']=error
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false')
    monkeypatch.setenv('GRADING_ENABLED','false')
    with pytest.raises(BatchPending,match='temporarily unavailable'):
        request(ai,requests)
    failed=next(iter(ai.budget.data['essay_batches'].values()))
    expected_operation='files.download' if operation=='download' else 'batches.'+operation
    assert failed['last_read_failure']['operation']==expected_operation
    assert 'Private' not in json.dumps(failed['last_read_failure'])
    assert {k:failed.get(k) for k in identity}==identity
    ai.budget=ClassBudget(store,binding,state,14000)
    result=request(ai,requests)
    assert result=={str(item.exercise):item for item in output.essays}
    assert calls['upload']==calls['create']==1 and calls['count']==2
    assert 'last_read_failure' not in next(iter(ai.budget.data['essay_batches'].values()))


@pytest.mark.parametrize('kind',['client_error','foreign_identity'])
def test_nontransient_or_semantic_collection_failure_still_held(binding,monkeypatch,tmp_path,kind):
    from google.genai.errors import ClientError
    ai,requests,_,calls,saved,_,_=setup(binding,monkeypatch,tmp_path)
    with pytest.raises(BatchPending):request(ai,requests)
    if kind=='client_error':
        calls['get_error']=ClientError(400,{'error':{'message':'Bad input'}})
        expected=ClientError
    else:
        saved['job']['model']='models/wrong-model'
        expected=ValueError
    with pytest.raises(expected):request(ai,requests)
    batch=next(iter(ai.budget.data['essay_batches'].values()))
    assert 'last_read_failure' not in batch
    assert calls['create']==calls['upload']==1


def test_service_binding_freezes_new_plan_and_rejects_legacy_override(binding, monkeypatch, tmp_path):
    ai, _, _, _, _, store, state = setup(binding, monkeypatch, tmp_path)
    service = GeminiService.__new__(GeminiService)
    for key in ('essay_model', 'essay_service_tier', 'essay_request_mode', 'pro_max_output_tokens'):
        setattr(service, key, getattr(ai, key))
    service.student_limit = 14000
    with pytest.raises(ValueError, match='frozen generation plan'):
        service.bind_budget(store, binding, state)
    state['generation_plan'] = {'model': MODEL, 'service_tier': 'batch', 'request_mode': 'per_essay_batch',
                                'max_output_tokens': MAX_OUTPUT, 'thinking_level': 'medium'}
    service.bind_budget(store, binding, state)
    assert service.budget.student_limit == 14000


def test_real_sdk_file_source_serialization(binding, monkeypatch, tmp_path):
    import httpx
    from google import genai
    ai, requests, _, calls, _, _, _ = setup(binding, monkeypatch, tmp_path)
    seen = []
    def transport(req):
        seen.append(req)
        body = json.loads(req.content)
        assert body['batch']['inputConfig']['fileName'] == 'files/input1'
        return httpx.Response(200, json={'name': 'batches/sdk-file', 'model': 'models/'+MODEL,
                              'displayName': body['batch']['displayName'], 'state': 'JOB_STATE_PENDING'})
    client = genai.Client(api_key='offline-synthetic-key', http_options=types.HttpOptions(
        client_args={'transport': httpx.MockTransport(transport)},
        retry_options=types.HttpRetryOptions(attempts=1)))
    ai.client.batches = client.batches
    with pytest.raises(BatchPending, match='submitted'):
        request(ai, requests)
    assert len(seen) == 1
    client.close()


@pytest.mark.parametrize('schema_name', ['EssayResult', 'ThoroughFlashResult', 'ThoroughFlashTask1Result',
    'ProEssayBundle', 'AuditedProEssayBundle', 'FlashEssayBundle', 'AuditedFlashEssayBundle',
    'AuditedBundledEssayFeedback', 'QualityReview'])
@pytest.mark.parametrize('model', [MODEL, 'gemini-3.8-flash'])
def test_new_mode_has_no_synchronous_or_legacy_essay_fallback(binding,monkeypatch,schema_name,model):
    import src.schemas as schemas
    from test_cost_control import service
    ai,calls,*_=service(binding,monkeypatch)
    ai.essay_request_mode='per_essay_batch'
    ai.essay_model=MODEL
    ai.essay_service_tier='batch'
    ai.pro_max_output_tokens=MAX_OUTPUT
    with pytest.raises(ValueError,match='requires structured_essay_batch'):
        ai.structured(model,'synthetic essay',getattr(schemas,schema_name))
    assert not calls and not ai.budget.data['calls']


@pytest.mark.parametrize('kind',['notebook','transcription'])
def test_new_mode_keeps_flash_input_work_at_8192_tokens(binding,monkeypatch,kind):
    from conftest import notebook
    from src.schemas import NotebookResult,Transcription
    from test_cost_control import service
    result=notebook() if kind=='notebook' else Transcription(essays=[],page_audit=[])
    schema=NotebookResult if kind=='notebook' else Transcription
    ai,calls,*_=service(binding,monkeypatch,result.model_dump_json())
    ai.essay_request_mode='per_essay_batch'
    ai.essay_model=MODEL
    ai.essay_service_tier='batch'
    ai.pro_max_output_tokens=MAX_OUTPUT
    ai.client.models.count_tokens=lambda **kwargs:SimpleNamespace(total_tokens=3000)
    ai.structured('gemini-3.8-flash','input evidence',schema,[('synthetic-pdf',b'pdf','application/pdf')])
    assert len(calls)==1 and calls[0]['model']=='gemini-3.8-flash'
    assert calls[0]['config'].max_output_tokens==8192
    assert calls[0]['config'].thinking_config.thinking_level==types.ThinkingLevel.LOW
    assert any(part.inline_data is not None for part in calls[0]['contents'])
