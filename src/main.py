import argparse
import os
import json
import sys
import uuid
from pathlib import Path
from .config import Settings
from .schemas import Binding
from .drive_service import DriveService, credentials
from .sheet_service import SheetService
from .gemini_service import GeminiService
from .state import StateStore
from .dashboard import Dashboard
from .pipeline import Pipeline

def main(argv=None):
    parser=argparse.ArgumentParser(description='Resumable IELTS homework and in-class assessment pipeline')
    parser.add_argument('--validate-config',type=Path,help='Validate local binding JSON without network/model calls')
    parser.add_argument('--preflight',action='store_true',help='Read configuration and check API/model access without grading')
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
    creds=credentials(settings.service_account)
    sheets,drive,ai=SheetService(creds),DriveService(creds),GeminiService(settings)
    bindings=sheets.guidelines(settings.guidelines_id)
    ai.preflight([settings.notebook_model,settings.essay_model])
    # Verify all folders exist and are visible without mutation.
    for folder in (settings.state_folder,settings.incoming_folder,settings.processed_folder):
        if drive.metadata(folder)['mimeType']!='application/vnd.google-apps.folder':
            raise ValueError('Configured Drive folder ID is not a folder')
    drive.assert_private_folder(settings.state_folder)
    if args.preflight:
        print(json.dumps({'preflight':True,'bindings':len(bindings),'live_writes':0}))
        return 0
    ai.audit=lambda data:drive.write_json(settings.state_folder,'attempt-'+uuid.uuid4().hex+'.json',data)
    report=Pipeline(settings,sheets,drive,ai,StateStore(drive,settings.state_folder),Dashboard(settings)).run(bindings)
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
