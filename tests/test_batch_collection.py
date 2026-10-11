from types import SimpleNamespace

import pytest

from conftest import FakeDrive, FakeSheets, FakeDashboard, notebook, essay
from src.pipeline import Pipeline
from src.pro_batch import BatchPending
from src.state import StateStore


def setup_saved(binding, settings, monkeypatch):
    import src.graders.essay_batch as grader
    import src.graders.essay_bundle as delivery_check
    specs=[binding.essays[0],binding.essays[0].model_copy(update={'exercise':2})]
    binding=binding.model_copy(update={'essays':specs})
    settings.essay_request_mode='per_essay_batch'
    settings.essay_model='gemini-3.1-pro-preview'
    settings.essay_service_tier='batch'
    settings.pro_max_output_tokens=16384
    drive=FakeDrive(); sheets=FakeSheets([]); dashboard=FakeDashboard()
    store=StateStore(drive,'state')
    student=sheets.roster(None,None)[0]
    source={'received_at':'2026-10-09T23:00:00+07:00','notebook_ids':['notebook_file_123'],
        'essay_texts':{'1':'Original first essay','2':'Original second essay'},'scan_id':None}
    state=store.begin(binding,student,source)
    state['notebook']=notebook().model_dump(mode='json')
    state['batch_essay_work']={'status':'queued','mode':'pro-per-essay-batch-v01'}
    state['generation_plan']={'model':'gemini-3.1-pro-preview','service_tier':'batch',
        'request_mode':'per_essay_batch','max_output_tokens':16384,'thinking_level':'medium'}
    store.save(state)
    calls=[]
    def collect(ai,settings,specs,texts,checkpoint,pending,**kwargs):
        calls.append('collect')
        checkpoint({**pending,'status':'validated'})
        return [essay(texts[str(s.exercise)],s) for s in specs]
    monkeypatch.setattr(grader,'grade_essay_batch',collect)
    # Transport/prompt tests verify the full quality contract; this integration fixture
    # verifies delivery ordering and resumability using deterministic synthetic essays.
    def verify(state,binding):
        assert state['batch_essay_work']['status']=='validated'
        assert [e['original'] for e in state['payload']['essays']]==list(source['essay_texts'].values())
    monkeypatch.setattr(delivery_check,'verify_saved_quality',verify)
    pipeline=Pipeline(settings,sheets,drive,SimpleNamespace(bind_budget=lambda *_:None),store,dashboard)
    def prohibited(*_): raise AssertionError('Collector must not read Form/PDF or grade notebook')
    pipeline.sources=prohibited
    pipeline.files=prohibited
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false')
    monkeypatch.setenv('GRADING_ENABLED','true')
    return pipeline,binding,state,drive,sheets,dashboard,calls


def test_collection_finishes_two_results_then_delivers_once(binding,settings,monkeypatch):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    result=pipeline.collect_batches([binding])
    assert result['completed']==1 and not result['errors'] and result['generation_calls']==0
    assert len(state['payload']['essays'])==2 and state['phase']=='complete'
    assert state['tracker_evidence']['exact_readback'] and state['parent_dashboard_evidence']['live_parent_ui_verified']
    assert len(sheets.blocks)==len(dashboard.payloads)==1 and drive.downloaded==[]
    assert pipeline.collect_batches([binding])['completed']==0 and calls==['collect']


def test_collection_pending_is_normal_and_never_writes_sheet(binding,settings,monkeypatch):
    import src.graders.essay_batch as grader
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    monkeypatch.setattr(grader,'grade_essay_batch',lambda *a,**kw:(_ for _ in ()).throw(BatchPending('Waiting')))
    result=pipeline.collect_batches([binding])
    assert result['pending']==1 and not result['errors']
    assert not state.get('last_error') and not state.get('payload')
    assert not sheets.blocks and not dashboard.payloads and not drive.downloaded


@pytest.mark.parametrize('condition',['grading_disabled','lesson_disabled','no_live_binding','pilot'])
def test_paid_result_is_retained_privately_when_publication_disabled(binding,settings,monkeypatch,condition):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    bindings=[binding]
    if condition=='grading_disabled':monkeypatch.setenv('GRADING_ENABLED','false')
    if condition=='lesson_disabled':bindings=[binding.model_copy(update={'ready':False})]
    if condition=='no_live_binding':bindings=[]
    if condition=='pilot':state['pilot_review']={'status':'awaiting_review','delivery_authorized':False}
    result=pipeline.collect_batches(bindings)
    assert result['staged']==1 and not result['errors'] and state['payload']
    assert not sheets.blocks and not dashboard.payloads and not drive.downloaded


