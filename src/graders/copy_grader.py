import json
from ..schemas import NotebookResult
from ..media import validate_page_audit, validate_references
from ..media import page_count
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
    if 'flash' not in settings.notebook_model.lower():
        raise ValueError('Notebook image checks require a Flash model; Pro is prohibited')
    prompt = 'Inspect every student page against ONLY this assigned checklist. Reconstruct out-of-order and interleaved pages. '
    prompt += 'Give each item an evidence-based finding; page_audit covers student files only. '
    prompt += 'Missing findings require a search of all pages, not an inference from page order.\n'
    if not reference_files:
        raise ValueError('Full teacher notebook/reference files required; checklist alone is insufficient')
    reference_counts={fid:page_count(data,mime) for fid,data,mime in reference_files}
    prompt += 'Read ALL pages of the supplied TEACHER REFERENCE FILES, including worked corrections, '
    prompt += 'English models, Vietnamese translations, explanations, outlines, charts and notes within the assigned copying boundary. '
    prompt += 'The checklist locates content; it is NOT a substitute for the actual teacher material. '
    prompt += 'Compare each assigned major section with the actual student pages. Do not accept headings alone. '
    prompt += 'Keep teacher reference pages separate from student evidence; an unreadable teacher source is uncertain, not missing student work.\n'
    requirements=binding.notebook_requirements+binding.outline_requirements
    if binding.outline_requirements:
        prompt += 'Also inspect the assigned student outlines in these same pages: verify each required argument, explanation/example and order against its explicit checklist, not merely a heading. Do not invent a student-outline requirement from the teacher essay outline. Unreadable evidence stays uncertain.\n'
    prompt += 'TRUSTED COPYING BOUNDARY: '+binding.notebook_copy_scope+'\n'
    prompt += 'Homework questions, new homework charts/tables, blank answer sheets and tool/submission instructions are not notebook copying requirements. Do not reject a notebook for their absence.\n'
    prompt += json.dumps({'version': binding.version, 'requirements':[r.model_dump() for r in requirements],
        'student_files':counts, 'reference_files':[x[0] for x in reference_files],
        'teacher_reference_pages':reference_counts}, ensure_ascii=False)
    result = validate_check(ai.structured(settings.notebook_model, prompt, NotebookResult,
        reference_files+student_files), requirements, counts)
    # A second independent full-page inspection guards against false missing/printed verdicts.
    if notebook_state(result) == 'fail':
        audit_prompt = prompt + '\nPerform an independent search for every assigned item, without relying on another reviewer.'
        second = validate_check(ai.structured(settings.notebook_model, audit_prompt, NotebookResult,
            reference_files+student_files), requirements, counts)
        original = {x.id:x.status for x in result.items}
        if original != {x.id:x.status for x in second.items}:
            raise ValueError('Independent notebook audits disagree; teacher/source verification required')
        return second
    return result
