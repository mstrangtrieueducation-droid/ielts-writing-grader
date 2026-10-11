from types import SimpleNamespace
import pytest
from google.genai import types
from src.cost_control import ClassBudget,cost_vnd,estimate_class
from src.gemini_service import GeminiService
from src.state import StateStore
from src.schemas import EssayResult,ThoroughFlashResult,NotebookResult,QualityReview
from conftest import FakeDrive,essay

def test_price_estimates_include_output_and_do_not_claim_15k():
    assert cost_vnd('gemini-3.1-pro-preview',3000,2000)==780
    assert estimate_class(25,1,3000,2000,10000,1000)==13650
    assert estimate_class(25,2,5000,4000,20000,2000)==39000

def test_durable_class_budget_across_jobs_and_restarts(binding):
    drive=FakeDrive();store=StateStore(drive,'state')
    budget=ClassBudget(store,binding,{'job_id':'first'})
    key=budget.key('same request')
    budget.reserve(key,'gemini-3.1-pro-preview',3000,8192)
    reloaded=ClassBudget(store,binding,{'job_id':'first'})
    with pytest.raises(ValueError,match='no automatic retry'):reloaded.existing(key)
    other=ClassBudget(store,binding,{'job_id':'second'})
    with pytest.raises(ValueError,match='14,900'):
        other.reserve(other.key('oversized'),'gemini-3.1-pro-preview',10000,50000)
    budget.received(key,'{}',{'prompt_token_count':3000,'candidates_token_count':1000,'thoughts_token_count':1000})
    assert ClassBudget(store,binding,{'job_id':'first'}).existing(key)['accounted_vnd']==780

def test_explicit_trial_ceiling_is_durable_and_job_scoped(binding):
    drive=FakeDrive();store=StateStore(drive,'state')
    job={'job_id':'bounded','trial_cost_ceiling_vnd':2000}
    first=ClassBudget(store,binding,job)
    key=first.key('first')
    first.reserve(key,'gemini-3.8-flash',3000,8192)
    first.received(key,'{}',{'prompt_token_count':3000,'candidates_token_count':3000,'thoughts_token_count':4000})
    second=ClassBudget(store,binding,job)
    second.reserve(second.key('second'),'gemini-3.8-flash',3000,8192)
    third=ClassBudget(store,binding,job)
    with pytest.raises(ValueError,match='trial cost ceiling'):
        third.reserve(third.key('third'),'gemini-3.8-flash',3000,8192)
    other=ClassBudget(store,binding,{'job_id':'other','trial_cost_ceiling_vnd':900})
    other.reserve(other.key('different'),'gemini-3.8-flash',3000,8192)

def service(binding,monkeypatch,response=None,error=None):
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','true')
    drive=FakeDrive();store=StateStore(drive,'state')
    calls=[];configs=[]
    def generate(**kwargs):
        calls.append(kwargs);configs.append(kwargs['config'])
        if error:raise error
        return SimpleNamespace(text=response,usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=3000,candidates_token_count=1500,thoughts_token_count=500))
    def count(**kwargs):
        # Actual Developer API rejects the system/generation fields in CountTokensConfig.
        assert 'config' not in kwargs
        assert len(kwargs['contents'])==3
        assert 'untrusted evidence' in kwargs['contents'][1].text
        assert 'properties' in kwargs['contents'][2].text
        return SimpleNamespace(total_tokens=3000)
    ai=GeminiService.__new__(GeminiService)
    ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    ai.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate,
        count_tokens=count))
    ai.limiter=SimpleNamespace(wait=lambda:None);ai.audit=None;ai.job_id='test'
    return ai,calls,drive,store

def test_generation_saved_usage_replayed_without_second_call(binding,monkeypatch):
    result=essay(' '.join(['word']*260),binding.essays[0])
    ai,calls,drive,store=service(binding,monkeypatch,result.model_dump_json())
    records=[];ai.audit=records.append
    assert ai.structured('gemini-3.8-flash','prompt',EssayResult).original==result.original
    ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    assert ai.structured('gemini-3.8-flash','prompt',EssayResult).original==result.original
    assert len(calls)==1 and not calls[0]['contents'][0].inline_data
    assert calls[0]['config'].max_output_tokens==8192
    assert calls[0]['config'].thinking_config.thinking_level==types.ThinkingLevel.MEDIUM
    assert records[0]['usage_metadata']['thoughts_token_count']==500

def test_thorough_schema_keeps_essay_budget_and_blocks_attachments(binding,monkeypatch):
    base=essay('An essay.',binding.essays[0]).model_dump()
    result=ThoroughFlashResult(**base,language_checks=[{'unit_id':1,'verdict':'clear','correction_indices':[]}])
    ai,calls,*_=service(binding,monkeypatch,result.model_dump_json())
    with pytest.raises(ValueError,match='attachments prohibited'):
        ai.structured('gemini-3.8-flash','prompt',ThoroughFlashResult,[('scan',b'pdf','application/pdf')])
    ai.structured('gemini-3.8-flash','prompt',ThoroughFlashResult)
    assert len(calls)==1 and calls[0]['config'].max_output_tokens==8192
    assert calls[0]['config'].thinking_config.thinking_level==types.ThinkingLevel.MEDIUM

