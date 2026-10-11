import argparse
import os
import json
import sys
import uuid
from pathlib import Path
from .config import Settings
from .schemas import Binding
from .drive_service import DriveService, credentials, state_credentials
from .sheet_service import SheetService
from .gemini_service import GeminiService
from .state import StateStore
from .dashboard import Dashboard
from .pipeline import Pipeline

def main(argv=None):
    parser=argparse.ArgumentParser(description='Resumable IELTS homework and in-class assessment pipeline')
    parser.add_argument('--validate-config',type=Path,help='Validate local binding JSON without network/model calls')
    parser.add_argument('--preflight',action='store_true',help='Read configuration and check API/model access without grading')
    parser.add_argument('--pilot',action='store_true',help='Grade exact private selection without publishing feedback')
    parser.add_argument('--deliver-pilot',action='store_true',help='Publish an approved saved pilot without model generation')
    parser.add_argument('--deliver-pilot-notebook',action='store_true',help='Return an independently approved notebook while essays remain held; no generation')
    parser.add_argument('--deliver-teacher-authorized',action='store_true',help='Publish exact saved output explicitly requested by the teacher; no generation')
    parser.add_argument('--collect-pro-batch',action='store_true',help='Poll one saved Pro Batch pilot; no new generation or source capture')
    parser.add_argument('--collect-batches',action='store_true',help='Collect saved per-essay Batch jobs, then verify dashboard and tracker; no generation or student source capture')
    args=parser.parse_args(argv)
    if args.validate_config:
        records=json.loads(args.validate_config.read_text(encoding='utf-8-sig'))
        for record in records if isinstance(records,list) else [records]:
            Binding.model_validate(record)
        print(json.dumps({'valid':True}))
        return 0
    if not args.preflight and os.getenv('GITHUB_ACTIONS')!='true':
        raise ValueError('Live grading must run under the serialized dedicated GitHub Actions workflow')
    settings=Settings.from_env()
    delivery_only=any((args.deliver_teacher_authorized,args.deliver_pilot_notebook,
        args.deliver_pilot,args.collect_pro_batch,args.collect_batches))
    if (not args.preflight and not delivery_only
            and getattr(settings,'essay_request_mode','legacy')=='per_essay_batch'
            and not all(os.getenv(k)=='true' for k in ('GRADING_ENABLED','GEMINI_GENERATION_ENABLED'))):
        raise ValueError('New per-essay Batch grading is disabled; no student sources read')
    creds=credentials(settings.service_account)
    sheets,drive,ai=SheetService(creds),DriveService(creds),GeminiService(settings)
    state_drive=DriveService(state_credentials(settings.state_oauth)) if settings.state_oauth else drive
    bindings=sheets.guidelines(settings.guidelines_id)
    ai.preflight([settings.notebook_model,settings.essay_model])
    # Verify all folders exist and are visible without mutation.
    for client,folder in ((state_drive,settings.state_folder),(drive,settings.incoming_folder),(drive,settings.processed_folder)):
        if client.metadata(folder)['mimeType']!='application/vnd.google-apps.folder':
            raise ValueError('Configured Drive folder ID is not a folder')
    state_drive.assert_private_folder(settings.state_folder)
    if args.preflight:
        print(json.dumps({'preflight':True,'bindings':len(bindings),'live_writes':0}))
        return 0
    ai.audit=lambda data:state_drive.write_json(settings.state_folder,'attempt-'+uuid.uuid4().hex+'.json',data)
    pipeline=Pipeline(settings,sheets,drive,ai,StateStore(state_drive,settings.state_folder),Dashboard(settings))
    if args.collect_batches:
        report=pipeline.collect_batches(bindings)
        print(json.dumps(report,ensure_ascii=False))
        return 1 if report['errors'] else 0
    if args.deliver_teacher_authorized:
        from .teacher_publication import deliver_teacher_authorized
        report=deliver_teacher_authorized(pipeline,bindings,json.loads(os.environ['PILOT_SELECTION_JSON']))
        print(json.dumps(report,ensure_ascii=False))
        return 0
    if args.deliver_pilot_notebook:
        from .pilot import deliver_pilot_notebook
        report=deliver_pilot_notebook(pipeline,bindings,json.loads(os.environ['PILOT_SELECTION_JSON']))
        print(json.dumps(report,ensure_ascii=False))
        return 0
    if args.collect_pro_batch:
        from .pilot import collect_batch_pilot
        report=collect_batch_pilot(pipeline,bindings,json.loads(os.environ['PILOT_SELECTION_JSON']))
        print(json.dumps(report,ensure_ascii=False))
        return 0
    if args.deliver_pilot:
        from .pilot import deliver_pilot
        report=deliver_pilot(pipeline,bindings,json.loads(os.environ['PILOT_SELECTION_JSON']))
        print(json.dumps(report,ensure_ascii=False))
        return 0
    if args.pilot:
        from .pilot import run_pilot
        report=run_pilot(pipeline,bindings,json.loads(os.environ['PILOT_SELECTION_JSON']))
        print(json.dumps(report,ensure_ascii=False))
        return 0
    report=pipeline.run(bindings)
    print(json.dumps(report,ensure_ascii=False))
    if not report['errors'] and report['completed']==0:
        return 0
    return 1 if report['errors'] else 0

if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'failed':True,'error_type':type(exc).__name__}),file=sys.stderr)
        sys.exit(1)
