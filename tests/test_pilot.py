import pytest
from src.pilot import selected_binding
from src.schemas import Binding

def test_selection_rejects_unbounded_pilot():
    with pytest.raises(ValueError,match='exact class'):
        selected_binding([],{'class_name':'IELTS 48','task_code':'W14'})

def test_selection_rejects_duplicate_students():
    with pytest.raises(ValueError,match='unique'):
        selected_binding([],{'class_name':'IELTS 48','task_code':'W14','student_ids':['1','1']})

def test_selection_requires_verified_binding():
    with pytest.raises(ValueError,match='not verified'):
        selected_binding([],{'class_name':'IELTS 48','task_code':'W14','student_ids':['1']})

def test_selection_paid_trial_rejects_multiple_students(binding):
    with pytest.raises(ValueError,match='exactly one'):
        selected_binding([binding],{'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['1','2']})

def test_deliver_saved_pilot_requires_exact_quality_approval_without_model(binding,settings):
    from test_pipeline import components
    from src.pilot import deliver_pilot,payload_digest
    from conftest import essay
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    student,source=pipeline.sources(binding,pipeline.sheets.roster(None,None))[0]
    state=store.begin(binding,student,source)
    state['payload']=pipeline.payload(binding,student,source,'graded','Vở đạt yêu cầu.',[essay('Essay',binding.essays[0]).model_dump(mode='json')])
    selection={'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['S1']}
    with pytest.raises(ValueError,match='quality verification'):
        deliver_pilot(pipeline,[binding],selection)
    state['pilot_review']={'status':'approved','delivery_authorized':True,'quality_evidence':'Independent comparison with original/chart',
        'approved_payload_sha256':payload_digest(state['payload'])}
    pipeline.grade=lambda *_:(_ for _ in ()).throw(AssertionError('No generation on delivery'))
    state['payload']['warning']='Changed after approval'
    with pytest.raises(ValueError,match='payload changed'):
        deliver_pilot(pipeline,[binding],selection)
    state['pilot_review']['approved_payload_sha256']=payload_digest(state['payload'])
    report=deliver_pilot(pipeline,[binding],selection)
    assert report['delivered']==1 and report['model_generation_calls']==0 and state['phase']=='complete'

def test_pilot_stages_actual_result_without_delivery(binding,settings,monkeypatch):
    from test_pipeline import components
    from conftest import notebook,essay
    import src.pipeline as module
    from src.pilot import run_pilot
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    monkeypatch.setattr(module,'grade_notebook',lambda *_:notebook())
    monkeypatch.setattr(module,'grade_essay',lambda ai,settings,spec,original,*_:essay(original,spec))
    result=run_pilot(pipeline,[binding],{'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['S1']})
    assert result['staged']==1 and result['essays']==1 and result['live_feedback_writes']==0
    assert not dashboard.payloads and not sheets.blocks
    assert next(iter(store.jobs.values()))['pilot_review']['status']=='awaiting_review'

def test_prior_tracker_feedback_guard_preserves_populated_old_section():
    from src.sheet_service import SheetService
    class Source(SheetService):
        def __init__(self,value):self.value=value
        def feedback_column(self,*_):return 'AC'
        def values(self,*_):return [[self.value]]
    from types import SimpleNamespace
    binding=SimpleNamespace(tracker_tab='Sheet')
    assert not Source('✅ ĐÃ NỘP\n— NHẬN XÉT GV —').has_prior_grading(None,binding,{'row':7})
    assert Source('✅ ĐÃ NỘP\n— NHẬN XÉT GV —\nVở chưa đạt.').has_prior_grading(None,binding,{'row':7})

def test_failed_private_pilot_cannot_be_delivered_by_regular_run(binding,settings,monkeypatch):
    from test_pipeline import components
    from src.pilot import run_pilot
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    monkeypatch.setattr(pipeline,'grade',lambda *_:(_ for _ in ()).throw(ValueError('Quote validation failed')))
    with pytest.raises(ValueError,match='Quote validation'):
        run_pilot(pipeline,[binding],{'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['S1']})
    state=next(iter(store.jobs.values()))
    assert state['pilot_review']['delivery_authorized'] is False
    assert pipeline.run([binding])['errors']
    assert not dashboard.payloads and not sheets.blocks

@pytest.mark.parametrize('status',['rejected','invalidated'])
def test_rejected_pilot_cannot_be_retried_or_automatically_published(binding,settings,status):
    from test_pipeline import components
    from src.pilot import run_pilot
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    student,source=pipeline.sources(binding,pipeline.sheets.roster(None,None))[0]
    state=store.begin(binding,student,source)
    state['payload']=pipeline.payload(binding,student,source,'graded','Saved, rejected quality.',[])
    state['pilot_review']={'status':status,'delivery_authorized':False}
    store.save(state)
    pipeline.grade=lambda *_:(_ for _ in ()).throw(AssertionError('Rejected work must not be regenerated'))
    assert pipeline.run([binding])['errors']
    with pytest.raises(ValueError,match='new explicit authorization'):
        run_pilot(pipeline,[binding],{'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['S1']})
    assert state['pilot_review']['status']==status and not dashboard.payloads and not sheets.blocks

def test_binding_requires_explicit_copy_scope(binding):
    from pydantic import ValidationError
    data=binding.model_dump();data['notebook_copy_scope']=''
    with pytest.raises(ValidationError,match='copying boundary'):
        Binding.model_validate(data)

def test_bad_unpublished_pilot_scope_keeps_history_without_notebook_lock(binding,settings):
    from test_pipeline import components
    pipeline,drive,sheets,dashboard,store=components(settings,[])
    student={'id':'S1','name':'Nguyễn Test','row':7}
    state=store.begin(binding,student,{})
    state['payload']={'state':'notebook_failed'}
    state['pilot_review']={'status':'awaiting_review'}
    store.save(state)
    assert store.locked_notebook(binding,student)
    store.invalidate_unpublished(state,{'reason':'Homework question erroneously included in notebook scope','source_reference':'Existing teacher rule: homework question/figures exempt'})
    assert not store.locked_notebook(binding,student)
    assert store.jobs[state['job_id']]['payload']['state']=='notebook_failed'
    state['phase']='complete'
    with pytest.raises(ValueError,match='unpublished'):
        store.invalidate_unpublished(state,{'reason':'No','source_reference':'No'})
