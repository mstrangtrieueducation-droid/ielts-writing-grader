"""A real, explicitly selected grading attempt, staged privately before delivery."""
import json
from .policy import eligible_binding,receipt_allowed
from .parsers import parse_receipt

def selected_binding(bindings, selection):
    if set(selection) != {'class_name','task_code','student_ids'}:
        raise ValueError('Pilot selection requires an exact class, task and student IDs')
    ids=selection['student_ids']
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)):
        raise ValueError('Pilot student IDs must be explicit and unique')
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
    report={'staged':0,'essays':0,'notebook_failed':0,'live_feedback_writes':0,'job_ids':[]}
    for sid in selection['student_ids']:
        student,source=selected[sid]
        if source.get('missing') or not receipt_allowed(binding,parse_receipt(source['received_at'])):
            raise ValueError('Pilot requires an eligible original receipt')
        jid=pipeline.store.identity(binding,student)
        existing=pipeline.store.jobs.get(jid)
        if existing and existing['phase']=='complete':
            raise ValueError('Already delivered pilot is preserved')
        if not existing and not binding.regrade_authorizations.get(sid) and pipeline.sheets.has_prior_grading(spreadsheet,binding,student):
            raise ValueError('Previously returned feedback is preserved')
        state=pipeline.store.begin(binding,student,source)
        try:
            pipeline.grade(state,binding)
        except Exception as exc:
            state['last_error']={'type':type(exc).__name__,
                'reason':str(exc) if isinstance(exc,ValueError) else 'External grading operation failed; inspect the private API audit and resume saved phase'}
            pipeline.store.save(state)
            raise
        state['pilot_review']={'status':'awaiting_review','delivery_authorized':False}
        pipeline.store.save(state)
        report['staged']+=1
        report['essays']+=len(state['payload']['essays'])
        report['notebook_failed']+=state['payload']['state']=='notebook_failed'
        report['job_ids'].append(jid)
    pipeline.store.drive.write_json(pipeline.store.folder,'pilot-'+binding.class_name.replace(' ','-')+'-'+binding.task_code+'.json',report)
    return report
