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
