"""Execute/collect one teacher-authorized pilot inside the 25k class trial.

Dedicated serialized workflow, private immutable inputs, one Batch creation;
no retries, model fallback, broad schedule activation or publication.
"""
import json,os,tempfile
from pathlib import Path
from datetime import datetime,timezone
from google import genai
from google.genai import types
from .drive_service import DriveService,state_credentials
from .parsers import digest
from .cost_control import cost_vnd
from .graders.balanced_plan import validate_response
from .pro_batch_essays import parse_batch_response

NAME='balanced-class-trial-IELTS48-W14-20261012.json'
def main(action):
    if action not in ['submit','collect'] or os.getenv('GITHUB_ACTIONS')!='true':
        raise ValueError('Explicit serialized trial workflow required')
    if action=='submit' and any(os.getenv(k)!='true' for k in ['GRADING_ENABLED','GEMINI_GENERATION_ENABLED']):
        raise ValueError('Scoped trial generation is disabled')
    owner=DriveService(state_credentials(json.loads(os.environ['GOOGLE_STATE_OAUTH_JSON'])))
    folder=os.environ['FOLDER_STATE_ID'];files=[f for f in owner.folder_files(folder) if f['name']==NAME]
    if len(files)!=1:raise ValueError('Exactly one private trial authorization required')
    trial=json.loads(owner.download(files[0]['id'])[0])
    if trial['new_ceiling_vnd']!=25000 or trial['authorized_students']!=['25','4'] or not trial.get('teacher_authorization'):
        raise ValueError('Wrong trial scope')
    if trial['class_plan_reserve_vnd']>25000:raise ValueError('Class plan exceeds authorization')
    rows=trial['pilot_requests'];content=trial.get('pilot_requests_jsonl') or ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
    if [json.loads(line) for line in content.splitlines() if line.strip()]!=rows:
        raise ValueError('Frozen JSONL differs from authorization')
    if digest(content)!=trial['pilot_requests_sha256']:raise ValueError('Frozen request changed')
    for r in rows:
        if r['request']['generationConfig']['maxOutputTokens']!=5200:raise ValueError('Output cap changed')
    client=genai.Client(api_key=os.environ['GEMINI_API_KEY'],http_options=types.HttpOptions(
        timeout=120000,retry_options=types.HttpRetryOptions(attempts=1)))
    def save():owner.write_json(folder,NAME,trial)
    stage=trial.setdefault('pilot',{'status':'prepared'})
    if action=='submit':
        if stage['status']!='prepared':
            print(json.dumps({'status':stage['status'],'new_generation':False}));return
        reserve=sum(r['reserved_vnd'] for r in trial['pilot_costs'])
        if reserve>25000:raise ValueError('Pilot exceeds class budget')
        stage.update(status='upload_intent',reserved_vnd=reserve,created_at=datetime.now(timezone.utc).isoformat())
        save()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'requests.jsonl';p.write_text(content,encoding='utf8')
            try:upload=client.files.upload(file=str(p),config=types.UploadFileConfig(mime_type='jsonl',display_name=trial['display_name']+'-input'))
            except Exception:
                stage['status']='upload_unknown';save();raise
        stage.update(status='submission_intent',input_file=upload.name);save()
        try:job=client.batches.create(model='gemini-3.1-pro-preview',src=upload.name,
            config=types.CreateBatchJobConfig(display_name=trial['display_name']))
        except Exception:
            stage['status']='submission_unknown';save();raise
        if not job.name:stage['status']='submission_unknown';save();raise ValueError('No provider identity')
        stage.update(status='submitted',batch_name=job.name);save()
        print(json.dumps({'status':'submitted','students':2,'essays':4,'reserved_vnd':reserve,'new_class_ceiling_vnd':25000}));return
    if stage['status']=='submission_unknown' and not stage.get('batch_name'):
        jobs=[j for j in client.batches.list() if j.display_name==trial['display_name']]
        if len(jobs)!=1:raise ValueError('Creation uncertain; no regeneration allowed')
        stage.update(status='submitted',batch_name=jobs[0].name);save()
    if stage['status'] in ['received','held','reviewed']:
        print(json.dumps({'status':stage['status'],'new_generation':False}));return
    if not stage.get('batch_name'):
        print(json.dumps({'status':stage['status'],'new_generation':False}));return
    job=client.batches.get(name=stage['batch_name']);provider=job.state.name;stage['provider_state']=provider;save()
    if provider not in ['JOB_STATE_SUCCEEDED','JOB_STATE_FAILED','JOB_STATE_CANCELLED','JOB_STATE_EXPIRED']:
        print(json.dumps({'status':'pending','provider_state':provider,'new_generation':False}));return
    output=getattr(job.dest,'file_name',None) if job.dest else None
    if not output:stage['status']='held';save();raise ValueError('Terminal job has no result file; no retry')
    raw=client.files.download(file=output);raw=raw.decode('utf8') if isinstance(raw,bytes) else raw
    owner.write_json(folder,trial['display_name']+'-output.json',{'raw':raw,'sha256':digest(raw)})
    by_key={};
    for line in raw.splitlines():
        if line.strip():
            r=json.loads(line);key=r['key']
            if key in by_key:raise ValueError('Duplicate provider output')
            by_key[key]=r
    stage.update(results={},errors=[],actual_cost_vnd=0)
    for spec in trial['pilot_sources']:
        r=by_key.get(spec['key'])
        if not r or not r.get('response'):
            stage['errors'].append({'student_id':spec['student_id'],'reason':'missing_or_error_response'});continue
        response,usage=parse_batch_response(r['response']);candidates=response.candidates or []
        prompt=usage.get('prompt_token_count');answer=usage.get('candidates_token_count');thought=usage.get('thoughts_token_count')
        cost=cost_vnd('gemini-3.1-pro-preview',prompt,answer+thought,service_tier='batch') if None not in [prompt,answer,thought] else None
        stage['actual_cost_vnd']+=cost or spec['reserved_vnd']
        finish=candidates[0].finish_reason.name if len(candidates)==1 else 'INVALID'
        entry={'response_text':response.text,'finish_reason':finish,'usage':usage,'accounted_or_reserved_vnd':cost or spec['reserved_vnd']}
        try:entry['validated']=validate_response(json.loads(response.text),spec['originals'],{1:150,2:150},finish).model_dump(mode='json')
        except Exception as exc:stage['errors'].append({'student_id':spec['student_id'],'reason':type(exc).__name__})
        stage['results'][spec['student_id']]=entry
    stage['status']='held' if stage['errors'] else 'received'
    stage['quality_review']='pending_independent_review';save()
    print(json.dumps({'status':stage['status'],'actual_or_reserved_vnd':stage['actual_cost_vnd'],'errors':stage['errors'],'new_generation':False}))

if __name__=='__main__':
    import sys
    main(sys.argv[1])
