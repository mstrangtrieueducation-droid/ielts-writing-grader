import json
import hashlib
from datetime import datetime, timezone
from .schemas import Binding
from .parsers import col_number, match_student, parse_receipt, drive_ids, parse_filename, digest
from .policy import eligible_binding, receipt_allowed, cutoff, notebook_state, gated_payload, TOO_LATE
from .media import page_count
from .graders.copy_grader import grade_notebook
from .graders.vocab_grader import grade_vocabulary
from .graders.essay_grader import grade_essay, transcribe
from .graders.essay_bundle import grade_bundle
from .delivery import deliver
from .announcements import save_draft

def cell(row, col):
    number=col_number(col)
    return str(row[number]).strip() if number<len(row) else ''

class Pipeline:
    def __init__(self, settings, sheets, drive, ai, store, dashboard):
        self.settings,self.sheets,self.drive,self.ai,self.store,self.dashboard=settings,sheets,drive,ai,store,dashboard
        self.blobs={}
        self.discovery_errors=[]

    def files(self, identifiers):
        output=[]
        for fid in dict.fromkeys(identifiers):
            if fid not in self.blobs:
                self.blobs[fid]=self.drive.download(fid)
            data,mime=self.blobs[fid]
            output.append((fid,data,mime))
        return output

    def sources(self, binding, roster):
        if binding.assignment_type=='assessment':
            output=[]
            for scan in self.drive.folder_files(self.settings.incoming_folder):
                if scan['mimeType']!='application/pdf':
                    continue
                try:
                    classroom,name,code=parse_filename(scan['name'])
                except ValueError:
                    self.discovery_errors.append({'class':binding.class_name,'task':binding.task_code,'reason':'Scan filename needs reconciliation'})
                    continue
                if classroom!=binding.class_name or code!=binding.task_code.upper():
                    continue
                try:
                    student=match_student(name,roster,binding.aliases)
                except ValueError:
                    self.discovery_errors.append({'class':binding.class_name,'task':binding.task_code,'reason':'Unmatched scan identity'})
                    continue
                output.append((student,{'received_at':None,'notebook_ids':[], 'essay_texts':{}, 'scan_id':scan['id']}))
            identities=[s['id'] for s,_ in output]
            if len(identities)!=len(set(identities)):
                raise ValueError('Multiple scans per student/task: select/reconcile explicitly before processing')
            return output
        rows=self.sheets.values(binding.form_spreadsheet_id,"'"+binding.form_tab.replace("'","''")+"'!A:ZZ")
        submissions={}
        for row_number,row in enumerate(rows[binding.submission_start_row-1:],binding.submission_start_row):
            if not any(row):
                continue
            if binding.class_column and cell(row,binding.class_column) != binding.class_name:
                continue
            try:
                student=match_student(cell(row,binding.name_column),roster,binding.aliases)
                received=parse_receipt(cell(row,binding.receipt_column))
            except ValueError:
                self.discovery_errors.append({'class':binding.class_name,'task':binding.task_code,'reason':'Form identity or receipt requires verification','row':row_number})
                continue
            record={'received_at':received.isoformat(),'form_row':row_number,
                'notebook_ids':list(dict.fromkeys(fid for column in binding.notebook_columns for fid in drive_ids(cell(row,column)))),
                'essay_texts':{str(ex):cell(row,column) for ex,column in binding.essay_columns.items()},'scan_id':None}
            submissions.setdefault(student['id'],[]).append(record)
        output=[]
        for student in roster:
            candidates=sorted(submissions.get(student['id'],[]),key=lambda s:(s['received_at'],s['form_row']))
            if not candidates:
                # Missing is reported only after the receipt boundary; never infer it from yesterday's list.
                unresolved=any(e['class']==binding.class_name and e['task']==binding.task_code for e in self.discovery_errors)
                if not unresolved and datetime.now(timezone.utc)>=cutoff(binding):
                    output.append((student,{'missing':True,'received_at':None,'notebook_ids':[],'essay_texts':{},'scan_id':None}))
                continue
            timely=[s for s in candidates if receipt_allowed(binding,parse_receipt(s['received_at']))]
            chosen={**(timely[-1] if timely else candidates[-1])}
            if timely:
                # Latest nonblank text per exercise, with its own original receipt provenance.
                chosen['essay_texts']={}
                chosen['exercise_receipts']={}
                for candidate in timely:
                    for exercise,text in candidate['essay_texts'].items():
                        if text:
                            chosen['essay_texts'][exercise]=text
                            chosen['exercise_receipts'][exercise]={'received_at':candidate['received_at'],'form_row':candidate['form_row']}
            output.append((student,chosen))
        return output

    def payload(self, binding, student, source, state_, warning, essays=()):
        received=parse_receipt(source['received_at']) if source.get('received_at') else None
        return gated_payload({'schema_version':1,'student_name':student['name'],'student_id':student['id'],
            'class_name':binding.class_name,'task_code':binding.task_code,'lesson':binding.lesson,
            'assignment_type':binding.assignment_type,'graded_at':datetime.now(timezone.utc).isoformat(),
            'received_at':source.get('received_at'),'received_display':received.strftime('%d/%m/%Y %H:%M:%S') if received else '',
            'submitted_late':bool(received and binding.due_at and received>binding.due_at),
            'state':state_,'warning':warning,'notebook_links':[f'https://drive.google.com/file/d/{fid}/view' for fid in source['notebook_ids']],
            'essays':list(essays)})

    def grade(self, state, binding):
        student,source=state['student'],state['source']
        if self.ai is not None:
            self.ai.job_id=state['job_id']
        if state.get('payload'):
            return
        if source.get('missing'):
            state['payload']=self.payload(binding,student,source,'missing','Chưa ghi nhận bài nộp.')
            self.store.save(state)
            return
        if binding.assignment_type!='assessment' and not receipt_allowed(binding,parse_receipt(source['received_at'])):
            # No PDF/image download or model call on this path.
            state['payload']=self.payload(binding,student,source,'too_late',TOO_LATE)
            self.store.save(state)
            return
        if self.ai is not None and hasattr(self.ai,'bind_budget'):
            self.ai.bind_budget(self.store,binding,state)
        hybrid=self.settings.essay_model=='gemini-3.1-pro-preview'
        if hybrid and binding.assignment_type in ('homework','assessment') and not state['essay_results'] and not state.get('bundle_work'):
            if self.ai is None or not hasattr(self.ai,'preflight_student_plan'):
                raise ValueError('Hybrid budget planning is required before notebook generation')
            self.ai.preflight_student_plan(binding)
        references=self.files(binding.source_file_ids)
        checksums={fid:hashlib.sha256(data).hexdigest() for fid,data,_ in references}
        if state.get('source_checksums') and state['source_checksums']!=checksums:
            raise ValueError('Assigned sources changed after prompt freeze; explicit audited new version required')
        state['source_checksums']=checksums
        self.store.save(state)
        if binding.assignment_type!='assessment':
            override=binding.notebook_overrides.get(student['id'],'').strip()
            if self.store.locked_notebook(binding,student):
                raise ValueError('Historical notebook lock requires an audited teacher override')
            if override:
                state['notebook_override_evidence']=override
                notebook_pass=True
                notebook_summary='Vở đạt yêu cầu theo xác nhận của Cô.'
            else:
                if not source['notebook_ids']:
                    raise ValueError('No notebook evidence received; awaiting verification')
                files=self.files(source['notebook_ids'])
                counts={fid:page_count(data,mime) for fid,data,mime in files}
                if not state['notebook']:
                    grader=grade_vocabulary if binding.assignment_type=='vocabulary' else grade_notebook
                    checked=grader(self.ai,self.settings,binding,files,references,counts)
                    state['notebook']=checked.model_dump(mode='json')
                    self.store.save(state)
                else:
                    from .schemas import NotebookResult
                    checked=NotebookResult.model_validate(state['notebook'])
                decision=notebook_state(checked)
                if decision=='pending':
                    raise ValueError('Notebook evidence uncertain; awaiting verification')
                notebook_pass=decision=='pass'
                notebook_summary=checked.summary_vi
                if not notebook_pass:
                    reasons='; '.join(i.explanation_vi for i in checked.items if i.status!='complete')
                    state['payload']=self.payload(binding,student,source,'notebook_failed',reasons)
                    self.store.save(state)
                    return
                if binding.assignment_type=='homework':
                    received_day=parse_receipt(source['received_at']).strftime('%d/%m/%Y')
                    notebook_summary=f'Đã ghi nhận vở nộp ngày {received_day} — Đạt yêu cầu.'
            if binding.assignment_type in ('notebook','vocabulary'):
                state['payload']=self.payload(binding,student,source,'graded',notebook_summary)
                self.store.save(state)
                return
        else:
            notebook_summary=''  # In-class tests never require or claim a notebook pass.
            if not state.get('transcription'):
                files=self.files([source['scan_id']])
                counts={fid:page_count(data,mime) for fid,data,mime in files}
                state['transcription']=transcribe(self.ai,self.settings,binding,files,counts)
                self.store.save(state)
            source['essay_texts']={str(k):v for k,v in state['transcription'].items()}
        if hybrid and len(state['essay_results'])!=len(binding.essays):
            if state['essay_results'] or state.get('essay_work'):
                raise ValueError('Existing individual essay attempts are preserved; no automatic hybrid regrade')
            if binding.assignment_type!='homework':
                raise ValueError('Hybrid bundle is homework-only; assessment needs a separate approved plan')
            def bundle_checkpoint(work):
                state['bundle_work']=work
                self.store.save(state)
            results=grade_bundle(self.ai,self.settings,binding.essays,source['essay_texts'],
                bundle_checkpoint,state.get('bundle_work'))
            state['essay_results']={str(result.exercise):result.model_dump(mode='json') for result in results}
            self.store.save(state)
        for spec in binding.essays:
            key=str(spec.exercise)
            if key in state['essay_results']:
                continue
            if key not in source['essay_texts']:
                raise ValueError(f'Exercise {spec.exercise} source is absent; awaiting verification')
            if binding.assignment_type!='assessment' and not receipt_allowed(binding,parse_receipt(source['received_at'])):
                raise ValueError('Original receipt no longer eligible')
            def checkpoint(work):
                state.setdefault('essay_work',{})[key]=work
                self.store.save(state)
            result=grade_essay(self.ai,self.settings,spec,source['essay_texts'][key],(),binding.assignment_type=='assessment',checkpoint,state.get('essay_work',{}).get(key))
            state['essay_results'][key]=result.model_dump(mode='json')
            self.store.save(state)
        state['payload']=self.payload(binding,student,source,'graded',notebook_summary,
            [state['essay_results'][str(e.exercise)] for e in binding.essays])
        self.store.save(state)

    def run(self, bindings, limit=None):
        limit=limit or self.settings.max_jobs
        report={'completed':0,'errors':[],'skipped':0,'pending':0,'announcements_ready':0}
        processed=0
        per_binding_limit=max(1,limit//max(1,sum(eligible_binding(b) for b in bindings)))
        for binding in bindings:
            binding_processed=0
            if not eligible_binding(binding):
                report['skipped']+=1
                continue
            spreadsheet=self.settings.class_sheets.get(binding.class_name)
            if not spreadsheet:
                report['errors'].append({'class':binding.class_name,'task':binding.task_code,'reason':'Missing tracker mapping'})
                continue
            try:
                roster=self.sheets.roster(spreadsheet,binding)
                sources=self.sources(binding,roster)
                # Existing frozen deliveries resume even if the incoming scan was moved just before a crash.
                current_ids={self.store.identity(binding,s) for s,_ in sources}
                resumed=[s for s in self.store.jobs.values() if s['binding']['class_name']==binding.class_name
                    and s['binding']['task_code']==binding.task_code and s['phase']!='complete' and not s.get('invalidation') and s['job_id'] not in current_ids]
                for s in resumed:
                    if s['student']['id'] in {r['id'] for r in roster}:
                        sources.append((next(r for r in roster if r['id']==s['student']['id']),s['source']))
                # Pending failures rotate behind unattempted/older work, preventing one class blocking others.
                sources.sort(key=lambda pair:self.store.jobs.get(self.store.identity(binding,pair[0]),{}).get('updated_at',''))
                for student,source in sources:
                    jid=self.store.identity(binding,student)
                    existing=self.store.jobs.get(jid)
                    if existing and existing['phase']=='complete' and not (
                        existing['payload']['state']=='missing' and not source.get('missing')):
                        report['skipped']+=1
                        continue
                    if processed>=limit or binding_processed>=per_binding_limit:
                        report['pending']+=1
                        continue
                    processed+=1
                    binding_processed+=1
                    try:
                        if existing and existing.get('pilot_review'):
                            raise ValueError('Private pilot requires dedicated approved delivery; regular grading cannot release it')
                        if not existing and not binding.regrade_authorizations.get(student['id']) and self.sheets.has_prior_grading(spreadsheet,binding,student):
                            raise ValueError('Existing grading from the prior system is preserved; import audited completion evidence or authorize a new attempt')
                        # A formerly missing student can later acquire a too-late receipt; never stay falsely missing.
                        if existing and existing['payload'] and existing['payload']['state']=='missing' and not source.get('missing'):
                            existing['source']=source; existing['payload']=None; existing['phase']='captured'
                            self.store.save(existing)
                        state=self.store.begin(binding,student,source)
                        frozen=Binding.model_validate(state['binding'])
                        self.grade(state,frozen)
                        deliver(state,frozen,student,self.dashboard,self.sheets,self.store,spreadsheet,self.drive,self.settings)
                        report['completed']+=1
                    except Exception as exc:
                        # Never print source text, URLs, credentials or exception request bodies.
                        report['errors'].append({'class':binding.class_name,'task':binding.task_code,'job':jid[:12],
                            'error_type':type(exc).__name__})
                        if jid in self.store.jobs:
                            failed=self.store.jobs[jid]
                            failed['last_error']={'type':type(exc).__name__, 'reason':str(exc) if isinstance(exc,ValueError) else 'External operation failed; retry saved phase'}
                            self.store.save(failed)
                if not any(e['class']==binding.class_name and e['task']==binding.task_code for e in self.discovery_errors):
                    if save_draft(binding,roster,self.store):
                        report['announcements_ready']+=1
            except Exception as exc:
                report['errors'].append({'class':binding.class_name,'task':binding.task_code,'error_type':type(exc).__name__})
        report['errors'].extend(self.discovery_errors)
        return report
