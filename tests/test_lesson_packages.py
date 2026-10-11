import json
import pytest
import src.lesson_packages as module

def library(binding,tmp_path,monkeypatch):
    root=tmp_path/'library';root.mkdir()
    package={'id':'B29-HOMEWORK','version':'v01','lesson':29,'quality_status':'prepared_not_live_accepted',
        'essay_fingerprint':module.essay_fingerprint(binding.essays),
        'notebook_fingerprint':module.notebook_fingerprint(binding),
        'assigned_source_sha256':['verifiedhash'],'prompt_files':[]}
    (root/'manifest.json').write_text(json.dumps(package),encoding='utf-8')
    (root/'catalog.json').write_text(json.dumps({'packages':[{'manifest':'manifest.json','manifest_sha256':module.fingerprint(package)}]}),encoding='utf-8')
    monkeypatch.setattr(module,'ROOT',root)
    return root

def test_same_lesson_reused_by_another_class_without_copying_authority(binding,tmp_path,monkeypatch):
    library(binding,tmp_path,monkeypatch)
    first=module.verify_package_sources(binding,{'source1':'verifiedhash'})
    other=binding.model_copy(update={'class_name':'IELTS 99','form_spreadsheet_id':'another-form',
        'regrade_authorizations':{'S2':'A separate class permission'}})
    assert module.verify_package_sources(other,{'source-copy':'verifiedhash'})==first
    assert set(first)=={'id','version','quality_status'}

def test_changed_source_or_copy_requirement_needs_new_version(binding,tmp_path,monkeypatch):
    library(binding,tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='source changed'):module.verify_package_sources(binding,{'source1':'newhash'})
    other=binding.model_copy(update={'notebook_copy_scope':'A different assigned lesson'})
    with pytest.raises(ValueError,match='copying requirements'):module.verify_package_sources(other,{'source1':'verifiedhash'})

def test_modified_manifest_is_not_silently_reused(binding,tmp_path,monkeypatch):
    root=library(binding,tmp_path,monkeypatch)
    p=json.loads((root/'manifest.json').read_text());p['quality_status']='accepted'
    (root/'manifest.json').write_text(json.dumps(p))
    with pytest.raises(ValueError,match='manifest changed'):module.resolve_package(binding.essays)

def test_rejected_live_package_blocks_other_classes_before_generation(binding,tmp_path,monkeypatch):
    root=library(binding,tmp_path,monkeypatch)
    package=json.loads((root/'manifest.json').read_text())
    package['quality_status']='live_quality_rejected'
    (root/'manifest.json').write_text(json.dumps(package))
    catalog=json.loads((root/'catalog.json').read_text())
    catalog['packages'][0]['manifest_sha256']=module.fingerprint(package)
    (root/'catalog.json').write_text(json.dumps(catalog))
    # Preserved prompts can still be inspected without activation or generation.
    assert module.resolve_package(binding.essays)['quality_status']=='live_quality_rejected'
    other=binding.model_copy(update={'class_name':'IELTS 99'})
    with pytest.raises(ValueError,match='failed live quality review'):
        module.verify_package_sources(other,{'source1':'verifiedhash'})

def test_new_draft_is_not_live_approval_and_text_hash_is_portable(binding,tmp_path,monkeypatch):
    import hashlib
    root=library(binding,tmp_path,monkeypatch)
    source=tmp_path/'prompt.txt';source.write_bytes(b'First\r\nSecond\r\n')
    package=json.loads((root/'manifest.json').read_text())
    package['quality_status']='prepared_requires_live_trial'
    package['prompt_files']=[{'path':'prompt.txt','normalization':'lf',
        'sha256':hashlib.sha256(b'First\nSecond\n').hexdigest()}]
    (root/'manifest.json').write_text(json.dumps(package))
    catalog=json.loads((root/'catalog.json').read_text())
    catalog['packages'][0]['manifest_sha256']=module.fingerprint(package)
    (root/'catalog.json').write_text(json.dumps(catalog))
    with pytest.raises(ValueError,match='separately authorized live quality trial'):
        module.verify_package_sources(binding,{'source1':'verifiedhash'})
    source.write_bytes(b'First\nSecond\n')
    assert module.resolve_package(binding.essays)['quality_status']=='prepared_requires_live_trial'
    source.write_bytes(b'Changed\nSecond\n')
    with pytest.raises(ValueError,match='prompt changed'):module.resolve_package(binding.essays)

def test_finite_trial_binds_exact_package_student_and_authority(binding,tmp_path,monkeypatch):
    import copy
    root=library(binding,tmp_path,monkeypatch)
    p=json.loads((root/'manifest.json').read_text());p['quality_status']='prepared_requires_live_trial'
    (root/'manifest.json').write_text(json.dumps(p))
    (root/'catalog.json').write_text(json.dumps({'packages':[{'manifest':'manifest.json','manifest_sha256':module.fingerprint(p)}]}))
    binding=binding.model_copy(update={'regrade_authorizations':{'S1':'Teacher approved one bounded trial'}})
    authority=binding.regrade_authorizations['S1']
    state={'job_id':'new-job','student':{'id':'S1'},'pilot_review':{'status':'awaiting_review'},
        'cost_exception':{'job_id':'new-job','student_id':'S1','authority':authority,
            'maximum_generation_calls':1,'generation_limits':{'gemini-3.1-pro-preview':1}},
        'lesson_package_trial':{'package_id':p['id'],'package_version':p['version'],
            'manifest_sha256':module.fingerprint(p),'job_id':'new-job','student_id':'S1','authority':authority}}
    result=module.verify_package_sources(binding,{'source':'verifiedhash'},trial_state=state)
    assert result['quality_status']=='prepared_requires_live_trial'
    for key,value in [('student_id','S2'),('package_version','newer'),('manifest_sha256','different')]:
        altered=copy.deepcopy(state);altered['lesson_package_trial'][key]=value
        with pytest.raises(ValueError,match='separately authorized'):
            module.verify_package_sources(binding,{'source':'verifiedhash'},trial_state=altered)
    with pytest.raises(ValueError,match='source changed'):
        module.verify_package_sources(binding,{'source':'changed'},trial_state=state)
