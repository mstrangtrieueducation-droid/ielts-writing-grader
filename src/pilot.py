"""A real, explicitly selected grading attempt, staged privately before delivery."""
import json
from .parsers import digest
from .schemas import Binding
from .delivery import deliver
from .policy import eligible_binding,receipt_allowed
from .parsers import parse_receipt
from .pro_batch import BatchPending

def selected_binding(bindings, selection):
    if set(selection) != {'class_name','task_code','student_ids'}:
        raise ValueError('Pilot selection requires an exact class, task and student IDs')
    ids=selection['student_ids']
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)):
        raise ValueError('Pilot student IDs must be explicit and unique')
    if len(ids)!=1:
        raise ValueError('A paid pilot is bounded to exactly one student')
    found=[b for b in bindings if b.class_name==selection['class_name'] and b.task_code==selection['task_code']]
    if len(found)!=1 or not eligible_binding(found[0]):
        raise ValueError('Pilot binding is absent, ambiguous or not verified')
    return found[0]

def run_pilot(pipeline, bindings, selection):
    binding=selected_binding(bindings,selection)
    spreadsheet=pipeline.settings.class_sheets[binding.class_name]
    roster=pipeline.sheets.roster(spreadsheet,binding)
    wanted=set(selection['student_ids'])
    if not wanted.issubset({s['id'] for s in roster}):
        raise ValueError('Pilot selection does not match the verified roster')
    sources=pipeline.sources(binding,roster)
    if pipeline.discovery_errors:
        raise ValueError('Unresolved Form identity/receipt prevents pilot grading')
    selected={s['id']:(s,source) for s,source in sources if s['id'] in wanted}
    if set(selected)!=wanted:
        raise ValueError('Selected pilot student has no original submission')
    report={'staged':0,'pending':0,'essays':0,'notebook_failed':0,'live_feedback_writes':0,'job_ids':[]}
    for sid in selection['student_ids']:
        student,source=selected[sid]
        if source.get('missing') or not receipt_allowed(binding,parse_receipt(source['received_at'])):
            raise ValueError('Pilot requires an eligible original receipt')
        jid=pipeline.store.identity(binding,student)
        existing=pipeline.store.jobs.get(jid)
        if existing and existing['phase']=='complete':
            raise ValueError('Already delivered pilot is preserved')
        if existing and existing.get('pilot_review',{}).get('status') in ('rejected','invalidated'):
            raise ValueError('Rejected pilot is preserved; another attempt requires new explicit authorization')
        if not existing and not binding.regrade_authorizations.get(sid) and pipeline.sheets.has_prior_grading(spreadsheet,binding,student):
            raise ValueError('Previously returned feedback is preserved')
        state=pipeline.store.begin(binding,student,source)
        if state['source']!=source or Binding.model_validate(state['binding'])!=binding:
            raise ValueError('Frozen pilot source or binding changed; preserve saved attempt')
        if getattr(pipeline.settings,'essay_service_tier','standard')=='batch' and not state.get('notebook'):
            raise ValueError('Pro Batch pilot must reuse an already verified notebook')
        # A failed/incomplete pilot must also remain outside automatic delivery.
        state['pilot_review']={'status':'awaiting_review','delivery_authorized':False}
        pipeline.store.save(state)
        try:
            pipeline.grade(state,binding)
        except BatchPending:
            state.pop('last_error',None)
            pipeline.store.save(state)
            report['pending']+=1
            report['job_ids'].append(jid)
            continue
        except Exception as exc:
            state['last_error']={'type':type(exc).__name__,
                'reason':str(exc) if isinstance(exc,ValueError) else 'External grading operation failed; inspect the private API audit and resume saved phase'}
            pipeline.store.save(state)
            raise
        state['pilot_review']={'status':'awaiting_review','delivery_authorized':False}
        state.pop('last_error',None)
        pipeline.store.save(state)
        report['staged']+=1
        report['essays']+=len(state['payload']['essays'])
        report['notebook_failed']+=state['payload']['state']=='notebook_failed'
        report['job_ids'].append(jid)
    pipeline.store.drive.write_json(pipeline.store.folder,'pilot-'+binding.class_name.replace(' ','-')+'-'+binding.task_code+'.json',report)
    return report