def test_timeout_reserved_without_repeat_payment(binding,monkeypatch):
    ai,calls,drive,store=service(binding,monkeypatch,error=TimeoutError())
    with pytest.raises(TimeoutError):ai.structured('gemini-3.8-flash','prompt',EssayResult)
    ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    with pytest.raises(ValueError,match='no automatic retry'):
        ai.structured('gemini-3.8-flash','prompt',EssayResult)
    assert len(calls)==1

def test_provider_error_is_audited_without_releasing_reserve(binding,monkeypatch):
    from google.genai.errors import ServerError
    error=ServerError(503,{'error':{'status':'UNAVAILABLE','message':'private request details'}})
    ai,calls,drive,store=service(binding,monkeypatch,error=error)
    records=[];ai.audit=records.append
    with pytest.raises(ServerError):ai.structured('gemini-3.8-flash','prompt',EssayResult)
    saved=next(iter(ai.budget.data['calls'].values()))
    assert saved['status']=='reserved' and 'accounted_vnd' not in saved
    assert saved['failure']['http_code']==503 and saved['failure']['provider_status']=='UNAVAILABLE'
    assert records[0]['charge_confirmed'] is False and 'private request details' not in str(records)
    ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    with pytest.raises(ValueError,match='no automatic retry'):
        ai.structured('gemini-3.8-flash','prompt',EssayResult)
    assert len(calls)==1

def test_image_model_routing_blocked_before_network(binding,monkeypatch):
    ai,calls,*_=service(binding,monkeypatch)
    with pytest.raises(ValueError,match='Flash-only'):
        ai.structured('gemini-3.1-pro-preview','prompt',NotebookResult)
    with pytest.raises(ValueError,match='Flash-only'):
        ai.structured('gemini-3.1-pro-preview','prompt',EssayResult)
    with pytest.raises(ValueError,match='attachments prohibited'):
        ai.structured('gemini-3.8-flash','prompt',EssayResult,[('notes',b'pdf','application/pdf')])
    with pytest.raises(ValueError,match='quality review is disabled'):
        ai.structured('gemini-3.8-flash','prompt',QualityReview)
    assert not calls

def test_invalid_json_cached_without_paid_repair(binding,monkeypatch):
    ai,calls,drive,store=service(binding,monkeypatch,response='invalid JSON')
    for _ in range(2):
        with pytest.raises(ValueError):ai.structured('gemini-3.8-flash','prompt',EssayResult)
        ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    assert len(calls)==1

def test_teacher_cost_exception_is_one_call_and_never_raises_shared_limit(binding):
    drive=FakeDrive();store=StateStore(drive,'state')
    original=ClassBudget(store,binding,{'job_id':'history'})
    original.data['calls']['old']={'job_id':'history','reserved_vnd':14500,'status':'reserved'}
    original.save()
    binding=binding.model_copy(update={'regrade_authorizations':{'S1':'Explicit one-call teacher approval'}})
    job={'job_id':'approved','student':{'id':'S1'},'trial_cost_ceiling_vnd':5700}
    job['cost_exception']={'scope':{'class_name':binding.class_name,'task_code':binding.task_code},
        'job_id':'approved','student_id':'S1','authority':binding.regrade_authorizations['S1'],
        'approved_at':'2026-10-12T00:00:00+07:00','maximum_generation_calls':1,
        'new_trial_ceiling_vnd':5700,'class_ceiling_vnd':16100}
    approved=ClassBudget(store,binding,job)
    approved.reserve('new','gemini-3.1-pro-preview',1000,2000)
    assert approved.data['limit_vnd']==14900
    with pytest.raises(ValueError,match='only one generation'):
        ClassBudget(store,binding,job).reserve('another','gemini-3.1-pro-preview',1000,2000)
    with pytest.raises(ValueError,match='14,900'):
        ClassBudget(store,binding,{'job_id':'other'}).ensure_capacity(1)
    mismatched={**job,'job_id':'different'}
    with pytest.raises(ValueError,match='exact teacher-authorized'):
        ClassBudget(store,binding,mismatched)

def test_notebook_and_bundle_exception_cannot_authorize_second_pro_call(binding):
    drive=FakeDrive();store=StateStore(drive,'state')
    binding=binding.model_copy(update={'regrade_authorizations':{'S2':'Explicit notebook and two-essay pilot'}})
    job={'job_id':'new-student','student':{'id':'S2'},'trial_cost_ceiling_vnd':7800}
    job['cost_exception']={'scope':{'class_name':binding.class_name,'task_code':binding.task_code},
        'job_id':'new-student','student_id':'S2','authority':binding.regrade_authorizations['S2'],
        'approved_at':'2026-10-12T00:00:00+07:00','maximum_generation_calls':3,
        'generation_limits':{'gemini-3.8-flash':2,'gemini-3.1-pro-preview':1},
        'new_trial_ceiling_vnd':7800,'class_ceiling_vnd':27600}
    for key,model in [('book','gemini-3.8-flash'),('independent-book','gemini-3.8-flash'),('bundle','gemini-3.1-pro-preview')]:
        ClassBudget(store,binding,job).reserve(key,model,1000,2000)
    for model in ('gemini-3.1-pro-preview','gemini-3.8-flash'):
        with pytest.raises(ValueError,match='model call limit'):
            ClassBudget(store,binding,job).reserve('extra-'+model,model,1000,2000)
    assert ClassBudget(store,binding,job).data['limit_vnd']==14900
