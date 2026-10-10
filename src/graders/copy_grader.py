import json
from ..schemas import NotebookResult
from ..media import validate_page_audit, validate_references
from ..policy import notebook_state

def validate_check(result, requirements, counts):
    ids = [r.id for r in requirements]
    found = [r.id for r in result.items]
    if len(found) != len(set(found)) or set(found) != set(ids):
        raise ValueError('Every assigned checklist item requires exactly one finding')
    validate_page_audit(result.page_audit, counts)
    for item in result.items:
        validate_references(item.pages, counts)
        if item.status == 'complete' and not item.pages:
            raise ValueError('Complete item requires concrete page evidence')
    return result

def grade_notebook(ai, settings, binding, student_files, reference_files, counts):
    prompt = 'Inspect every student page against ONLY this assigned checklist. Reconstruct out-of-order and interleaved pages. '
    prompt += 'Give each item an evidence-based finding; page_audit covers student files only. '
    prompt += 'Missing findings require a search of all pages, not an inference from page order.\n'
    prompt += json.dumps({'version': binding.version, 'requirements':[r.model_dump() for r in binding.notebook_requirements],
        'student_files':counts, 'reference_files':[x[0] for x in reference_files]}, ensure_ascii=False)
    result = validate_check(ai.structured(settings.notebook_model, prompt, NotebookResult,
        reference_files+student_files), binding.notebook_requirements, counts)
    # A second independent full-page inspection guards against false missing/printed verdicts.
    if notebook_state(result) == 'fail':
        audit_prompt = prompt + '\nPerform an independent search for every assigned item, without relying on another reviewer.'
        second = validate_check(ai.structured(settings.essay_model, audit_prompt, NotebookResult,
            reference_files+student_files), binding.notebook_requirements, counts)
        original = {x.id:x.status for x in result.items}
        if original != {x.id:x.status for x in second.items}:
            raise ValueError('Independent notebook audits disagree; teacher/source verification required')
        return second
    return result
