import copy
import hashlib
import pytest
from conftest import essay,notebook
from test_pipeline import components
from src.pilot import payload_digest
from src.parsers import digest
from src.teacher_publication import saved_essays,deliver_teacher_authorized


def setup(binding,settings):
    binding=binding.model_copy(update={'essays':binding.essays+[binding.essays[0].model_copy(update={'exercise':2})],
        'essay_columns':{1:'D',2:'E'}})
    pipeline,drive,sheets,dashboard,store=components(settings,[['Time','Name','Notes','One','Two'],
        ['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','First original.','Second original.']])
    student,source=pipeline.sources(binding,sheets.roster(None,None))[0]
    state=store.begin(binding,student,source);state['notebook']=notebook().model_dump(mode='json')
    raw=[]
    for spec in binding.essays:
        original=source['essay_texts'][str(spec.exercise)]
        result=essay(original,spec).model_dump(exclude={'original','word_count','paragraph_count','band_scores'})
        result.update(source_digest=digest(original),language_checks=[],numeric_checks=[],comparisons=[],numeric_evidence=[],generated_numbers=[])
        raw.append(result)
    state['bundle_work']={'status':'held','result':{'essays':raw}}
    state['pilot_review']={'status':'rejected','delivery_authorized':False,'quality_evidence':'Retained independent findings'}
    state['teacher_publication']={'payload':pipeline.payload(binding,student,source,'graded','Vở đạt yêu cầu.',saved_essays(state))}
    state['teacher_publication_authorization']={'kind':'explicit_existing_output','authority':'Teacher explicitly requests publishing these exact saved results despite explained findings.',
        'authorized_at':'2026-10-12T01:00:00+07:00','quality_findings_acknowledged':True,'job_id':state['job_id'],'student_id':student['id'],
        'raw_sha256':payload_digest(state['bundle_work']['result']),'binding_sha256':payload_digest(state['binding']),
        'source_sha256':payload_digest(source),'payload_sha256':payload_digest(state['teacher_publication']['payload']),
        'file_checksums':{fid:hashlib.sha256(b'exact bytes').hexdigest() for fid in binding.source_file_ids+source['notebook_ids']}}
    pipeline.files=lambda ids:[(fid,b'exact bytes','application/pdf') for fid in ids]
    pipeline.grade=lambda *_:(_ for _ in ()).throw(AssertionError('Must not grade during delivery'))
    return pipeline,binding,state,{'class_name':binding.class_name,'task_code':binding.task_code,'student_ids':['S1']}


def test_explicit_teacher_delivery_publishes_normally_and_preserves_quality_rejection(binding,settings):
    p,b,s,selection=setup(binding,settings);before=copy.deepcopy(s['bundle_work'])
    report=deliver_teacher_authorized(p,[b.model_copy(update={'ready':False})],selection)
    assert report['essays']==2 and report['tracker_verified'] and report['model_generation_calls']==0
    assert s['bundle_work']==before and s['pilot_review']['status']=='rejected'
    assert s['teacher_publication']['status']=='published' and s['payload'] is None
    assert len(p.dashboard.payloads[0]['essays'])==2 and 'Đã trả 2/2 bài chữa' in p.sheets.blocks[0]


@pytest.mark.parametrize('change',['no_authority','raw','payload','binding','source_file'])
def test_delivery_rejects_unapproved_or_changed_content(binding,settings,change):
    p,b,s,selection=setup(binding,settings)
    if change=='no_authority':s['teacher_publication_authorization']['authority']=''
    if change=='raw':s['bundle_work']['result']['essays'][0]['summary_vi']='Changed model feedback without new authorization.'
    if change=='payload':s['teacher_publication']['payload']['warning']='Changed approved payload'
    if change=='binding':b=b.model_copy(update={'source_reference':'Changed source reference'})
    if change=='source_file':p.files=lambda ids:[(fid,b'new bytes','application/pdf') for fid in ids]
    with pytest.raises(ValueError):deliver_teacher_authorized(p,[b],selection)
    assert not p.dashboard.payloads and not p.sheets.blocks


def test_teacher_delivery_does_not_override_notebook_lock_or_call_model(binding,settings,monkeypatch):
    p,b,s,selection=setup(binding,settings)
    monkeypatch.setattr(p.store,'locked_notebook',lambda *_:True)
    with pytest.raises(ValueError,match='notebook eligibility'):deliver_teacher_authorized(p,[b],selection)
    monkeypatch.setattr(p.store,'locked_notebook',lambda *_:False)
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','true')
    with pytest.raises(ValueError,match='generation OFF'):deliver_teacher_authorized(p,[b],selection)
    assert not p.dashboard.payloads and not p.sheets.blocks


def test_saved_delivery_can_resume_tracker_failure_without_regrading(binding,settings):
    p,b,s,selection=setup(binding,settings);p.sheets.fail_once=True
    with pytest.raises(RuntimeError,match='Transient'):deliver_teacher_authorized(p,[b],selection)
    assert s['teacher_publication']['dashboard_evidence']['live_ui_verified']
    assert deliver_teacher_authorized(p,[b],selection)['tracker_verified']

def test_parent_portal_failure_does_not_mark_publication_complete(binding,settings):
    p,b,s,selection=setup(binding,settings)
    p.dashboard.verify_parent_ui=lambda *_:(_ for _ in ()).throw(ValueError('Parent cards absent'))
    with pytest.raises(ValueError,match='Parent cards absent'):deliver_teacher_authorized(p,[b],selection)
    assert s['teacher_publication'].get('status')!='published'
    assert s['teacher_publication']['tracker_evidence']['exact_readback']
    assert s['pilot_review']['status']=='rejected'
