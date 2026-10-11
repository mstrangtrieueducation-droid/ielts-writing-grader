from types import SimpleNamespace
import pytest
from src.schemas import ProEssayBundle
from src.gemini_service import GeminiService
from src.state import StateStore
from conftest import FakeDrive
from test_cost_control import service
from test_hybrid_bundle import originals

def test_truncated_even_parseable_response_is_saved_and_never_repaid(binding,monkeypatch):
    _,_,response=originals(binding)
    ai,calls,drive,store=service(binding,monkeypatch,response.model_dump_json())
    ai.essay_model='gemini-3.1-pro-preview'
    generate=ai.client.models.generate_content
    def truncated(**kwargs):
        result=generate(**kwargs)
        result.candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name='MAX_TOKENS'))]
        return result
    ai.client.models.generate_content=truncated
    with pytest.raises(ValueError,match='did not finish normally'):
        ai.structured(ai.essay_model,'prompt',ProEssayBundle)
    with pytest.raises(ValueError,match='truncated'):
        ai.structured(ai.essay_model,'prompt',ProEssayBundle)
    assert len(calls)==1
    call=next(iter(ai.budget.data['calls'].values()))
    assert call['status']=='received' and call['response_text']==response.model_dump_json()
    assert call['response_incomplete'] and call['accounted_vnd']

def test_larger_plan_requires_frozen_authorization_before_notebook_budget(binding):
    ai=GeminiService.__new__(GeminiService)
    ai.essay_model='gemini-3.1-pro-preview';ai.essay_service_tier='standard'
    ai.pro_max_output_tokens=16384;ai.student_limit=6000
    store=StateStore(FakeDrive(),'state')
    state={'job_id':'new','student':{'id':'S1'}}
    with pytest.raises(ValueError,match='explicitly frozen'):
        ai.bind_budget(store,binding,state)
    state['generation_plan']={'model':ai.essay_model,'service_tier':'standard',
        'max_output_tokens':16384,'thinking_level':'medium'}
    ai.bind_budget(store,binding,state)
    ai.essay_service_tier='flex'
    with pytest.raises(ValueError,match='explicitly frozen'):
        ai.bind_budget(store,binding,state)

def test_larger_standard_response_keeps_medium_and_one_request(binding,monkeypatch):
    _,_,response=originals(binding)
    ai,calls,*_=service(binding,monkeypatch,response.model_dump_json())
    ai.essay_model='gemini-3.1-pro-preview';ai.essay_service_tier='standard'
    ai.pro_max_output_tokens=16384
    ai.structured(ai.essay_model,'prompt',ProEssayBundle)
    assert len(calls)==1
    config=calls[0]['config']
    assert config.max_output_tokens==16384
    assert config.thinking_config.thinking_level.name=='MEDIUM'
    assert config.http_options.retry_options.attempts==1 and config.http_options.timeout==900000
    ai.essay_service_tier='flex'
    with pytest.raises(ValueError,match='restricted'):
        ai.structured(ai.essay_model,'prompt',ProEssayBundle)
