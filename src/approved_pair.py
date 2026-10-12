"""Execute only the separately budget-authorized 2026-10-12 pair, without discovery."""
import json,os,sys
from dataclasses import replace
from .config import Settings
from .drive_service import DriveService,state_credentials,credentials
from .sheet_service import SheetService
from .state import StateStore
from .schemas import Binding
from .gemini_service import GeminiService
from .pipeline import Pipeline
from .dashboard import Dashboard
from .pro_batch import BatchPending

def main():
    submit=sys.argv[1:]==['submit']
    if not submit and sys.argv[1:]!=['collect']:raise ValueError('Explicit submit or collect required')
    if os.getenv('GITHUB_ACTIONS')!='true':raise ValueError('Serialized workflow required')
    if submit and not all(os.getenv(k)=='true' for k in ('GRADING_ENABLED','GEMINI_GENERATION_ENABLED')):raise ValueError('Generation disabled')
    if not submit and os.getenv('GEMINI_GENERATION_ENABLED')!='false':raise ValueError('Read-only collector required')
    settings=Settings.from_env();owner=DriveService(state_credentials(settings.state_oauth));store=StateStore(owner,settings.state_folder)
    refs=[f for f in owner.folder_files(settings.state_folder) if f['name']=='approved-pair-v10-20261012.json'];assert len(refs)==1
    auth=json.loads(owner.download(refs[0]['id'])[0]);assert auth['new_ceiling_vnd']==11400 and auth['class_ceiling_vnd']==59900
    assert len(auth['jobs'])==2 and {j['student_id'] for j in auth['jobs']}=={'25','4'}
    creds=credentials(settings.service_account);report=[]
    for selected in auth['jobs']:
        state=store.jobs[selected['job_id']];binding=Binding.model_validate(state['binding'])
        assert binding.class_name=='IELTS 48' and binding.task_code=='IELTS-WRITING-W14' and len(binding.essays)==2
        assert state['student']['id']==selected['student_id'] and state['trial_cost_ceiling_vnd']==5700
        assert state['cost_exception']['generation_limits']=={'gemini-3.1-pro-preview':2}
        assert state['cost_exception']['authority']==auth['authority']+' Student '+selected['student_id']
        if not submit and not state.get('batch_essay_work'):
            report.append({'student_id':selected['student_id'],'status':'not_submitted'});continue
        bounded=replace(settings,student_budget_vnd=selected['student_cumulative_ceiling_vnd'])
        ai=GeminiService(bounded);pipeline=Pipeline(bounded,SheetService(creds),DriveService(creds),ai,store,Dashboard(bounded))
        try:
            work=state.get('batch_essay_work',{})
            if not submit and work.get('status')=='held' and 'result' not in work:
                from .pro_batch_essays import reconcile_saved_metadata
                ai.job_id=state['job_id'];ai.bind_budget(store,binding,state)
                recovered=reconcile_saved_metadata(ai,work['requests'])
                work['result']={k:v.model_dump(mode='json') for k,v in recovered.items()}
                work['status']='received';store.save(state)
            pipeline.grade(state,binding)
            result='staged'
        except BatchPending:result='pending'
        except Exception as exc:
            state['last_error']={'type':type(exc).__name__,'reason':str(exc) if isinstance(exc,ValueError) else 'Inspect private provider state'};store.save(state);result='held'
        calls=[c for c in ai.budget.data['calls'].values() if c['job_id']==state['job_id']] if ai.budget else []
        report.append({'student_id':selected['student_id'],'status':result,'requests_reserved':len(calls),
            'cost_or_reserve_vnd':sum(c.get('accounted_vnd',c['reserved_vnd']) for c in calls)})
    owner.write_json(settings.state_folder,'approved-pair-v10-20261012-report.json',{'students':report})
    print(json.dumps({'students':report,'publication':False}))
if __name__=='__main__':main()
