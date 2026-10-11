"""Class-independent lesson packages, selected by verified content, not roster.

The catalog records prepared versions separately from live-quality acceptance.
A package is not grading authorization and cannot change receipts or budgets.
"""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'prompt-library'

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def essay_fingerprint(specs):
    return fingerprint([s.model_dump(mode='json') for s in sorted(specs,key=lambda s:s.exercise)])

def notebook_fingerprint(binding):
    return fingerprint({'scope':binding.notebook_copy_scope,
        'requirements':[r.model_dump(mode='json') for r in binding.notebook_requirements],
        'outline_requirements':[r.model_dump(mode='json') for r in binding.outline_requirements]})

def resolve_package(specs,root=None):
    root=Path(root) if root is not None else ROOT
    if not (root/'catalog.json').exists():return None
    catalog=json.loads((root/'catalog.json').read_text(encoding='utf-8'))
    matches=[]
    for entry in catalog['packages']:
        path=(root/entry['manifest']).resolve()
        if not path.is_relative_to(root.resolve()):raise ValueError('Lesson package path escapes library')
        package=json.loads(path.read_text(encoding='utf-8'))
        if package['essay_fingerprint']==essay_fingerprint(specs):
            if fingerprint(package)!=entry['manifest_sha256']:raise ValueError('Lesson package manifest changed')
            for ref in package['prompt_files']:
                source=(ROOT.parent/ref['path']).resolve()
                if not source.is_relative_to(ROOT.parent.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest()!=ref['sha256']:
                    raise ValueError('Reusable prompt changed without a new package version')
            matches.append(package)
    if len(matches)>1:raise ValueError('Ambiguous active lesson package')
    return matches[0] if matches else None

def verify_package_sources(binding,source_checksums):
    package=resolve_package(binding.essays)
    if package is None:return None
    if binding.lesson!=package['lesson'] or notebook_fingerprint(binding)!=package['notebook_fingerprint']:
        raise ValueError('Lesson package copying requirements differ; verify a new version')
    if sorted(source_checksums.values())!=package['assigned_source_sha256']:
        raise ValueError('Assigned lesson source changed; verify a new package version')
    return {'id':package['id'],'version':package['version'],'quality_status':package['quality_status']}
