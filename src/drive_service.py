import io
import json
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from .retry import retry

SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

def credentials(account):
    return service_account.Credentials.from_service_account_info(account, scopes=SCOPES)

def state_credentials(account):
    # Use the owner's existing drive.file grant for app-created private state in My Drive.
    # Source Drive reads and Sheets edits still use the separately authorized service account.
    return Credentials.from_authorized_user_info(account, scopes=['https://www.googleapis.com/auth/drive.file'])

class DriveService:
    def __init__(self, creds):
        self.api = build('drive', 'v3', credentials=creds, cache_discovery=False)

    def listing(self, query):
        files, page = [], None
        while True:
            result = retry(lambda: self.api.files().list(q=query, pageToken=page,
                fields='nextPageToken,files(id,name,mimeType,size,parents,createdTime)',
                pageSize=100, supportsAllDrives=True, includeItemsFromAllDrives=True).execute())
            files.extend(result.get('files', []))
            page = result.get('nextPageToken')
            if not page:
                return files

    def folder_files(self, folder):
        return self.listing(f"'{folder}' in parents and trashed=false")

    def metadata(self, file_id):
        return retry(lambda: self.api.files().get(fileId=file_id, supportsAllDrives=True,
            fields='id,name,mimeType,size,parents,createdTime').execute())

    def assert_private_folder(self, folder):
        page=None
        while True:
            result=retry(lambda:self.api.permissions().list(fileId=folder,pageToken=page,
                supportsAllDrives=True,fields='nextPageToken,permissions(type)').execute())
            if any(p.get('type')=='anyone' for p in result.get('permissions',[])):
                raise ValueError('State folder must not be publicly shared')
            page=result.get('nextPageToken')
            if not page: return

    def download(self, file_id, limit=40_000_000):
        metadata = self.metadata(file_id)
        if int(metadata.get('size', 0)) > limit:
            raise ValueError('Source exceeds configured maximum size; split or compress first')
        mime = metadata['mimeType']
        if mime == 'application/vnd.google-apps.document':
            request = self.api.files().export_media(fileId=file_id, mimeType='application/pdf')
            mime = 'application/pdf'
        elif mime == 'application/pdf' or mime.startswith('image/') or mime == 'application/json':
            request = self.api.files().get_media(fileId=file_id, supportsAllDrives=True)
        else:
            raise ValueError('Only PDF, images, native Docs and JSON supported; video is not downloaded')
        stream = io.BytesIO()
        downloader = MediaIoBaseDownload(stream, request, chunksize=1024*1024)
        done = False
        while not done:
            _, done = retry(downloader.next_chunk)
            if stream.tell() > limit:
                raise ValueError('Source exceeds maximum size')
        return stream.getvalue(), mime

    def write_json(self, folder, name, data):
        safe_name = name.replace("'", "\\'")
        matches = self.listing(f"'{folder}' in parents and name='{safe_name}' and trashed=false")
        if len(matches) > 1:
            raise ValueError('Duplicate state document; reconcile before continuing')
        content = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype='application/json', resumable=False)
        if matches:
            result = retry(lambda: self.api.files().update(fileId=matches[0]['id'], media_body=media,
                supportsAllDrives=True, fields='id').execute())
        else:
            # Create is reconciled by name if a response is lost; do not blindly retry a non-idempotent create.
            try:
                result = self.api.files().create(body={'name': name, 'parents': [folder]},
                    media_body=media, supportsAllDrives=True, fields='id').execute()
            except Exception:
                found = self.listing(f"'{folder}' in parents and name='{safe_name}' and trashed=false")
                if len(found) != 1:
                    raise
                result = found[0]
        actual, _ = self.download(result['id'])
        if json.loads(actual) != data:
            raise RuntimeError('Drive state exact readback failed')
        return result['id']

    def move_processed(self, file_id, incoming, processed):
        parents = self.metadata(file_id).get('parents', [])
        if processed in parents and incoming not in parents:
            return
        if incoming not in parents:
            raise ValueError('Scan is no longer in the configured incoming folder')
        retry(lambda: self.api.files().update(fileId=file_id, addParents=processed,
            removeParents=incoming, supportsAllDrives=True, fields='id,parents').execute())
        parents = self.metadata(file_id).get('parents', [])
        if processed not in parents or incoming in parents:
            raise RuntimeError('Processed-folder move readback failed')