def test_sheet_failure_reuses_collected_output_without_model_call(binding,settings,monkeypatch):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    sheets.fail_once=True
    assert pipeline.collect_batches([binding])['errors']
    assert state['phase']=='dashboard_verified' and state['payload']
    resumed=Pipeline(settings,sheets,drive,pipeline.ai,StateStore(drive,'state'),dashboard)
    assert resumed.collect_batches([binding])['completed']==1
    assert calls==['collect'] and len(sheets.blocks)==1


def test_changed_assignment_collects_but_does_not_publish(binding,settings,monkeypatch):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    changed=binding.model_copy(update={'version':'changed'})
    result=pipeline.collect_batches([changed])
    assert result['errors'] and state['payload'] and not sheets.blocks and not dashboard.payloads


@pytest.mark.parametrize('change',['assignment','student_name','duplicate_assignment'])
def test_regular_run_cannot_bypass_collector_publication_hold(binding,settings,monkeypatch,change):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    live=[binding]
    roster=sheets.roster(None,None)
    if change=='assignment':live=[binding.model_copy(update={'version':'changed'})]
    if change=='student_name':roster=[{**roster[0],'name':'A different student name'}]
    if change=='duplicate_assignment':live=[binding,binding]
    sheets.roster=lambda *_:roster
    first=pipeline.collect_batches(live)
    assert first['errors'] or first['staged']==1
    assert state['payload'] and calls==['collect']
    # The following scheduled grade step must not publish the saved payload that
    # collection deliberately retained. No notebook/media work is needed either.
    pipeline.sources=lambda _binding,current_roster:[(current_roster[0],state['source'])]
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','true')
    second=pipeline.run(live)
    assert second['errors'] and second['completed']==0
    assert calls==['collect'] and not sheets.blocks and not dashboard.payloads
    assert state['phase']!='complete' and not drive.downloaded


@pytest.mark.parametrize('entrypoint',['collector','regular_run'])
def test_batch_publication_uses_current_row_after_tracker_sort(binding,settings,monkeypatch,entrypoint):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    roster=[{**sheets.roster(None,None)[0],'row':19}]
    sheets.roster=lambda *_:roster
    written=[]
    original_write=sheets.write_feedback
    def write(spreadsheet,current_binding,student,block):
        written.append(student['row'])
        return original_write(spreadsheet,current_binding,student,block)
    sheets.write_feedback=write
    if entrypoint=='collector':
        result=pipeline.collect_batches([binding])
    else:
        pipeline.sources=lambda _binding,current_roster:[(current_roster[0],state['source'])]
        monkeypatch.setenv('GEMINI_GENERATION_ENABLED','true')
        result=pipeline.run([binding])
    assert result['completed']==1 and not result['errors']
    assert written==[19] and state['phase']=='complete' and calls==['collect']


def test_collection_rechecks_receipt_and_never_publishes_late(binding,settings,monkeypatch):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    state['source']['exercise_receipts']={'2':{'received_at':'2026-10-10T00:00:00+07:00'}}
    assert pipeline.collect_batches([binding])['errors']
    assert not calls and not sheets.blocks and not state.get('payload')


def test_collector_refuses_generation_enabled_context(binding,settings,monkeypatch):
    pipeline,binding,state,drive,sheets,dashboard,calls=setup_saved(binding,settings,monkeypatch)
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','true')
    with pytest.raises(ValueError,match='generation OFF'):
        pipeline.collect_batches([binding])
    assert not calls and not sheets.blocks


@pytest.mark.parametrize('front_page_state',['staged','pending','error'])
def test_collector_rotates_full_front_page_so_later_paid_jobs_are_not_starved(binding,settings,monkeypatch,front_page_state):
    import copy
    pipeline,binding,state,drive,sheets,dashboard,_=setup_saved(binding,settings,monkeypatch)
    monkeypatch.setenv('GRADING_ENABLED','false')
    settings.max_jobs=2
    pipeline.store.jobs.clear()
    for index in range(3):
        saved=copy.deepcopy(state)
        saved['job_id']=f'job-{index}'
        saved['updated_at']=f'2026-01-0{index+1}T00:00:00+00:00'
        pipeline.store.jobs[saved['job_id']]=saved
    observed=[]
    def complete(saved,_):
        observed.append(saved['job_id'])
        if saved['job_id']!='job-2':
            if front_page_state=='pending':raise BatchPending('Provider still working')
            if front_page_state=='error':raise ValueError('Saved item needs review')
        saved['payload']={'state':'graded','essays':[]}
    pipeline.complete_essay_batch=complete
    pipeline.collect_batches([binding])
    assert observed==['job-0','job-1']
    assert all(pipeline.store.jobs[key].get('batch_collection_checked_at') for key in observed)
    # Staging, pending status and failures all rotate. A saved result on the first
    # page must not consume the same limited collector slot forever.
    pipeline.collect_batches([binding])
    assert observed[2]=='job-2'
    assert pipeline.store.jobs['job-2']['payload']['state']=='graded'
    assert not sheets.blocks and not dashboard.payloads and not drive.downloaded
