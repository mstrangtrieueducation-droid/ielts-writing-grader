from types import SimpleNamespace
import json
import pytest
from src.schemas import ProEssayBundle,FlashEssayBundle,AuditedProEssayBundle
from src.parsers import digest
from src.graders.essay_grader import language_units
from src.graders.essay_bundle import grade_bundle,prepare_bundle,restore_bundle
from src.cost_control import ClassBudget
from src.state import StateStore
from src.gemini_service import GeminiService
from src.pipeline import Pipeline
from conftest import FakeDrive,FakeSheets,FakeDashboard,essay
from test_cost_control import service

def originals(binding):
    first=binding.essays[0]
    second=first.model_copy(update={'exercise':2})
    specs=[first,second]
    texts={'1':'First source paragraph.\n\nSecond source paragraph.',
           '2':'Different essay source.\n\nAnother paragraph.'}
    items=[]
    for spec in specs:
        original=texts[str(spec.exercise)]
        data=essay(original,spec).model_dump(exclude={'original','word_count','paragraph_count','band_scores'})
        data.update(source_digest=digest(original),numeric_checks=[],language_checks=[
            {'unit_id':u['unit_id'],'verdict':'clear','correction_indices':[]} for u in language_units(original)])
        items.append(data)
    return specs,texts,ProEssayBundle(essays=items)

def audited(response):
    data=response.model_dump()
    for item in data['essays']:
        item.update(comparisons=[],numeric_evidence=[],generated_numbers=[])
        for correction in item['corrections']:correction['category']='grammar'
    return AuditedProEssayBundle.model_validate(data)

def test_scoped_teacher_knowledge_reaches_gemini_but_not_historical_replay(binding,monkeypatch):
    from src import lesson_packages
    specs,texts,response=originals(binding)
    context='Only this verified lesson teaches this comparison function.'
    monkeypatch.setattr(lesson_packages,'resolve_package',lambda _: {'id':'TEST','version':'v08','teaching_context':context})
    calls=[];states=[]
    ai=SimpleNamespace(structured=lambda model,prompt,schema,attachments: (calls.append(prompt) or audited(response)))
    settings=SimpleNamespace(essay_model='gemini-3.1-pro-preview')
    grade_bundle(ai,settings,specs,texts,states.append)
    assert context in calls[0]
    assert calls[0].count(context)==1
    frozen=states[-1].copy()
    frozen.update(mode='hybrid-two-essays-v07-teaching-reference-register',prompt='Frozen earlier teacher context',prompt_sha256=digest('Frozen earlier teacher context'))
    grade_bundle(ai,settings,specs,texts,states.append,frozen)
    assert len(calls)==1
    assert states[-1]['prompt']=='Frozen earlier teacher context'
    monkeypatch.setattr(lesson_packages,'resolve_package',lambda _: None)
    prompt,_=prepare_bundle(specs,texts)
    assert context not in prompt

def test_two_originals_one_request_durable_replay(binding):
    specs,texts,response=originals(binding)
    calls=[];work=[]
    def structured(model,prompt,schema,attachments):
        calls.append((model,prompt,schema,attachments))
        return audited(response)
    ai=SimpleNamespace(structured=structured)
    settings=SimpleNamespace(essay_model='gemini-3.1-pro-preview')
    first=grade_bundle(ai,settings,specs,texts,work.append)
    second=grade_bundle(ai,settings,specs,texts,work.append,work[-1])
    assert len(calls)==1 and calls[0][3]==()
    assert calls[0][2] is AuditedProEssayBundle
    sent=json.loads(calls[0][1].split('\n')[-1])
    assert [item['original'] for item in sent]==[texts['1'],texts['2']]
    assert [x.original for x in first]==[texts['1'],texts['2']]
    assert [x.model_dump() for x in first]==[x.model_dump() for x in second]
    assert work[0]['status']=='reserved' and work[-1]['status']=='validated'
    assert 'original' not in response.essays[0].model_dump()

def test_flash_two_essays_explicit_one_call_and_replay(binding,monkeypatch):
    specs,texts,response=originals(binding)
    ai,calls,*_=service(binding,monkeypatch,audited(response).model_dump_json())
    ai.essay_model='gemini-3.8-flash';ai.essay_bundle=True
    settings=SimpleNamespace(essay_model=ai.essay_model,essay_bundle=True)
    checkpoints=[]
    result=grade_bundle(ai,settings,specs,texts,checkpoints.append)
    repeated=grade_bundle(ai,settings,specs,texts,checkpoints.append,checkpoints[-1])
    assert len(calls)==1 and calls[0]['model']=='gemini-3.8-flash'
    assert len(result)==len(repeated)==2 and all(part.inline_data is None for part in calls[0]['contents'])
    assert calls[0]['config'].max_output_tokens==8192
    ai.essay_bundle=False
    with pytest.raises(ValueError,match='Flash-only'):
        ai.structured('gemini-3.8-flash','prompt',FlashEssayBundle)
    with pytest.raises(ValueError,match='model differs'):
        grade_bundle(ai,SimpleNamespace(essay_model='gemini-3.1-pro-preview'),specs,texts,checkpoints.append,checkpoints[-1])

