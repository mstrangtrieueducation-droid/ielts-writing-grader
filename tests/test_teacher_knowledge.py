import copy
import hashlib
import json
from types import SimpleNamespace as N
import pytest
from src.teacher_knowledge import verify_corpus,render_corpus,load_corpus
from src.lesson_packages import fingerprint
from src.graders.essay_bundle import prepare_bundle
from src.graders.copy_grader import grade_notebook
from conftest import FakeDrive,notebook,pdf
from test_hybrid_bundle import originals

def corpus():
    text='Lý thuyết nguyên văn\r\nBài mẫu\nBản dịch\nLưu ý cuối nguồn.'
    d={'id':'L06','lesson':6,'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    c={'schema_version':1,'through_lesson':14,'documents':[d]}
    return c,{'filename':'teacher-full.json','through_lesson':14,'sha256':fingerprint(c),
              'documents':[{k:d[k] for k in ('id','lesson','sha256')}]}

def test_full_source_bytes_and_tail_reach_prompt_once(binding,monkeypatch):
    from src import lesson_packages
    c,r=corpus();specs,texts,_=originals(binding)
    monkeypatch.setattr(lesson_packages,'resolve_package',lambda _: {'id':'B14','version':'v09','full_teacher_sources':r})
    with pytest.raises(ValueError,match='summary-only'):prepare_bundle(specs,texts)
    prompt,_=prepare_bundle(specs,texts,teacher_knowledge=c)
    assert prompt.count(c['documents'][0]['text'])==1
    assert json.loads(prompt.split('\n')[-1])[0]['original']==texts['1']
    # Old paid requests can restore their frozen prompt without loading new teacher files.
    prepare_bundle(specs,texts,frozen_replay=True)

def test_truncated_changed_or_future_corpus_is_held():
    c,r=corpus()
    shortened=copy.deepcopy(c);shortened['documents'][0]['text']='Summary'
    with pytest.raises(ValueError,match='changed'):verify_corpus(shortened,r)
    missing=copy.deepcopy(c);missing['documents']=[];rr={**r,'sha256':fingerprint(missing)}
    with pytest.raises(ValueError,match='omits'):verify_corpus(missing,rr)
    future=copy.deepcopy(c);future['documents'][0]['lesson']=15
    rr={**r,'sha256':fingerprint(future),'documents':[{**r['documents'][0],'lesson':15}]}
    with pytest.raises(ValueError,match='future'):verify_corpus(future,rr)

def test_private_corpus_loaded_once_and_frozen_without_live_data_changes():
    c,r=corpus();drive=FakeDrive();drive.state[r['filename']]=c;saved=[]
    store=N(drive=drive,folder='state',save=lambda state:saved.append(copy.deepcopy(state)))
    state={};package={'full_teacher_sources':r}
    assert load_corpus(store,state,package)==c
    assert load_corpus(store,state,package)==c
    assert len(saved)==1 and drive.downloaded==[r['filename']]

def test_flash_receives_all_teacher_pdf_bytes_and_copying_boundary(binding,settings):
    teacher=('teacher',pdf(),'application/pdf');student=('notebook_file_123',pdf(),'application/pdf')
    calls=[]
    def run(model,prompt,schema,attachments):
        calls.append((model,prompt,attachments));return notebook()
    grade_notebook(N(structured=run),settings,binding,[student],[teacher],{'notebook_file_123':1})
    assert calls[0][2]==[teacher,student]
    assert binding.notebook_copy_scope in calls[0][1]
    assert 'English models, Vietnamese translations' in calls[0][1]
    assert '"teacher_reference_pages": {"teacher": 1}' in calls[0][1]
    with pytest.raises(ValueError,match='checklist alone'):
        grade_notebook(N(structured=run),settings,binding,[student],[],{'notebook_file_123':1})
    assert len(calls)==1

def test_full_teacher_input_is_budgeted_and_cannot_be_spent_on_flash(binding,monkeypatch):
    from test_cost_control import service
    from src.schemas import NotebookResult
    from src.cost_control import cost_vnd
    ai,calls,drive,store=service(binding,monkeypatch)
    ai.essay_model='gemini-3.1-pro-preview'
    ai.pro_max_output_tokens=16384
    counts=[]
    def count(**kwargs):
        counts.append(kwargs)
        return N(total_tokens=40000 if len(counts)==1 else 3000)
    ai.client.models.count_tokens=count
    ai.preflight_bundle_prompt('COMPLETE TEACHER SOURCE')
    assert counts[0]['contents'][0]=='COMPLETE TEACHER SOURCE'
    assert ai.planned_essay_reserve==cost_vnd(ai.essay_model,48256,16384)
    # Flash alone fits, but Flash + the unchanged complete-text Pro request does not.
    ai.budget.trial_limit=ai.planned_essay_reserve+1
    with pytest.raises(ValueError,match='trial cost ceiling'):
        ai.structured('gemini-3.8-flash','inspect notebook',NotebookResult)
    assert not calls and not ai.budget.data['calls']
