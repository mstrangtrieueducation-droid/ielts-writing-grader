from src.drive_service import state_credentials

def test_owner_state_credential_requests_only_app_created_drive_files():
    creds=state_credentials({'client_id':'client','client_secret':'secret','refresh_token':'refresh',
        'type':'authorized_user','token_uri':'https://oauth2.googleapis.com/token'})
    assert list(creds.scopes)==['https://www.googleapis.com/auth/drive.file']
    assert not creds.has_scopes(['https://www.googleapis.com/auth/cloud-platform'])