def test_bundle_timeout_or_identity_error_never_repaid(binding):
    specs,texts,response=originals(binding)
    settings=SimpleNamespace(essay_model='gemini-3.1-pro-preview')
    calls=[];work=[]
    def failed(*args):
        calls.append(args)
        raise TimeoutError()
    ai=SimpleNamespace(structured=failed)
    with pytest.raises(TimeoutError):grade_bundle(ai,settings,specs,texts,work.append)
    with pytest.raises(ValueError,match='no automatic paid regeneration'):
        grade_bundle(ai,settings,specs,texts,work.append,work[-1])
    assert len(calls)==1
    response.essays[1].source_digest=response.essays[0].source_digest
    with pytest.raises(ValueError,match='source identity'):restore_bundle(response,specs,texts)
    response.essays[1].exercise=1
    with pytest.raises(ValueError,match='duplicates'):restore_bundle(response,specs,texts)
    with pytest.raises(ValueError,match='Both original'):prepare_bundle(specs,{'1':texts['1']})

def test_pro_bundle_routing_text_only_and_explicit(binding,monkeypatch):
    _,_,response=originals(binding)
    ai,calls,*_=service(binding,monkeypatch,response.model_dump_json())
    with pytest.raises(ValueError,match='Flash-only'):
        ai.structured('gemini-3.1-pro-preview','bundle',ProEssayBundle)
    ai.essay_model='gemini-3.1-pro-preview'
    with pytest.raises(ValueError,match='attachments prohibited'):
        ai.structured(ai.essay_model,'bundle',ProEssayBundle,[('notebook',b'pdf','application/pdf')])
    result=ai.structured(ai.essay_model,'bundle',ProEssayBundle)
    assert len(calls)==1 and len(result.essays)==2
    assert all(part.inline_data is None for part in calls[0]['contents'])

def test_student_cap_combines_models_and_survives_new_job(binding):
    drive=FakeDrive();store=StateStore(drive,'state')
    first={'job_id':'first','student':{'id':'S1'}}
    budget=ClassBudget(store,binding,first,1000)
    key=budget.key('notebook')
    budget.reserve(key,'gemini-3.8-flash',1000,1000)
    budget.received(key,'{}',{'prompt_token_count':1000,'candidates_token_count':500,'thoughts_token_count':500})
    new=ClassBudget(store,binding,{'job_id':'second','student':{'id':'S1'}},1000)
    with pytest.raises(ValueError,match='1,000'):
        new.reserve(new.key('essays'),'gemini-3.1-pro-preview',1000,3000)
    another=ClassBudget(store,binding,{'job_id':'third','student':{'id':'S2'}},1000)
    another.reserve(another.key('own essays'),'gemini-3.1-pro-preview',1000,2500)
    assert len(drive.state[budget.filename]['calls'])==2

def test_hybrid_unaffordable_plan_stops_before_notebook_read(binding,settings):
    specs,_,_=originals(binding)
    binding=binding.model_copy(update={'essays':specs})
    settings.essay_model='gemini-3.1-pro-preview'
    drive=FakeDrive();store=StateStore(drive,'state')
    ai=GeminiService.__new__(GeminiService)
    ai.essay_model=settings.essay_model;ai.student_limit=1000
    state=store.begin(binding,{'id':'S1','name':'Test','row':7},
        {'received_at':'2026-10-09T23:00:00+07:00','notebook_ids':['notebook_file_123'],
         'essay_texts':{'1':'First essay','2':'Second essay'}})
    pipeline=Pipeline(settings,FakeSheets([]),drive,ai,store,FakeDashboard())
    with pytest.raises(ValueError,match='1,000'):pipeline.grade(state,binding)
    assert not drive.downloaded and not state['payload'] and not state['essay_results']

def test_outline_ids_cannot_duplicate_notebook(binding):
    with pytest.raises(ValueError,match='Duplicate requirement'):
        type(binding).model_validate({**binding.model_dump(),
            'outline_requirements':[{'id':'notes','text':'Actual assigned outline'}]})
