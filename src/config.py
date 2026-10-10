import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

CLASS_SHEET_MAP = {}  # Actual classroom source IDs live in a GitHub Secret, never public code.

@dataclass(frozen=True)
class Settings:
    api_key: str
    service_account: dict
    guidelines_id: str
    state_folder: str
    incoming_folder: str
    processed_folder: str
    notebook_model: str
    essay_model: str
    master_key: bytes
    dashboard_base_url: str
    class_sheets: dict
    output_dir: Path
    max_jobs: int = 12
    requests_per_minute: int = 6
    retry_attempts: int = 6
    state_oauth: dict | None = None

    @classmethod
    def from_env(cls):
        def required(key):
            value = os.getenv(key, '').strip()
            if not value or value.startswith('YOUR_'):
                raise ValueError(f'Missing configuration: {key}')
            return value
        key = base64.b64decode(required('DASHBOARD_MASTER_KEY'), validate=True)
        if len(key) != 32:
            raise ValueError('DASHBOARD_MASTER_KEY must be base64 of exactly 32 random bytes')
        accounts = json.loads(required('GCP_SA_KEY'))
        if accounts.get('type') != 'service_account':
            raise ValueError('GCP_SA_KEY must be a service account JSON object')
        mapping = json.loads(required('CLASS_SHEET_MAP_JSON'))
        if not isinstance(mapping,dict) or not mapping or not all(isinstance(k,str) and isinstance(v,str) and v for k,v in mapping.items()):
            raise ValueError('CLASS_SHEET_MAP_JSON must map classroom names to actual spreadsheet IDs')
        settings = cls(required('GEMINI_API_KEY'), accounts, required('GUIDELINES_SPREADSHEET_ID'),
            required('FOLDER_STATE_ID'), required('FOLDER_INCOMING_SCAN_ID'),
            required('FOLDER_PROCESSED_SCAN_ID'), required('GEMINI_NOTEBOOK_MODEL'),
            required('GEMINI_ESSAY_MODEL'), key, required('DASHBOARD_BASE_URL').rstrip('/'),
            mapping, Path(os.getenv('DASHBOARD_OUTPUT_DIR', 'dashboard_data')),
            int(os.getenv('MAX_JOBS_PER_RUN', '12')), int(os.getenv('GEMINI_RPM', '6')))
        state_auth = os.getenv('GOOGLE_STATE_OAUTH_JSON', '').strip()
        if state_auth:
            state_auth = json.loads(state_auth)
            if state_auth.get('type') != 'authorized_user' or not all(state_auth.get(k) for k in ('client_id','client_secret','refresh_token')):
                raise ValueError('GOOGLE_STATE_OAUTH_JSON must contain an authorized-user refresh credential')
            from dataclasses import replace
            settings = replace(settings, state_oauth=state_auth)
        if settings.incoming_folder == settings.processed_folder or settings.state_folder in (
                settings.incoming_folder, settings.processed_folder):
            raise ValueError('Incoming, processed and state folders must be different')
        if not settings.dashboard_base_url.startswith('https://') or settings.max_jobs < 1 or settings.requests_per_minute < 1:
            raise ValueError('Invalid dashboard URL or execution limits')
        return settings
