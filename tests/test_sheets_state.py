import copy
import hashlib
import json
from types import SimpleNamespace
import pytest
from src.sheets_state import SheetsStateDrive, HEADERS, TITLE, MARKER, encode


class Request:
    def __init__(self, call): self.call = call
    def execute(self): return self.call()


class Api:
    def __init__(self, rows): self.rows, self.writes, self.lost = rows, 0, False
    def get(self, **kw):
        if 'range' in kw:
            return Request(lambda: {'values': copy.deepcopy(self.rows)})
        return Request(lambda: {'sheets': [{'properties': {'sheetId': 7, 'title': TITLE,
                         'gridProperties': {'rowCount': 1000}}}]})
    def values(self): return self
    def batchUpdate(self, **kw):
        def write():
            self.writes += 1
            for item in kw['body']['requests']:
                if 'appendDimension' in item: continue
                update = item['updateCells']; i = update['range']['startRowIndex']
                while len(self.rows) <= i: self.rows.append([])
                self.rows[i] = [x['userEnteredValue']['stringValue'] for x in update.get('rows', [{}])[0].get('values', [])]
            if self.lost: raise TimeoutError('response lost after commit')
            return {}
        return Request(write)


def row(name, value, legacy=''):
    raw = encode(value)
    return [name, '0', '1', hashlib.sha256(raw.encode()).hexdigest(), raw, 'private-folder', legacy]


def store(rows=None):
    api = Api(rows or [HEADERS, row(MARKER, {'files': 1}), row('job-old.json', {'phase': 'returned'}, 'old-drive-id')])
    sheets = SimpleNamespace(api=SimpleNamespace(spreadsheets=lambda: api))
    drive = SimpleNamespace(assert_private_folder=lambda folder: None)
    return SheetsStateDrive(sheets, drive, 'private-book', 'private-folder'), api


def test_preserves_legacy_raw_results_and_aliases():
    s, api = store()
    assert json.loads(s.download('old-drive-id')[0]) == {'phase': 'returned'}
    assert s.folder_files('private-folder')[0]['name'] == 'job-old.json'
    assert api.writes == 0


def test_chunked_update_and_shrink():
    s, api = store(); value = {'comment': 'Đúng nguyên văn. ' * 6000}
    identifier = s.write_json('private-folder', 'job-new.json', value)
    assert json.loads(s.download(identifier)[0]) == value
    s.write_json('private-folder', 'job-new.json', {'short': True})
    assert len(s.positions['job-new.json']) == 1
    assert json.loads(s.download('old-drive-id')[0]) == {'phase': 'returned'}


def test_uncertain_committed_write_reconciles_without_replay():
    s, api = store(); api.lost = True
    s.write_json('private-folder', 'attempt-test.json', {'saved': True})
    assert api.writes == 1


def test_missing_migration_manifest_and_corruption_fail_closed():
    with pytest.raises(ValueError, match='imported'):
        store([HEADERS, row('job-old.json', {'saved': True})])
    rows = [HEADERS, row(MARKER, {}), row('job-old.json', {})]; rows[-1][4] = 'tampered'
    with pytest.raises(ValueError, match='checksum'): store(rows)


def test_concurrent_writer_stops_before_write():
    s, api = store(); api.rows.append(row('other.json', {}))
    with pytest.raises(ValueError, match='another writer'):
        s.write_json('private-folder', 'job-new.json', {})
    assert api.writes == 0
