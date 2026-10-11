import json
from types import SimpleNamespace
import pytest
from google.genai import types
from src.pro_batch import request,BatchPending,MODEL
from src.cost_control import ClassBudget,cost_vnd
from src.state import StateStore
from src.gemini_service import SYSTEM
from src.schemas import ProEssayBundle
from src.graders.essay_bundle import grade_bundle
from test_hybrid_bundle import originals
from conftest import FakeDrive

def setup(binding,monkeypatch):
    for key in ('GITHUB_ACTIONS','GEMINI_GENERATION_ENABLED','PILOT_BATCH_SUBMIT_AUTHORIZED'):
        monkeypatch.setenv(key,'true')
    drive=FakeDrive();store=StateStore(drive,'state')
    job={'job_id':'pilot','student':{'id':'S1'},'trial_cost_ceiling_vnd':1500}
    ai=SimpleNamespace(budget=ClassBudget(store,binding,job,1500),trusted_system=SYSTEM)
    calls={'create':0,'get':0,'list':0,'count':0}
    saved={}
    def create(**kwargs):
        calls['create']+=1
        # Intent and reservation must already be on Drive when the request is sent.
        ledger=drive.state[ai.budget.filename]
        assert next(iter(ledger['calls'].values()))['batch']['status']=='submission_intent'
        req=kwargs['src'][0]
        assert len(kwargs['src'])==1 and all(p.inline_data is None for c in req.contents for p in c.parts)
        assert req.config.max_output_tokens==8192 and req.config.service_tier is None
        assert kwargs['config'].http_options.retry_options.attempts==1
        saved.update(name='batches/job-1',display_name=kwargs['config'].display_name,
                     model='models/'+MODEL,state='JOB_STATE_PENDING',dest=None)
        if calls.get('timeout'):raise TimeoutError()
        return types.BatchJob(**saved)
    def get(**kwargs):
        calls['get']+=1
        assert kwargs['name']=='batches/job-1'
        return types.BatchJob(**saved)
    def list_jobs(**kwargs):
        calls['list']+=1
        if calls.get('invisible'):return []
        found=types.BatchJob(**saved)
        return [found,found] if calls.get('ambiguous') else [found]
    def count(**kwargs):
        calls['count']+=1;return SimpleNamespace(total_tokens=5794)
    ai.client=SimpleNamespace(models=SimpleNamespace(count_tokens=count),
        batches=SimpleNamespace(create=create,get=get,list=list_jobs))
    return ai,calls,saved,store,job

def reload(ai,store,binding,job):
    ai.budget=ClassBudget(store,binding,job,1500)

