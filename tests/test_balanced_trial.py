import copy,json
from types import SimpleNamespace as N
import pytest
from src import balanced_trial as trial
from src.parsers import digest

def test_scoped_submission_is_once_and_collection_cannot_generate(monkeypatch):
    rows=[{'key':'a','request':{'generationConfig':{'maxOutputTokens':5200}}}]
    content=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
    state={'new_ceiling_vnd':25000,'authorized_students':['25','4'],'teacher_authorization':'Explicit trial',
           'class_plan_reserve_vnd':24559,'pilot_requests':rows,'pilot_requests_sha256':digest(content),
           'pilot_costs':[{'reserved_vnd':1900}],'display_name':'private-trial'}
    saved=[];creates=[]
    class Owner:
        def folder_files(self,folder):return [{'name':trial.NAME,'id':'private'}]
        def download(self,fid):return json.dumps(state).encode(),'application/json'
        def write_json(self,folder,name,value):state.clear();state.update(copy.deepcopy(value));saved.append(copy.deepcopy(value))
    client=N(files=N(upload=lambda **kw:N(name='files/input')),
        batches=N(create=lambda **kw:(creates.append(kw) or N(name='batches/once')),
                  get=lambda **kw:N(state=N(name='JOB_STATE_PENDING'))))
    monkeypatch.setattr(trial,'DriveService',lambda creds:Owner())
    monkeypatch.setattr(trial,'state_credentials',lambda auth:None)
    monkeypatch.setattr(trial.genai,'Client',lambda **kw:client)
    for k,v in {'GITHUB_ACTIONS':'true','GRADING_ENABLED':'true','GEMINI_GENERATION_ENABLED':'true',
                'GOOGLE_STATE_OAUTH_JSON':'{}','FOLDER_STATE_ID':'private','GEMINI_API_KEY':'synthetic'}.items():monkeypatch.setenv(k,v)
    trial.main('submit');assert len(creates)==1
    assert any(s['pilot']['status']=='submission_intent' for s in saved)
    trial.main('submit');assert len(creates)==1
    monkeypatch.setenv('GEMINI_GENERATION_ENABLED','false')
    trial.main('collect');assert len(creates)==1
    with pytest.raises(ValueError):trial.main('submit')
