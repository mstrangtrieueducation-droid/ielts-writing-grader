import copy
import hashlib
import pytest
from src.pilot import deliver_pilot_notebook,payload_digest
from conftest import notebook
from test_pipeline import components

def prepared(binding,settings):
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    student,source=pipeline.sources(binding,pipeline.sheets.roster(None,None))[0]
    state=store.begin(binding,student,source)
    state['notebook']=notebook().model_dump(mode='json')
    state['bundle_work']={'status':'held','result':{'rejected':'must never be exposed'}}
    state['pilot_review']={'status':'rejected','delivery_authorized':False}
    # Stable fake files, like immutable captured real PDFs.
    drive.download=lambda fid:(b'original PDF '+fid.encode(),'application/pdf')
    state['notebook_publication_review']={'status':'approved','delivery_authorized':True,
        'quality_evidence':'Independent full-page visual audit',
        'notebook_sha256':payload_digest(state['notebook']),
        'file_checksums':{fid:hashlib.sha256(drive.download(fid)[0]).hexdigest()
            for fid in binding.source_file_ids+source['notebook_ids']}}
    pipeline.grade=lambda *_:(_ for _ in ()).throw(AssertionError('No generation'))
    return pipeline,drive,sheets,dashboard,store,state,{'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['S1']}

def test_notebook_return_does_not_release_rejected_essays_or_complete_job(binding,settings,monkeypatch):
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false')
    p,d,s,dash,store,state,selection=prepared(binding,settings)
    original=copy.deepcopy(state['bundle_work']);phase=state['phase']
    result=deliver_pilot_notebook(p,[binding],selection)
    assert result['tracker_verified'] and result['grading_complete'] is False
    assert state['phase']==phase and state['payload'] is None
    assert state['bundle_work']==original and state['pilot_review']['status']=='rejected'
    assert dash.payloads[0]['essays']==[] and dash.payloads[0]['state']=='pending'
    assert 'đang chờ trả bản chữa' in s.blocks[0]
    assert 'Đã trả' not in s.blocks[0] and 'must never' not in s.blocks[0]

@pytest.mark.parametrize('fault',['no_approval','changed_verdict','changed_file','hidden_essays','changed_identity','generation_on'])
def test_notebook_component_safety_guards(binding,settings,monkeypatch,fault):
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false')
    p,d,s,dash,store,state,selection=prepared(binding,settings)
    if fault=='no_approval':state['notebook_publication_review']['delivery_authorized']=False
    if fault=='changed_verdict':state['notebook']['summary_vi']='Changed after review'
    if fault=='changed_file':d.download=lambda fid:(b'new file','application/pdf')
    if fault in ('hidden_essays','changed_identity'):
        payload=p.payload(binding,state['student'],state['source'],'pending',state['notebook']['summary_vi']+'\nBài viết: đang chờ trả bản chữa.')
        if fault=='hidden_essays':payload['essays']=[{'secret':'rejected essay'}]
        else:payload['student_id']='another student'
        state['notebook_publication']={'payload':payload}
    if fault=='generation_on':monkeypatch.setenv('GEMINI_GENERATION_ENABLED','true')
    with pytest.raises(ValueError):deliver_pilot_notebook(p,[binding],selection)
    assert not dash.payloads and not s.blocks

def test_tracker_retry_preserves_incomplete_job_and_raw(binding,settings,monkeypatch):
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false')
    p,d,s,dash,store,state,selection=prepared(binding,settings)
    s.fail_once=True
    with pytest.raises(RuntimeError):deliver_pilot_notebook(p,[binding],selection)
    assert state['notebook_publication']['dashboard_evidence']['live_ui_verified']
    assert state['phase']!='complete' and not state['payload']
    assert deliver_pilot_notebook(p,[binding],selection)['tracker_verified']
