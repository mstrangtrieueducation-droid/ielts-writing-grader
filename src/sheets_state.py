"""Private JSON checkpoints in Sheets, authenticated only by the service account.

Compatible with StateStore/CostLedger's small Drive-shaped interface. Historical
Drive IDs are retained as aliases, so saved results and budgets are never reset.
The existing workflow concurrency group remains the single-writer authority.
"""
import hashlib
import json
import urllib.parse

TITLE = '_IELTS_PYTHON_STATE_V1'
HEADERS = ['name', 'part', 'parts', 'sha256', 'json', 'namespace', 'legacy_id']
MARKER = '__migration_complete__.json'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class SheetsStateDrive:
    def __init__(self, sheets, drive, spreadsheet, namespace, require_import=True):
        if not spreadsheet or not namespace:
            raise ValueError('Private Sheets checkpoint binding required')
        self.sheets, self.drive, self.spreadsheet, self.namespace = sheets, drive, spreadsheet, namespace
        self.api = sheets.api.spreadsheets()
        metadata = self.api.get(spreadsheetId=spreadsheet, fields='sheets(properties)').execute()
        found = [s['properties'] for s in metadata['sheets'] if s['properties']['title'] == TITLE]
        if len(found) != 1:
            raise ValueError('Checkpoint table must be provisioned and migrated before cutover')
        self.sheet_id = found[0]['sheetId']
        self.row_count = found[0]['gridProperties']['rowCount']
        self.reload()
        if require_import and MARKER not in self.records:
            raise ValueError('Historical checkpoints must be imported before grading')

    def reload(self):
        self.rows = self.api.values().get(spreadsheetId=self.spreadsheet, range=f"'{TITLE}'!A:G",
                                          valueRenderOption='UNFORMATTED_VALUE').execute().get('values', [])
        if not self.rows or self.rows[0] != HEADERS:
            raise ValueError('Checkpoint schema mismatch')
        self.records, self.positions, self.aliases = {}, {}, {}
        grouped = {}
        for index, row in enumerate(self.rows[1:], 1):
            if not row or not any(row):
                continue
            row = row + [''] * (7-len(row))
            if row[5] != self.namespace:
                raise ValueError('Checkpoint namespace mismatch')
            grouped.setdefault(row[0], []).append((index, row))
        for name, parts in grouped.items():
            ordered = sorted(parts, key=lambda item: int(item[1][1]))
            count = int(ordered[0][1][2])
            if len(parts) != count or [int(x[1][1]) for x in ordered] != list(range(count)):
                raise ValueError('Incomplete checkpoint chunks')
            raw = ''.join(x[1][4] for x in ordered)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            if any(x[1][3] != digest or int(x[1][2]) != count for x in ordered):
                raise ValueError('Checkpoint checksum mismatch')
            self.records[name] = json.loads(raw)
            self.positions[name] = [x[0] for x in ordered]
            aliases = {x[1][6] for x in ordered if x[1][6]}
            if len(aliases) > 1:
                raise ValueError('Ambiguous legacy checkpoint alias')
            for alias in aliases:
                if alias in self.aliases:
                    raise ValueError('Duplicate legacy checkpoint alias')
                self.aliases[alias] = name

    def folder_files(self, folder):
        self.check_folder(folder)
        return [{'id': 'sheetstate:' + urllib.parse.quote(name, safe=''), 'name': name,
                 'mimeType': 'application/json'} for name in self.records if name != MARKER]

    def check_folder(self, folder):
        if folder != self.namespace:
            raise ValueError('Checkpoint namespace changed')

    def download(self, identifier, limit=40_000_000):
        name = urllib.parse.unquote(identifier[len('sheetstate:'):]) if identifier.startswith('sheetstate:') else self.aliases.get(identifier)
        if name not in self.records:
            raise ValueError('Unknown checkpoint; never fall back to restricted user OAuth')
        raw = encode(self.records[name]).encode()
        if len(raw) > limit:
            raise ValueError('Checkpoint exceeds requested limit')
        return raw, 'application/json'

    def assert_private_folder(self, folder):
        self.check_folder(folder)
        self.drive.assert_private_folder(self.spreadsheet)

    def write_json(self, folder, name, data):
        self.check_folder(folder)
        if name == MARKER:
            raise ValueError('Migration manifest is immutable')
        before = self.rows
        self.reload()
        if self.rows != before:
            raise ValueError('Checkpoint changed under another writer; stop without replay')
        raw = encode(data)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        chunks = [raw[i:i+20000] for i in range(0, len(raw), 20000)]
        old = self.positions.get(name, [])
        positions = old[:len(chunks)] + list(range(len(self.rows), len(self.rows) + max(0, len(chunks)-len(old))))
        alias = next((key for key, value in self.aliases.items() if value == name), '')
        updates = []
        required_rows = max(positions, default=0) + 1
        if required_rows > self.row_count:
            updates.append({'appendDimension': {'sheetId': self.sheet_id, 'dimension': 'ROWS',
                            'length': required_rows - self.row_count}})
        for part, (row, text) in enumerate(zip(positions, chunks)):
            values = [name, str(part), str(len(chunks)), digest, text, self.namespace, alias]
            updates.append({'updateCells': {'range': {'sheetId': self.sheet_id, 'startRowIndex': row,
                'endRowIndex': row+1, 'startColumnIndex': 0, 'endColumnIndex': 7},
                'rows': [{'values': [{'userEnteredValue': {'stringValue': v}} for v in values]}], 'fields': 'userEnteredValue'}})
        for row in old[len(chunks):]:
            updates.append({'updateCells': {'range': {'sheetId': self.sheet_id, 'startRowIndex': row,
                'endRowIndex': row+1, 'startColumnIndex': 0, 'endColumnIndex': 7}, 'fields': 'userEnteredValue'}})
        # One atomic batch; no automatic replay on an unknown HTTP outcome.
        error = None
        try:
            self.api.batchUpdate(spreadsheetId=self.spreadsheet, body={'requests': updates}).execute()
        except Exception as exc:
            error = exc
        self.reload()
        self.row_count = max(self.row_count, required_rows)
        if self.records.get(name) != data:
            raise RuntimeError('Checkpoint exact readback failed; no replay') from error
        return 'sheetstate:' + urllib.parse.quote(name, safe='')
