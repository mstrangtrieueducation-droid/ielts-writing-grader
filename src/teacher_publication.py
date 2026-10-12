"""Publish exact saved output on a separate, explicit teacher instruction.

Quality findings and raw model output remain unchanged. This path never grades,
retries, clears a notebook lock, or treats publication as quality acceptance.
"""
import hashlib
import os
from .schemas import Binding, EssayResult, AuditedProEssayBundle, AuditedBundledEssayFeedback, NotebookResult
from .parsers import word_count, essay_paragraphs, parse_receipt
from .policy import eligible_binding, receipt_allowed, notebook_state, check_suppression
from .pilot import payload_digest
from .graders.essay_grader import source_quote
from .delivery import feedback_block


def saved_raw(state):
    if bool(state.get('bundle_work')) == bool(state.get('batch_essay_work')):
        raise ValueError('Exactly one saved grading transport is required')
    return (state.get('batch_essay_work') or state['bundle_work'])['result']


def saved_essays(state):
    """Restore display-only schema; do not change grading prose or private QA."""
    binding=Binding.model_validate(state['binding'])
    raw=saved_raw(state)
    if state.get('batch_essay_work'):
        from .graders.essay_batch import _frozen_requests
        _frozen_requests(state['batch_essay_work'],binding.essays,state['source']['essay_texts'])
        if not isinstance(raw,dict) or set(raw)!={str(s.exercise) for s in binding.essays}:
            raise ValueError('Saved Batch exercise mapping differs')
        items=[AuditedBundledEssayFeedback.model_validate(raw[str(s.exercise)]) for s in binding.essays]
        if any(item.exercise!=spec.exercise for item,spec in zip(items,binding.essays)):
            raise ValueError('Saved Batch response mapping differs')
    else:
        items=AuditedProEssayBundle.model_validate(raw).essays
    if sorted(e.exercise for e in items)!=sorted(s.exercise for s in binding.essays):
        raise ValueError('Saved bundle does not contain the exact assigned exercises')
    output=[]
    from .parsers import digest
    for item in items:
        original=state['source']['essay_texts'][str(item.exercise)]
        if item.source_digest!=digest(original):
            raise ValueError('Saved essay source identity differs')
        data=item.model_dump(include=set(EssayResult.model_fields))
        for c in data['corrections']:
            c.pop('category',None)
            c['original']=source_quote(c['original'],original)
        data.update(original=original,word_count=word_count(original),
            paragraph_count=len(essay_paragraphs(original)),band_scores={})
        output.append(EssayResult.model_validate(data).model_dump(mode='json'))
    return output


def verify_authorization(state):
    approval=state.get('teacher_publication_authorization',{})
    publication=state.get('teacher_publication',{})
    if (approval.get('kind')!='explicit_existing_output' or not approval.get('authority')
        or not approval.get('authorized_at') or not approval.get('quality_findings_acknowledged')
        or approval.get('job_id')!=state['job_id']
        or approval.get('student_id')!=state['student']['id']
        or approval.get('raw_sha256')!=payload_digest(saved_raw(state))
        or approval.get('binding_sha256')!=payload_digest(state['binding'])
        or approval.get('source_sha256')!=payload_digest(state['source'])
        or approval.get('payload_sha256')!=payload_digest(publication.get('payload'))):
        raise ValueError('Exact teacher authorization for saved output is absent or changed')
    payload=publication['payload'];binding=Binding.model_validate(state['binding'])
    if (payload.get('essays')!=saved_essays(state) or payload.get('state')!='graded'
        or payload.get('student_id')!=state['student']['id']
        or payload.get('student_name')!=state['student']['name']
        or payload.get('class_name')!=binding.class_name or payload.get('task_code')!=binding.task_code
        or payload.get('received_at')!=state['source']['received_at']
        or payload.get('notebook_links')!=[f'https://drive.google.com/file/d/{fid}/view' for fid in state['source']['notebook_ids']]):
        raise ValueError('Teacher-directed publication differs from saved source/output')
    check_suppression(payload)
    return approval,payload


def deliver_teacher_authorized(pipeline,bindings,selection):
    if os.getenv('GEMINI_GENERATION_ENABLED')=='true':
        raise ValueError('Teacher-directed delivery requires paid generation OFF')
    if set(selection)!={'class_name','task_code','student_ids'} or len(selection['student_ids'])!=1:
        raise ValueError('Teacher-directed delivery requires one exact student selection')
    matches=[b for b in bindings if b.class_name==selection['class_name'] and b.task_code==selection['task_code']]
    if len(matches)!=1:raise ValueError('Current binding absent or ambiguous')
    current=matches[0];spreadsheet=pipeline.settings.class_sheets[current.class_name]
    roster=pipeline.sheets.roster(spreadsheet,current);sources=pipeline.sources(current,roster)
    if pipeline.discovery_errors:raise ValueError('Unresolved Form identity prevents delivery')
    found=[(s,source) for s,source in sources if s['id']==selection['student_ids'][0]]
    if len(found)!=1:raise ValueError('Current source absent or ambiguous')
    student,source=found[0];state=pipeline.store.jobs.get(pipeline.store.identity(current,student))
    if not state:raise ValueError('Saved job absent')
    frozen=Binding.model_validate(state['binding'])
    # A closed paid trial may have ready=false; this authorizes saved publication only.
    if (current.model_copy(update={'ready':frozen.ready})!=frozen or not eligible_binding(frozen)
        or source!=state['source'] or student!=state['student']
        or not receipt_allowed(frozen,parse_receipt(source['received_at']))):
        raise ValueError('Frozen binding, student or eligible receipt changed')
    if pipeline.store.locked_notebook(frozen,student) or notebook_state(NotebookResult.model_validate(state['notebook']))!='pass':
        raise ValueError('Teacher publication cannot bypass notebook eligibility')
    approval,payload=verify_authorization(state)
    actual={fid:hashlib.sha256(data).hexdigest() for fid,data,_ in pipeline.files(frozen.source_file_ids+source['notebook_ids'])}
    if actual!=approval.get('file_checksums'):raise ValueError('Teacher publication source files changed')
    publication=state['teacher_publication']
    publication['dashboard_evidence']=pipeline.dashboard.publish(payload)
    pipeline.store.save(state)
    publication['tracker_evidence']=pipeline.sheets.write_feedback(spreadsheet,frozen,student,feedback_block(payload,pipeline.dashboard.link(frozen.class_name,student['id'])))
    pipeline.store.save(state)
    publication['parent_dashboard_evidence']=pipeline.dashboard.verify_parent_ui(payload,pipeline.sheets.parent_link(spreadsheet,frozen,student))
    publication['status']='published'
    pipeline.store.save(state)
    return {'delivered':1,'essays':len(payload['essays']),'tracker_verified':bool(publication['tracker_evidence'].get('exact_readback')),
        'model_generation_calls':0,'quality_status_changed':False}