def success(ai,saved,response):
    key=next(iter(ai.budget.data['calls']))
    saved.update(state='JOB_STATE_SUCCEEDED',dest=types.BatchJobDestination(inlined_responses=[
        types.InlinedResponse(metadata={'key':key},response=types.GenerateContentResponse(
            candidates=[types.Candidate(finish_reason='STOP',content=types.Content(parts=[types.Part(text=response)]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=5794,
                candidates_token_count=3000,thoughts_token_count=500)))]))

@pytest.mark.parametrize('off',['GITHUB_ACTIONS','GEMINI_GENERATION_ENABLED','PILOT_BATCH_SUBMIT_AUTHORIZED'])
def test_new_batch_requires_each_explicit_gate(binding,monkeypatch,off):
    ai,calls,_,_,_=setup(binding,monkeypatch)
    monkeypatch.setenv(off,'false')
    with pytest.raises(ValueError,match='explicit serialized'):
        request(ai,'prompt',ProEssayBundle)
    assert calls['create']==calls['count']==0 and not ai.budget.data['calls']

def test_real_sdk_serializes_single_text_request_and_schema(binding,monkeypatch):
    import httpx
    from google import genai
    ai,calls,_,_,_=setup(binding,monkeypatch)
    captured=[]
    def transport(req):
        captured.append(req)
        body=json.loads(req.content)
        return httpx.Response(200,json={'name':'batches/sdk-test','model':'models/'+MODEL,
            'displayName':body['batch']['displayName'],'state':'JOB_STATE_PENDING'})
    client=genai.Client(api_key='synthetic-offline-key',http_options=types.HttpOptions(
        client_args={'transport':httpx.MockTransport(transport)},
        retry_options=types.HttpRetryOptions(attempts=1)))
    ai.client.batches=client.batches
    with pytest.raises(BatchPending):request(ai,'Synthetic two-essay prompt',ProEssayBundle)
    assert len(captured)==1 and captured[0].url.path.endswith(':batchGenerateContent')
    body=json.loads(captured[0].content)
    entries=body['batch']['inputConfig']['requests']['requests']
    assert len(entries)==1
    config=entries[0]['request']['generationConfig']
    assert config['responseJsonSchema']==ProEssayBundle.model_json_schema()
    assert config['maxOutputTokens']==8192 and 'serviceTier' not in config
    assert entries[0]['request']['systemInstruction']['parts'][0]['text']==SYSTEM
    client.close()

def test_submit_poll_and_raw_replay_never_regenerate(binding,monkeypatch):
    ai,calls,saved,store,job=setup(binding,monkeypatch)
    _,_,bundle=originals(binding)
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    reload(ai,store,binding,job)
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false')
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    success(ai,saved,bundle.model_dump_json())
    assert request(ai,'prompt',ProEssayBundle)==bundle
    reload(ai,store,binding,job)
    assert request(ai,'prompt',ProEssayBundle)==bundle
    assert calls=={'create':1,'get':2,'list':0,'count':1}
    call=next(iter(ai.budget.data['calls'].values()))
    assert call['actual_service_tier']=='batch' and call['batch']['provider_result']
    assert call['reserved_vnd']==pytest.approx(1465.386)
    assert call['accounted_vnd']==cost_vnd(MODEL,5794,3500,service_tier='batch')

def test_uncertain_create_reconciles_same_job_only(binding,monkeypatch):
    ai,calls,saved,store,job=setup(binding,monkeypatch);calls['timeout']=True
    with pytest.raises(BatchPending,match='uncertain'):request(ai,'prompt',ProEssayBundle)
    reload(ai,store,binding,job);calls['invisible']=True
    with pytest.raises(BatchPending,match='unresolved'):request(ai,'prompt',ProEssayBundle)
    calls['invisible']=False
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    assert calls['create']==calls['count']==1 and calls['list']==2
    assert next(iter(ai.budget.data['calls'].values()))['batch']['name']=='batches/job-1'

def test_ambiguous_recovery_cannot_create_again(binding,monkeypatch):
    ai,calls,_,_,_=setup(binding,monkeypatch);calls['timeout']=True
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    calls['ambiguous']=True
    with pytest.raises(ValueError,match='Ambiguous'):request(ai,'prompt',ProEssayBundle)
    assert calls['create']==1

@pytest.mark.parametrize('field,value',[('model','models/other'),('name','batches/other'),('display_name','other')])
def test_foreign_batch_response_held(binding,monkeypatch,field,value):
    ai,calls,saved,_,_=setup(binding,monkeypatch)
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    saved[field]=value
    with pytest.raises(ValueError,match='identity/model'):request(ai,'prompt',ProEssayBundle)
    assert calls['create']==1 and next(iter(ai.budget.data['calls'].values()))['status']=='reserved'

def test_failed_batch_preserves_reserve_without_retry(binding,monkeypatch):
    ai,calls,saved,_,_=setup(binding,monkeypatch)
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    saved['state']='JOB_STATE_FAILED'
    with pytest.raises(ValueError,match='terminal failure'):request(ai,'prompt',ProEssayBundle)
    with pytest.raises(ValueError,match='preserve reserve'):request(ai,'prompt',ProEssayBundle)
    assert calls['create']==calls['get']==1

def test_bad_json_is_saved_and_never_repaid(binding,monkeypatch):
    ai,calls,saved,store,job=setup(binding,monkeypatch)
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    success(ai,saved,'{truncated')
    with pytest.raises(ValueError):request(ai,'prompt',ProEssayBundle)
    reload(ai,store,binding,job)
    with pytest.raises(ValueError):request(ai,'prompt',ProEssayBundle)
    assert calls['create']==calls['get']==1
    assert next(iter(ai.budget.data['calls'].values()))['response_text']=='{truncated'

def test_truncated_response_with_parseable_json_is_still_held(binding,monkeypatch):
    ai,calls,saved,store,job=setup(binding,monkeypatch)
    _,_,bundle=originals(binding)
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    success(ai,saved,bundle.model_dump_json())
    saved['dest'].inlined_responses[0].response.candidates[0].finish_reason=types.FinishReason.MAX_TOKENS
    with pytest.raises(ValueError,match='incomplete'):request(ai,'prompt',ProEssayBundle)
    reload(ai,store,binding,job)
    with pytest.raises(ValueError,match='incomplete'):request(ai,'prompt',ProEssayBundle)
    assert calls['create']==calls['get']==1

def test_no_batch_identity_after_reservation_never_resubmits(binding,monkeypatch):
    ai,calls,_,store,job=setup(binding,monkeypatch)
    with pytest.raises(BatchPending):request(ai,'prompt',ProEssayBundle)
    next(iter(ai.budget.data['calls'].values())).pop('batch')
    ai.budget.save();reload(ai,store,binding,job)
    with pytest.raises(ValueError,match='preserved'):request(ai,'prompt',ProEssayBundle)
    assert calls['create']==1

def test_bundle_checkpoints_queue_and_resumes_existing_batch(binding,monkeypatch):
    ai,calls,saved,_,_=setup(binding,monkeypatch)
    specs,texts,bundle=originals(binding)
    ai.structured=lambda model,prompt,schema,files:request(ai,prompt,schema)
    settings=SimpleNamespace(essay_model=MODEL,essay_service_tier='batch')
    work=[]
    with pytest.raises(BatchPending):grade_bundle(ai,settings,specs,texts,work.append)
    assert work[-1]['status']=='queued' and work[-1]['transport']=='batch'
    with pytest.raises(BatchPending):grade_bundle(ai,settings,specs,texts,work.append,work[-1])
    success(ai,saved,bundle.model_dump_json())
    results=grade_bundle(ai,settings,specs,texts,work.append,work[-1])
    assert len(results)==2 and work[-1]['status']=='validated' and calls['create']==1

def test_collect_does_not_read_sources_or_publish(binding,settings,monkeypatch):
    from src.pilot import collect_batch_pilot
    from src.pipeline import Pipeline
    from conftest import notebook
    ai,calls,saved,store,_=setup(binding,monkeypatch)
    specs,texts,bundle=originals(binding)
    binding=binding.model_copy(update={'essays':specs})
    state=store.begin(binding,{'id':'S1','name':'Test'},
        {'received_at':'2026-10-09T23:00:00+07:00','notebook_ids':['book'],'essay_texts':texts})
    ai.budget=ClassBudget(store,binding,state,1500)
    state['notebook']=notebook().model_dump(mode='json')
    state['pilot_review']={'status':'awaiting_review','delivery_authorized':False}
    ai.structured=lambda model,prompt,schema,files:request(ai,prompt,schema)
    settings.essay_model=MODEL;settings.essay_service_tier='batch'
    def checkpoint(saved_work):state['bundle_work']=saved_work;store.save(state)
    with pytest.raises(BatchPending):grade_bundle(ai,settings,specs,texts,checkpoint)
    success(ai,saved,bundle.model_dump_json())
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false');monkeypatch.setenv('PILOT_BATCH_SUBMIT_AUTHORIZED','false')
    ai.bind_budget=lambda *_:None
    pipeline=Pipeline(settings,None,None,ai,store,None)
    report=collect_batch_pilot(pipeline,[binding],{'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['S1']})
    assert report['staged']==1 and report['generation_calls']==report['live_feedback_writes']==0
    assert len(state['payload']['essays'])==2 and not state['pilot_review']['delivery_authorized']
