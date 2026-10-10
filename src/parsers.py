import hashlib
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

VIETNAM = ZoneInfo('Asia/Ho_Chi_Minh')
FILE_PATTERN = re.compile(r'^(IELTS\s*\d{1,3})_([^/\\]+)_([A-Za-z0-9][A-Za-z0-9.-]*)\.pdf$', re.I)
DRIVE_ID = re.compile(r'^[A-Za-z0-9_-]{10,200}$')

def normalize_name(value):
    # Accent/case/space variants only; no fuzzy surname guessing.
    value = unicodedata.normalize('NFD', str(value).casefold().replace('đ', 'd'))
    return ' '.join(''.join(c for c in value if unicodedata.category(c) != 'Mn').split())

def parse_filename(filename):
    match = FILE_PATTERN.fullmatch(filename)
    if not match:
        raise ValueError('Scan filename must be IELTSnn_Full Student Name_TaskCode.pdf')
    classroom, student, code = match.groups()
    class_number=int(re.search(r'\d+',classroom).group())
    return f'IELTS {class_number}', student.replace('_', ' '), code.upper()

def match_student(name, roster, aliases):
    resolved = aliases.get(name, name)
    matches = [r for r in roster if normalize_name(r['name']) == normalize_name(resolved)]
    if len(matches) != 1:
        raise ValueError('Student identity is absent or ambiguous; explicit alias required')
    return matches[0]

def parse_receipt(value):
    if not value:
        raise ValueError('Original Form receipt time is required')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        result = None
        for pattern in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%m/%d/%Y %H:%M:%S'):
            try:
                result = datetime.strptime(value, pattern)
                break
            except ValueError:
                continue
        if result is None:
            raise ValueError('Unrecognized receipt timestamp')
    return (result.replace(tzinfo=VIETNAM) if result.tzinfo is None else result).astimezone(VIETNAM)

def drive_ids(value):
    ids = []
    for part in re.split(r'[,\n;]', value or ''):
        part = part.strip()
        if not part:
            continue
        match = re.search(r'(?:/d/|[?&]id=)([A-Za-z0-9_-]+)', part)
        token = match.group(1) if match else part
        if not DRIVE_ID.fullmatch(token):
            raise ValueError('Invalid Drive reference')
        if token not in ids:
            ids.append(token)
    return ids

def word_count(text):
    return len(re.findall(r"[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*", text))

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def sheet_range(tab, cell):
    return "'" + tab.replace("'", "''") + "'!" + cell

def col_number(col):
    if not re.fullmatch('[A-Z]{1,3}', col):
        raise ValueError('Invalid A1 column')
    number = 0
    for c in col:
        number = number * 26 + ord(c) - 64
    return number - 1
