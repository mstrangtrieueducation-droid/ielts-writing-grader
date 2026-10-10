import pymupdf as fitz

def page_count(data, mime):
    with fitz.open(stream=data, filetype='pdf' if mime == 'application/pdf' else None) as doc:
        count = len(doc)
    if count < 1 or count > 100:
        raise ValueError('Source must contain between 1 and 100 pages')
    return count

def validate_page_audit(audit, counts):
    expected = {(fid, page) for fid, count in counts.items() for page in range(1, count+1)}
    actual = [(p.file_id, p.page) for p in audit]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('Page audit must cover every submitted page exactly once')
    if not all(p.readable for p in audit):
        raise ValueError('Unreadable source pages: awaiting verification, not missing')

def validate_references(references, counts):
    if any(p.file_id not in counts or not 1 <= p.page <= counts[p.file_id] for p in references):
        raise ValueError('Evidence refers to an unknown file or nonexistent page')
