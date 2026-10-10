import json
from ..schemas import NotebookResult
from .copy_grader import validate_check

def grade_vocabulary(ai, settings, binding, student_files, reference_files, counts):
    prompt = '''Check ONLY the assigned vocabulary and fields explicitly required for each word.
    Identify English spelling, IPA, Vietnamese meaning, collocations/examples when assigned.
    Return one item per required word ID; report missing words/fields precisely, with readable
    page evidence. All required student writing must be handwritten. page_audit covers all
    student files only, regardless of page order. Do not require unassigned example sentences.
    ''' + json.dumps({'words':[x.model_dump() for x in binding.vocabulary], 'student_files':counts,
        'reference_files':[x[0] for x in reference_files]}, ensure_ascii=False)
    result = validate_check(ai.structured(settings.notebook_model, prompt, NotebookResult,
        reference_files+student_files), binding.vocabulary, counts)
    if any(x.status not in ('complete', 'uncertain') for x in result.items):
        second = validate_check(ai.structured(settings.essay_model, prompt+' Independently recheck all pages.',
            NotebookResult, reference_files+student_files), binding.vocabulary, counts)
        if {x.id:x.status for x in result.items} != {x.id:x.status for x in second.items}:
            raise ValueError('Independent vocabulary audits disagree')
        return second
    return result
