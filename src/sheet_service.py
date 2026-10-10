import json
from googleapiclient.discovery import build
from .parsers import col_number, normalize_name, sheet_range
from .schemas import Binding
from .retry import retry

START = '【KẾT QUẢ CHẤM '
END = '【HẾT KẾT QUẢ CHẤM】'

def replace_comment(existing, block):
    # Preserve teacher text and receipt prefixes verbatim; reject malformed duplicate markers.
    starts = [i for i in range(len(existing)) if existing.startswith(START, i)]
    if len(starts) > 1 or existing.count(END) > 1:
        raise ValueError('Ambiguous existing grading blocks')
    if starts:
        stop = existing.find(END, starts[0])
        if stop < 0:
            raise ValueError('Unclosed grading block')
        return existing[:starts[0]] + block + existing[stop+len(END):]
    if END in existing:
        raise ValueError('Orphan grading end marker')
    return existing.rstrip() + ('\n\n— NHẬN XÉT GV —\n\n' if '— NHẬN XÉT GV —' not in existing else '\n\n') + block

class SheetService:
    def __init__(self, creds):
        self.api = build('sheets', 'v4', credentials=creds, cache_discovery=False)

    def values(self, spreadsheet, range_, formula=False):
        return retry(lambda: self.api.spreadsheets().values().get(spreadsheetId=spreadsheet,
            range=range_, valueRenderOption='FORMULA' if formula else 'FORMATTED_VALUE').execute()).get('values', [])

    def set_cell(self, spreadsheet, range_, value):
        retry(lambda: self.api.spreadsheets().values().update(spreadsheetId=spreadsheet,
            range=range_, valueInputOption='RAW', body={'values': [[value]]}).execute())
        if self.values(spreadsheet, range_) != [[value]]:
            raise RuntimeError('Tracker exact readback failed')

    def guidelines(self, spreadsheet):
        rows = self.values(spreadsheet, "'IELTS_WRITING_GUIDELINES'!A:C")
        if not rows or rows[0] != ['task_code', 'assignment_type', 'config_json']:
            raise ValueError('Guidelines header must be task_code, assignment_type, config_json')
        bindings, seen = [], set()
        for row in rows[1:]:
            if not any(row):
                continue
            if len(row) != 3:
                raise ValueError('Incomplete guidelines row')
            binding = Binding.model_validate({**json.loads(row[2]), 'task_code': row[0], 'assignment_type': row[1]})
            identity = (binding.class_name, binding.task_code)
            if identity in seen:
                raise ValueError('Duplicate class/task source binding')
            seen.add(identity)
            bindings.append(binding)
        return bindings

    def roster(self, spreadsheet, binding):
        names = self.values(spreadsheet, sheet_range(binding.tracker_tab,
            f'{binding.roster_name_column}{binding.roster_start_row}:{binding.roster_name_column}{binding.roster_end_row}'))
        identifiers = self.values(spreadsheet, sheet_range(binding.tracker_tab,
            f'{binding.roster_id_column}{binding.roster_start_row}:{binding.roster_id_column}{binding.roster_end_row}'))
        roster, seen = [], set()
        for offset, row in enumerate(names):
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            if normalize_name(name) in seen:
                raise ValueError('Duplicate roster names require distinct identity configuration')
            seen.add(normalize_name(name))
            sid = identifiers[offset][0] if offset < len(identifiers) and identifiers[offset] else ''
            if not sid:
                raise ValueError('Every real roster student requires a stable student ID')
            roster.append({'name':name, 'id':sid, 'row':binding.roster_start_row+offset})
        if len({r['id'] for r in roster}) != len(roster):
            raise ValueError('Duplicate stable roster IDs')
        return roster

    def feedback_column(self, spreadsheet, binding):
        rows = self.values(spreadsheet, sheet_range(binding.tracker_tab, binding.tracker_header_range))
        positions = {col for row in rows for col, value in enumerate(row) if value.strip() == binding.tracker_header_exact}
        if len(positions) != 1:
            raise ValueError('Exact assignment header not uniquely found')
        number = positions.pop()+1
        letters = ''
        while number:
            number, rem = divmod(number-1, 26)
            letters = chr(65+rem)+letters
        return letters

    def write_feedback(self, spreadsheet, binding, student, block):
        column = self.feedback_column(spreadsheet, binding)
        cell = sheet_range(binding.tracker_tab, f"{column}{student['row']}")
        before = self.values(spreadsheet, cell, formula=True)
        existing = before[0][0] if before and before[0] else ''
        if existing.startswith('='):
            raise ValueError('Feedback target contains a formula; no overwrite allowed')
        updated = replace_comment(existing, block)
        if updated != existing:
            # Check for a human edit immediately before mutation.
            if self.values(spreadsheet, cell, formula=True) != before:
                raise RuntimeError('Tracker changed during writeback; retry from fresh source')
            self.set_cell(spreadsheet, cell, updated)
        elif self.values(spreadsheet, cell) != [[updated]]:
            raise RuntimeError('Tracker readback failed')
        return {'cell':cell, 'exact_readback':True}

    def has_prior_grading(self, spreadsheet, binding, student):
        column=self.feedback_column(spreadsheet,binding)
        values=self.values(spreadsheet,sheet_range(binding.tracker_tab,f"{column}{student['row']}"))
        return bool(values and values[0] and START in values[0][0])
