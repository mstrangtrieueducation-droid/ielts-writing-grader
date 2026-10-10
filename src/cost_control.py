"""Conservative application budget, durable under the serialized Actions writer.

This is not a Google billing cap. Unknown/in-flight calls keep their full reserve.
Prices are a dated standard-tier snapshot; no free-tier/cache discount is assumed.
"""
import json
import math
from datetime import datetime, timezone
from .parsers import digest

PRICES = {'gemini-3.1-pro-preview': (2.0, 12.0),
          'gemini-3.8-flash': (0.75, 3.75)}
PRICE_VALID_THROUGH = '2026-12-31'
USD_VND = 26000  # Budget assumption, not the bank's billing conversion.
CLASS_BUDGET_VND = 14900

def cost_vnd(model, input_tokens, output_tokens, fx=USD_VND):
    if model not in PRICES or input_tokens > 200000:
        raise ValueError('Model/context has no verified budget price; generation held')
    if min(input_tokens,output_tokens,fx) < 0:
        raise ValueError('Invalid cost inputs')
    price_in,price_out=PRICES[model]
    return (input_tokens*price_in+output_tokens*price_out)*fx/1_000_000

class ClassBudget:
    def __init__(self, store, binding, job, student_limit=None):
        self.drive,self.folder=store.drive,store.folder
        self.scope={'class_name':binding.class_name,'task_code':binding.task_code}
        self.filename='cost-ledger-'+digest(json.dumps(self.scope,sort_keys=True))+'.json'
        found=[f for f in self.drive.folder_files(self.folder) if f['name']==self.filename]
        if len(found)>1:
            raise ValueError('Duplicate cost ledger; generation held')
        self.data=json.loads(self.drive.download(found[0]['id'])[0]) if found else {
            'scope':self.scope,'limit_vnd':CLASS_BUDGET_VND,'fx_assumption':USD_VND,'calls':{}}
        if self.data['scope']!=self.scope or self.data['limit_vnd']!=CLASS_BUDGET_VND:
            raise ValueError('Cost ledger scope/limit differs; generation held')
        self.job_id=job['job_id']
        self.trial_limit=job.get('trial_cost_ceiling_vnd')
        self.student_limit=student_limit
        self.student_id=job.get('student',{}).get('id')
        self.jobs=store.jobs
        if student_limit is not None and not self.student_id:
            raise ValueError('Stable student identity required for student cost ceiling')

    def ensure_capacity(self, amount):
        calls=list(self.data['calls'].values())
        value=lambda c:c.get('accounted_vnd',c['reserved_vnd'])
        if self.student_limit is not None:
            student_spent=0
            for call in calls:
                identity=call.get('student_id') or self.jobs.get(call.get('job_id'),{}).get('student',{}).get('id')
                if not identity:
                    raise ValueError('Historical cost identity is unresolved; student budget held')
                if identity==self.student_id:
                    student_spent+=value(call)
            if student_spent+amount>self.student_limit:
                raise ValueError(f'Student/task cost ceiling of {self.student_limit:,} VND would be exceeded; generation held')
        if self.trial_limit is not None:
            trial_spent=sum(value(c) for c in calls if c.get('job_id')==self.job_id)
            if trial_spent+amount>self.trial_limit:
                raise ValueError('Explicit trial cost ceiling would be exceeded; generation held')
        if sum(value(c) for c in calls)+amount>self.data['limit_vnd']:
            raise ValueError('Class/task budget would exceed 14,900 VND; generation held')

    def save(self):
        self.drive.write_json(self.folder,self.filename,self.data)

    def key(self, fingerprint):
        return digest(self.job_id+'|'+fingerprint)

    def existing(self, key):
        call=self.data['calls'].get(key)
        if call and call.get('status')!='received':
            raise ValueError('Prior paid call unresolved; no automatic retry')
        return call

    def reserve(self, key, model, tokens, max_output):
        if datetime.now(timezone.utc).date().isoformat()>PRICE_VALID_THROUGH:
            raise ValueError('Budget price snapshot expired; generation held')
        # Allow room for token-counter overhead/schema differences; all output includes thought.
        bounded_input=math.ceil(tokens*1.2)+256
        amount=cost_vnd(model,bounded_input,max_output)
        self.ensure_capacity(amount)
        self.data['calls'][key]={'status':'reserved','model':model,'input_bound':bounded_input,
            'output_bound':max_output,'reserved_vnd':amount,'job_id':self.job_id,
            'student_id':self.student_id}
        self.save()  # Do not send a paid request unless the reserve is durable.

    def received(self, key, response_text, usage):
        call=self.data['calls'][key]
        call.update(status='received',response_text=response_text,usage_metadata=usage)
        prompt=usage.get('prompt_token_count')
        candidates=usage.get('candidates_token_count')
        thoughts=usage.get('thoughts_token_count')
        if prompt is not None and candidates is not None and thoughts is not None:
            actual=cost_vnd(call['model'],prompt,candidates+thoughts)
            # Overrun signals a bad bound. Freeze this scope rather than allowing another call.
            call['accounted_vnd']=actual
            if prompt>call['input_bound'] or candidates+thoughts>call['output_bound']:
                self.data['limit_vnd']=0
        self.save()

def estimate_class(students, essays_each, essay_in, essay_out, notebook_in, notebook_out):
    return students*(essays_each*cost_vnd('gemini-3.8-flash',essay_in,essay_out)
        +cost_vnd('gemini-3.8-flash',notebook_in,notebook_out))
