import src.pipeline as module
from src.pipeline import Pipeline
from src.state import StateStore
from conftest import FakeDrive, FakeSheets, FakeDashboard, notebook, essay

def components(settings, rows):
    drive=FakeDrive(); sheets=FakeSheets(rows); dashboard=FakeDashboard(); store=StateStore(drive,'state')
    return Pipeline(settings,sheets,drive,None,store,dashboard),drive,sheets,dashboard,store

def test_late_has_no_model_or_student_media_reads(binding,settings,monkeypatch):
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['10/10/2026 00:00:00','Nguyễn Test','notebook_file_123','Essay']])
    monkeypatch.setattr(module,'grade_notebook',lambda *_: (_ for _ in ()).throw(AssertionError('No late grading')))
    result=pipeline.run([binding])
    assert result['completed']==1 and not result['errors'] and drive.downloaded==[]
    assert dashboard.payloads[0]['state']=='too_late' and dashboard.payloads[0]['essays']==[]
    assert '10/10/2026 00:00:00' in sheets.blocks[0]

def test_notebook_failure_short_circuits(binding,settings,monkeypatch):
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    monkeypatch.setattr(module,'grade_notebook',lambda *_: notebook('typed_or_printed'))
    monkeypatch.setattr(module,'grade_essay',lambda *_: (_ for _ in ()).throw(AssertionError('Must not grade locked essay')))
    result=pipeline.run([binding])
    assert result['completed']==1 and dashboard.payloads[0]['state']=='notebook_failed'
    assert dashboard.payloads[0]['essays']==[]
    assert 'KHÔNG ĐƯỢC CHẤM BÀI VIẾT' in sheets.blocks[0]

def test_delivery_retry_does_not_regrade(binding,settings,monkeypatch):
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    calls=[]
    monkeypatch.setattr(module,'grade_notebook',lambda *_: notebook())
    def grade(ai,settings,spec,original,*args): calls.append(original); return essay(original,spec)
    monkeypatch.setattr(module,'grade_essay',grade)
    sheets.fail_once=True
    first=pipeline.run([binding]); assert first['errors'] and len(calls)==1
    # New process loads the durable Drive checkpoint after a tracker failure.
    resumed=Pipeline(settings,sheets,drive,None,StateStore(drive,'state'),dashboard)
    second=resumed.run([binding]); assert second['completed']==1 and not second['errors'] and len(calls)==1
    third=resumed.run([binding]); assert third['completed']==0 and len(calls)==1

def test_unknown_identity_never_becomes_false_missing(binding,settings):
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Unmapped Name','notebook_file_123','Essay']])
    result=pipeline.run([binding]); assert result['errors'] and not dashboard.payloads

def test_missing_updates_to_late_receipt(binding,settings):
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay']])
    assert pipeline.run([binding])['completed']==1
    assert dashboard.payloads[-1]['state']=='missing'
    sheets.rows.append(['10/10/2026 01:00:00','Nguyễn Test','notebook_file_123','Essay'])
    assert pipeline.run([binding])['completed']==1
    assert dashboard.payloads[-1]['state']=='too_late' and not drive.downloaded

def test_latest_nonblank_exercise_with_own_receipt(binding,settings):
    pipeline,*_=components(settings,[['Time','Name','Notes','Essay'],
        ['09/10/2026 20:00:00','Nguyễn Test','notebook_file_123','First essay'],
        ['09/10/2026 22:00:00','Nguyễn Test','notebook_file_123',''],
        ['10/10/2026 01:00:00','Nguyễn Test','notebook_file_123','Late replacement']])
    source=pipeline.sources(binding,pipeline.sheets.roster(None,None))[0][1]
    assert source['essay_texts']['1']=='First essay'
    assert source['exercise_receipts']['1']['form_row']==2
