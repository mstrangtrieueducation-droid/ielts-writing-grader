import json
from datetime import datetime, timezone
from .parsers import digest

class StateStore:
    """Private durable checkpoints, serialized by the repository workflow concurrency group."""
    def __init__(self, drive, folder):
        self.drive, self.folder = drive, folder
        self.jobs = {}
        for file in drive.folder_files(folder):
            if file['name'].startswith('job-') and file['name'].endswith('.json'):
                data, _ = drive.download(file['id'])
                state = json.loads(data)
                if state['job_id'] in self.jobs:
                    raise ValueError('Duplicate durable job state')
                self.jobs[state['job_id']] = state

    @staticmethod
    def identity(binding, student):
        authorization = binding.regrade_authorizations.get(student['id'], '')
        return digest('|'.join([binding.class_name,binding.task_code,student['id'],authorization]))

    def save(self, state):
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.drive.write_json(self.folder, f"job-{state['job_id']}.json", state)
        self.jobs[state['job_id']] = state

    def begin(self, binding, student, source):
        identity = self.identity(binding, student)
        if identity in self.jobs:
            return self.jobs[identity]
        state = {'job_id':identity, 'phase':'captured', 'binding':binding.model_dump(mode='json'),
            'student':student, 'source':source, 'notebook':None, 'essay_results':{}, 'payload':None}
        self.save(state)
        return state

    def locked_notebook(self, binding, student):
        # A new upload or regrade ID alone never clears a permanent notebook lock.
        if student['id'] in binding.notebook_overrides:
            return False
        return any(s['binding']['class_name']==binding.class_name and s['binding']['task_code']==binding.task_code
            and s['student']['id']==student['id'] and s.get('payload',{}).get('state')=='notebook_failed'
            for s in self.jobs.values() if s.get('payload'))