def collect_batch_pilot(pipeline,bindings,selection):
    """Poll only an already submitted pilot, using frozen text and cached notebook.

    No Form/PDF capture, notebook model, new Batch create or automatic publication.
    Dedicated delivery subsequently revalidates all live source/receipt bindings.
    """
    import os
    from .graders.essay_bundle import grade_bundle
    from .schemas import NotebookResult
    from .policy import notebook_state
    if os.getenv('GEMINI_GENERATION_ENABLED')=='true' or os.getenv('PILOT_BATCH_SUBMIT_AUTHORIZED')=='true':
        raise ValueError('Batch collection requires paid generation OFF')
    if pipeline.settings.essay_service_tier!='batch':
        raise ValueError('Collection requires explicit Pro Batch transport')
    binding=selected_binding(bindings,selection)
    matches=[s for s in pipeline.store.jobs.values() if s['binding']==binding.model_dump(mode='json')
        and s['student']['id']==selection['student_ids'][0]]
    if len(matches)!=1:
        raise ValueError('No unique frozen Batch pilot for selected binding')
    state=matches[0]
    review=state.get('pilot_review',{})
    if review.get('status')!='awaiting_review' or state.get('payload') or state['phase']=='complete':
        raise ValueError('Collection cannot reopen completed/rejected pilots')
    work=state.get('bundle_work',{})
    if work.get('transport')!='batch' or work.get('status') not in ('queued','received','validated'):
        raise ValueError('Collection requires an existing saved Batch attempt')
    if pipeline.store.locked_notebook(binding,state['student']) or not state.get('notebook') or notebook_state(NotebookResult.model_validate(state['notebook']))!='pass':
        raise ValueError('Collection requires previously verified passed notebook')
    pipeline.ai.bind_budget(pipeline.store,binding,state)
    def checkpoint(saved):
        state['bundle_work']=saved;pipeline.store.save(state)
    try:
        results=grade_bundle(pipeline.ai,pipeline.settings,binding.essays,state['source']['essay_texts'],checkpoint,work)
    except BatchPending:
        return {'pending':1,'staged':0,'live_feedback_writes':0,'generation_calls':0}
    state['essay_results']={str(r.exercise):r.model_dump(mode='json') for r in results}
    day=parse_receipt(state['source']['received_at']).strftime('%d/%m/%Y')
    state['payload']=pipeline.payload(binding,state['student'],state['source'],'graded',
        f'Đã ghi nhận vở nộp ngày {day} — Đạt yêu cầu.',[r.model_dump(mode='json') for r in results])
    state.pop('last_error',None)
    pipeline.store.save(state)
    return {'pending':0,'staged':1,'essays':len(results),'live_feedback_writes':0,'generation_calls':0}

def payload_digest(payload):
    return digest(json.dumps(payload,ensure_ascii=False,sort_keys=True))

