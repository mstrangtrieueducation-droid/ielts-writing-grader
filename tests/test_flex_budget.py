from types import SimpleNamespace
import pytest
from src.cost_control import ClassBudget,cost_vnd
from src.state import StateStore
from src.schemas import ProEssayBundle
from src.graders.essay_bundle import restore_bundle
from conftest import FakeDrive
from test_cost_control import service
from test_hybrid_bundle import originals

def test_flex_cost_and_durable_actual_tier(binding):
    assert cost_vnd('gemini-3.1-pro-preview',7098,8192,service_tier='flex')==1462.5
    drive=FakeDrive();store=StateStore(drive,'state')
    budget=ClassBudget(store,binding,{'job_id':'flex','student':{'id':'S1'},'trial_cost_ceiling_vnd':1500},1500)
    key=budget.key('one bundle')
    budget.reserve(key,'gemini-3.1-pro-preview',5701,8192,'flex')
    budget.received(key,'{}',{'prompt_token_count':5000,'candidates_token_count':3500,'thoughts_token_count':500},'flex')
    assert budget.data['calls'][key]['accounted_vnd']==754
    with pytest.raises(ValueError,match='1,500'):
        ClassBudget(store,binding,{'job_id':'other','student':{'id':'S1'}},1500).reserve('new','gemini-3.1-pro-preview',5701,8192,'flex')

def test_unknown_flex_tier_keeps_reserve_and_freezes(binding):
    drive=FakeDrive();store=StateStore(drive,'state')
    budget=ClassBudget(store,binding,{'job_id':'flex'})
    budget.reserve('key','gemini-3.1-pro-preview',5701,8192,'flex')
    budget.received('key','raw',{ 'prompt_token_count':5000,'candidates_token_count':3500,'thoughts_token_count':500})
    assert budget.data['limit_vnd']==0 and 'accounted_vnd' not in budget.data['calls']['key']
    with pytest.raises(ValueError,match='unverified'):budget.existing('key')

def test_flex_request_uses_same_pro_no_retry_or_fallback(binding,monkeypatch):
    _,_,response=originals(binding)
    ai,calls,*_=service(binding,monkeypatch,response.model_dump_json())
    ai.essay_model='gemini-3.1-pro-preview';ai.essay_service_tier='flex'
    generate=ai.client.models.generate_content
    def confirmed(**kwargs):
        result=generate(**kwargs)
        result.sdk_http_response=SimpleNamespace(headers={'x-gemini-service-tier':'flex'})
        return result
    ai.client.models.generate_content=confirmed
    ai.structured(ai.essay_model,'prompt',ProEssayBundle)
    assert len(calls)==1 and calls[0]['model']=='gemini-3.1-pro-preview'
    assert calls[0]['config'].service_tier=='flex'
    assert calls[0]['config'].http_options.retry_options.attempts==1
    assert calls[0]['config'].max_output_tokens==8192

def test_static_chart_blocks_peak_in_pro_rewrite(binding):
    specs,texts,response=originals(binding)
    specs[0]=specs[0].model_copy(update={'task':1,'data_kind':'static'})
    response.essays[0].upgraded_paragraphs[0][0].text+=' Peaking at thirty.'
    with pytest.raises(ValueError,match='Static chart'):restore_bundle(response,specs,texts)
