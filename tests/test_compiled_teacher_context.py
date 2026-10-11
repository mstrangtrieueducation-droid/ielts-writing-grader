import copy
import hashlib
import json
from types import SimpleNamespace as N

import pytest

from conftest import FakeDrive
from test_teacher_knowledge import corpus
from test_hybrid_bundle import originals
from src.lesson_packages import fingerprint
from src.teacher_knowledge import (load_teaching_context, verify_compiled_context,
    verify_compiled_against_corpus)
from src.graders.essay_batch import prepare_essay_requests


def pack():
    archived, full = corpus()
    doc = archived['documents'][0]
    sample = doc['text'][0:20]
    context = {'schema_version': 1, 'lesson': 14, 'source_corpus_sha256': full['sha256'],
        'content': 'Reviewed lesson rules.\n' + sample,
        'coverage': [{'document_id': doc['id'], 'lesson': doc['lesson'],
            'source_sha256': doc['sha256'], 'compiled_functions': ['Applicable rules']}],
        'models': [{'source_document_id': doc['id'], 'source_document_sha256': doc['sha256'],
            'start_offset': 0, 'end_offset': len(sample), 'text': sample,
            'text_sha256': hashlib.sha256(sample.encode()).hexdigest()}],
        'latest_clarifications': [{'rule': 'US and UK accepted.'}]}
    reference = {'filename': 'compiled.json', 'lesson': 14,
        'sha256': fingerprint(context), 'teacher_authorized': True}
    return archived, context, {'id': 'B14', 'version': 'v10', 'full_teacher_sources': full,
        'compiled_teacher_sources': reference, 'body_sentence_policy': 'source_scoped_flexible'}


def test_compiled_pack_loaded_once_and_models_verified_against_preserved_full_source():
    archived, context, package = pack()
    drive = FakeDrive()
    drive.state.update({'compiled.json': context, package['full_teacher_sources']['filename']: archived})
    saved = []
    store = N(drive=drive, folder='state', save=lambda state: saved.append(copy.deepcopy(state)))
    state = {}
    assert load_teaching_context(store, state, package) == context
    assert load_teaching_context(store, state, package) == context
    assert len(drive.downloaded) == 2
    assert state['teacher_knowledge'] == archived
    assert state['teacher_compiled_context'] == context


@pytest.mark.parametrize('bad', ['missing_source', 'source_hash', 'model_hash', 'missing_model',
    'missing_clarification', 'empty_content', 'changed_corpus', 'no_authority'])
def test_compilation_cannot_silently_drop_sources_models_or_authority(bad):
    _, context, package = pack()
    reference = package['compiled_teacher_sources']
    if bad == 'missing_source': context['coverage'] = []
    if bad == 'source_hash': context['coverage'][0]['source_sha256'] = 'wrong'
    if bad == 'model_hash': context['models'][0]['text_sha256'] = 'wrong'
    if bad == 'missing_model': context['content'] = 'Rules without the declared model.'
    if bad == 'missing_clarification': context['latest_clarifications'] = []
    if bad == 'empty_content': context['content'] = ''
    if bad == 'changed_corpus': context['source_corpus_sha256'] = 'wrong'
    if bad == 'no_authority': reference['teacher_authorized'] = False
    # Even repinning a new hash cannot bypass structural source validation.
    reference['sha256'] = fingerprint(context)
    with pytest.raises(ValueError):
        verify_compiled_context(context, reference, package['full_teacher_sources'])


def test_changed_excerpt_offsets_are_not_mistaken_for_verbatim_teacher_model():
    archived, context, _ = pack()
    context['models'][0]['start_offset'] += 1
    context['models'][0]['end_offset'] += 1
    with pytest.raises(ValueError, match='not verbatim'):
        verify_compiled_against_corpus(context, archived)


def test_only_reviewed_compiled_mode_removes_redundant_instructions_not_student_evidence(binding, monkeypatch):
    from src import lesson_packages
    from src.graders.essay_batch import RUBRIC, QUALITY_CONTRACT
    archived, context, package = pack()
    package['teaching_context'] = 'Old duplicate navigation context.'
    monkeypatch.setattr(lesson_packages, 'resolve_package', lambda specs: package)
    specs, texts, _ = originals(binding)
    requests = prepare_essay_requests(specs, texts, context)
    assert len(requests) == 2
    for index, request in enumerate(requests):
        prompt = request['prompt']
        assert context['content'] in prompt
        assert archived['documents'][0]['text'] not in prompt
        assert RUBRIC not in prompt and QUALITY_CONTRACT not in prompt
        assert package['teaching_context'] not in prompt
        record = json.loads(prompt.split('\n')[-1])
        assert record['original'] == texts[str(index + 1)]
        assert record['specification']['taught_theory'] == specs[index].taught_theory
        assert 'body_min_sentences' not in record['specification']
    with pytest.raises(ValueError, match='summary-only'):
        prepare_essay_requests(specs, texts)
