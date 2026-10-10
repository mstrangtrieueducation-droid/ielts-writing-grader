from datetime import datetime, time, date
from .parsers import VIETNAM

TOO_LATE = 'NỘP QUÁ MUỘN — KHÔNG ĐƯỢC CHẤM CHỮA CHI TIẾT'

def eligible_binding(binding):
    if not binding.ready or not binding.source_verified or binding.archive_before_20260930:
        return False
    if binding.assignment_type != 'assessment' and binding.lesson in (21, 39):
        return False
    if binding.lesson <= 5 and binding.assignment_type != 'assessment' and not binding.early_lesson_authorized:
        return False
    return True

def cutoff(binding):
    if binding.assignment_type == 'assessment':
        return None
    return datetime.combine(binding.next_writing_date, time.min, tzinfo=VIETNAM)

def receipt_allowed(binding, received):
    boundary = cutoff(binding)
    if boundary is None:
        return True
    if boundary.date() < date(2026, 9, 30):
        return False  # archived old weeks stay closed
    return received < boundary  # wall clock after midnight does not block grading backlog

def notebook_state(result):
    statuses = {item.status for item in result.items}
    if 'uncertain' in statuses:
        return 'pending'
    return 'pass' if statuses == {'complete'} else 'fail'

def gated_payload(payload):
    if payload['state'] in ('too_late', 'notebook_failed', 'pending', 'missing'):
        payload = {**payload, 'essays': []}
    return payload

def check_suppression(payload):
    if payload['state'] != 'graded' and payload.get('essays'):
        raise ValueError('Gated result exposes essay details')