def deliver_pilot_notebook(pipeline,bindings,selection):
    """Return independently approved notebook work while essays remain held.

    This is a component publication, never a completed grading job. Immutable
    rejected essays and their quality gate remain untouched and undisclosed.
    """
    import os
    import hashlib
    from .schemas import NotebookResult
    from .policy import notebook_state,check_suppression
    from .delivery import feedback_block
    if os.getenv('GEMINI_GENERATION_ENABLED')=='true':
        raise ValueError('Notebook publication requires generation OFF')
    binding=selected_binding(bindings,selection)
    if binding.assignment_type!='homework':
        raise ValueError('Component publication is homework-only')
    spreadsheet=pipeline.settings.class_sheets[binding.class_name]
    roster=pipeline.sheets.roster(spreadsheet,binding)
    sources=pipeline.sources(binding,roster)
    if pipeline.discovery_errors:
        raise ValueError('Unresolved identity/receipt prevents notebook publication')
    sid=selection['student_ids'][0]
    found=[(student,source) for student,source in sources if student['id']==sid]
    if len(found)!=1:
        raise ValueError('Notebook source absent or ambiguous')
    student,source=found[0]
    state=pipeline.store.jobs.get(pipeline.store.identity(binding,student))
    if not state or state.get('payload') or state['phase']=='complete':
        raise ValueError('Only an incomplete unpublished essay job may return its notebook separately')
    if Binding.model_validate(state['binding'])!=binding or source!=state['source'] or not receipt_allowed(binding,parse_receipt(source['received_at'])):
        raise ValueError('Frozen notebook binding/source/receipt changed')
    if pipeline.store.locked_notebook(binding,student):
        raise ValueError('Notebook locked; cannot publish a pass')
    result=NotebookResult.model_validate(state.get('notebook'))
    if notebook_state(result)!='pass':
        raise ValueError('Notebook must be verified complete')
    review=state.get('notebook_publication_review',{})
    if review.get('status')!='approved' or not review.get('delivery_authorized') or not review.get('quality_evidence'):
        raise ValueError('Independent notebook approval is required')
    if review.get('notebook_sha256')!=payload_digest(state['notebook']):
        raise ValueError('Approved notebook result changed')
    expected_files=set(binding.source_file_ids)|set(source['notebook_ids'])
    if set(review.get('file_checksums',{}))!=expected_files:
        raise ValueError('Notebook approval must cover every assigned and submitted file')
    for fid in expected_files:
        data,_=pipeline.drive.download(fid)
        if hashlib.sha256(data).hexdigest()!=review['file_checksums'][fid]:
            raise ValueError('Notebook/source file changed after independent review')
    publication=state.setdefault('notebook_publication',{})
    expected_payload=pipeline.payload(binding,student,source,'pending',
        result.summary_vi+'\nBài viết: đang chờ trả bản chữa.')
    payload=publication.get('payload') or expected_payload
    # Regenerate semantic content from the exact reviewed notebook, never trust a
    # separately supplied warning or any copied essay cards.
    if {k:v for k,v in payload.items() if k!='graded_at'}!={k:v for k,v in expected_payload.items() if k!='graded_at'}:
        raise ValueError('Notebook-only publication contains unapproved content')
    check_suppression(payload)
    publication['payload']=payload
    pipeline.store.save(state)
    publication['dashboard_evidence']=pipeline.dashboard.publish(payload)
    pipeline.store.save(state)
    publication['tracker_evidence']=pipeline.sheets.write_feedback(spreadsheet,binding,student,feedback_block(payload,pipeline.dashboard.link(binding.class_name,student['id'])))
    pipeline.store.save(state)
    publication['parent_dashboard_evidence']=pipeline.dashboard.verify_parent_ui(payload,pipeline.sheets.parent_link(spreadsheet,binding,student))
    pipeline.store.save(state)
    return {'notebooks_published':1,'essays_published':0,'model_generation_calls':0,
        'tracker_verified':bool(publication['tracker_evidence'].get('exact_readback')),'grading_complete':False}

def deliver_pilot(pipeline,bindings,selection):
    binding=selected_binding(bindings,selection)
    spreadsheet=pipeline.settings.class_sheets[binding.class_name]
    roster=pipeline.sheets.roster(spreadsheet,binding)
    sources=pipeline.sources(binding,roster)
    if pipeline.discovery_errors:
        raise ValueError('Unresolved identity/receipt prevents pilot delivery')
    report={'delivered':0,'model_generation_calls':0,'tracker_verified':0}
    for sid in selection['student_ids']:
        found=[(s,source) for s,source in sources if s['id']==sid]
        if len(found)!=1:
            raise ValueError('Selected pilot source absent/ambiguous')
        student,source=found[0]
        state=pipeline.store.jobs.get(pipeline.store.identity(binding,student))
        if not state or not state.get('payload'):
            raise ValueError('No saved completed pilot result')
        review=state.get('pilot_review',{})
        if review.get('status')!='approved' or not review.get('delivery_authorized') or not review.get('quality_evidence'):
            raise ValueError('Pilot requires source-based quality verification before delivery')
        if review.get('approved_payload_sha256')!=payload_digest(state['payload']):
            raise ValueError('Approved payload changed; do not deliver')
        frozen=Binding.model_validate(state['binding'])
        if frozen!=binding or source!=state['source'] or not receipt_allowed(binding,parse_receipt(source['received_at'])):
            raise ValueError('Pilot frozen binding/source/receipt changed')
        if state['payload']['state']!='graded' or len(state['payload']['essays'])!=len(binding.essays):
            raise ValueError('Pilot must contain all assigned exercises before delivery')
        if pipeline.store.locked_notebook(binding,student):
            raise ValueError('Notebook locked; do not publish essays')
        # No call to grade(): publication strictly reuses approved saved results.
        deliver(state,binding,student,pipeline.dashboard,pipeline.sheets,pipeline.store,
            spreadsheet,pipeline.drive,pipeline.settings)
        report['delivered']+=1
        report['tracker_verified']+=bool(state.get('tracker_evidence',{}).get('exact_readback'))
    return report
