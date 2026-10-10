from types import SimpleNamespace
import pytest
from google.genai import types
from src.cost_control import ClassBudget,cost_vnd,estimate_class
from src.gemini_service import GeminiService
from src.state import StateStore
from src.schemas import EssayResult,NotebookResult,QualityReview
from conftest import FakeDrive,essay

def test_price_estimates_include_output_and_do_not_claim_15k():
    assert cost_vnd('gemini-3.1-pro-preview',3000,2000)==780
    assert estimate_class(25,1,3000,2000,10000,1000)==26812.5
    assert estimate_class(25,2,5000,4000,20000,2000)==90025

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

def service(binding,monkeypatch,response=None,error=None):
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','true')
    drive=FakeDrive();store=StateStore(drive,'state')
    calls=[];configs=[]
    def generate(**kwargs):
        calls.append(kwargs);configs.append(kwargs['config'])
        if error:raise error
        return SimpleNamespace(text=response,usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=3000,candidates_token_count=1500,thoughts_token_count=500))
    ai=GeminiService.__new__(GeminiService)
    ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    ai.client=SimpleNamespace(models=SimpleNamespace(generate_content=generate,
        count_tokens=lambda **_:SimpleNamespace(total_tokens=3000)))
    ai.limiter=SimpleNamespace(wait=lambda:None);ai.audit=None;ai.job_id='test'
    return ai,calls,drive,store

def test_generation_saved_usage_replayed_without_second_call(binding,monkeypatch):
    result=essay(' '.join(['word']*260),binding.essays[0])
    ai,calls,drive,store=service(binding,monkeypatch,result.model_dump_json())
    records=[];ai.audit=records.append
    assert ai.structured('gemini-3.1-pro-preview','prompt',EssayResult).original==result.original
    ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    assert ai.structured('gemini-3.1-pro-preview','prompt',EssayResult).original==result.original
    assert len(calls)==1 and not calls[0]['contents'][0].inline_data
    assert calls[0]['config'].max_output_tokens==8192
    assert calls[0]['config'].thinking_config.thinking_level==types.ThinkingLevel.LOW
    assert records[0]['usage_metadata']['thoughts_token_count']==500

def test_timeout_reserved_without_repeat_payment(binding,monkeypatch):
    ai,calls,drive,store=service(binding,monkeypatch,error=TimeoutError())
    with pytest.raises(TimeoutError):ai.structured('gemini-3.1-pro-preview','prompt',EssayResult)
    ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    with pytest.raises(ValueError,match='no automatic retry'):
        ai.structured('gemini-3.1-pro-preview','prompt',EssayResult)
    assert len(calls)==1

def test_image_model_routing_blocked_before_network(binding,monkeypatch):
    ai,calls,*_=service(binding,monkeypatch)
    with pytest.raises(ValueError,match='never Pro'):
        ai.structured('gemini-3.1-pro-preview','prompt',NotebookResult)
    with pytest.raises(ValueError,match='attachments prohibited'):
        ai.structured('gemini-3.1-pro-preview','prompt',EssayResult,[('notes',b'pdf','application/pdf')])
    with pytest.raises(ValueError,match='quality review is disabled'):
        ai.structured('gemini-3.1-pro-preview','prompt',QualityReview)
    assert not calls

def test_invalid_json_cached_without_paid_repair(binding,monkeypatch):
    ai,calls,drive,store=service(binding,monkeypatch,response='invalid JSON')
    for _ in range(2):
        with pytest.raises(ValueError):ai.structured('gemini-3.1-pro-preview','prompt',EssayResult)
        ai.budget=ClassBudget(store,binding,{'job_id':'test'})
    assert len(calls)==1
