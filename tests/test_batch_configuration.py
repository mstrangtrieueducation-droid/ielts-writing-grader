import base64
import json
from pathlib import Path

import pytest
import yaml

from src.config import Settings


@pytest.fixture
def configured_env(monkeypatch):
    values = {
        'DASHBOARD_MASTER_KEY': base64.b64encode(b'x' * 32).decode(),
        'GCP_SA_KEY': json.dumps({'type': 'service_account'}),
        'CLASS_SHEET_MAP_JSON': json.dumps({'TEST': 'synthetic-sheet'}),
        'GEMINI_API_KEY': 'synthetic-not-a-key',
        'GUIDELINES_SPREADSHEET_ID': 'synthetic-guidelines',
        'FOLDER_STATE_ID': 'state',
        'FOLDER_INCOMING_SCAN_ID': 'incoming',
        'FOLDER_PROCESSED_SCAN_ID': 'processed',
        'GEMINI_NOTEBOOK_MODEL': 'gemini-3.8-flash',
        'DASHBOARD_BASE_URL': 'https://example.test',
    }
    for key in ('GEMINI_ESSAY_REQUEST_MODE', 'GEMINI_ESSAY_MODEL',
                'GEMINI_ESSAY_SERVICE_TIER', 'GEMINI_ESSAY_BUNDLE',
                'GEMINI_PRO_MAX_OUTPUT_TOKENS', 'GOOGLE_STATE_OAUTH_JSON',
                'GEMINI_STUDENT_BUDGET_VND'):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_environment_defaults_are_independent_pro_batch_without_raising_budget(configured_env):
    settings = Settings.from_env()
    assert settings.essay_request_mode == 'per_essay_batch'
    assert settings.essay_model == 'gemini-3.1-pro-preview'
    assert settings.essay_service_tier == 'batch'
    assert settings.essay_bundle is False
    assert settings.pro_max_output_tokens == 16384
    assert settings.student_budget_vnd == 1000


@pytest.mark.parametrize('key,value', [
    ('GEMINI_ESSAY_MODEL', 'gemini-3.8-flash'),
    ('GEMINI_ESSAY_SERVICE_TIER', 'standard'),
    ('GEMINI_ESSAY_SERVICE_TIER', 'flex'),
    ('GEMINI_ESSAY_BUNDLE', 'true'),
    ('GEMINI_PRO_MAX_OUTPUT_TOKENS', '8192'),
])
def test_stale_production_settings_fail_closed_instead_of_falling_back(configured_env, key, value):
    configured_env.setenv(key, value)
    with pytest.raises(ValueError, match='Per-essay production requires'):
        Settings.from_env()


def test_legacy_saved_result_collection_keeps_compatible_settings(configured_env):
    configured_env.setenv('GEMINI_ESSAY_REQUEST_MODE', 'legacy')
    configured_env.setenv('GEMINI_ESSAY_SERVICE_TIER', 'batch')
    settings = Settings.from_env()
    assert settings.essay_request_mode == 'legacy'
    assert settings.pro_max_output_tokens == 8192


def test_unknown_request_mode_does_not_silently_run_legacy(configured_env):
    configured_env.setenv('GEMINI_ESSAY_REQUEST_MODE', 'per_essay_bach')
    with pytest.raises(ValueError, match='Unknown essay request mode'):
        Settings.from_env()


def test_scheduled_collection_remains_available_when_generation_is_off():
    workflow = yaml.safe_load((Path(__file__).parents[1] /
                              '.github/workflows/grade_writing.yml').read_text(encoding='utf-8'))
    job = workflow['jobs']['grade']
    assert 'if' not in job  # Paid generation flags must not skip pending-job collection.
    steps = job['steps']
    collect = next(step for step in steps if step.get('run') == 'python -m src.main --collect-batches')
    assert "github.event_name != 'workflow_dispatch'" in collect['if']
    assert 'vars.GRADING_ENABLED' not in collect['if']
    assert 'vars.GEMINI_GENERATION_ENABLED' not in collect['if']
    assert collect['env']['GEMINI_GENERATION_ENABLED'] == 'false'
    assert job['env']['GRADING_ENABLED'] == "${{ vars.GRADING_ENABLED || 'false' }}"
    for command in ('python -m src.main', 'python -m src.main --pilot'):
        step = next(step for step in steps if step.get('run') == command)
        assert "vars.GRADING_ENABLED == 'true'" in step['if']
        assert "vars.GEMINI_GENERATION_ENABLED == 'true'" in step['if']
    assert steps.index(collect) < next(i for i, step in enumerate(steps)
                                       if step.get('run') == 'python -m src.main')


def test_workflow_cannot_override_generation_flags_or_export_private_requests():
    path = Path(__file__).parents[1] / '.github/workflows/grade_writing.yml'
    text = path.read_text(encoding='utf-8')
    workflow = yaml.safe_load(text)
    job = workflow['jobs']['grade']
    assert 'inputs.authorized_' not in text
    assert job['env']['GEMINI_ESSAY_SERVICE_TIER'] == 'batch'
    assert job['env']['GEMINI_ESSAY_MODEL'] == 'gemini-3.1-pro-preview'
    assert job['env']['GEMINI_ESSAY_BUNDLE'] == 'false'
    assert "inputs.mode == 'pilot'" not in job['env']['GEMINI_ESSAY_REQUEST_MODE']
    assert workflow['concurrency']['cancel-in-progress'] is False
    assert all('upload-artifact' not in step.get('uses', '') for step in job['steps'])


@pytest.mark.parametrize('preflight_outcome,cancelled,enabled,should_grade',[
    ('success',False,True,True),  # A collector error after successful preflight is independent.
    ('failure',False,True,False),
    ('skipped',False,True,False),  # Earlier test/setup failure means preflight never ran.
    ('success',True,True,False),
    ('success',False,False,False),
])
def test_collector_errors_do_not_skip_grading_or_bypass_validation(preflight_outcome,cancelled,enabled,should_grade):
    workflow=yaml.safe_load((Path(__file__).parents[1]/'.github/workflows/grade_writing.yml').read_text(encoding='utf-8'))
    steps=workflow['jobs']['grade']['steps']
    preflight=next(s for s in steps if s.get('id')=='preflight')
    collect=next(s for s in steps if s.get('run')=='python -m src.main --collect-batches')
    grade=next(s for s in steps if s.get('run')=='python -m src.main')
    assert preflight['run']=='python -m src.main --preflight' and 'if' not in preflight
    assert all(not s.get('continue-on-error') for s in steps[:steps.index(preflight)+1])
    assert not collect.get('continue-on-error')  # Collector failure stays visible in Actions.
    assert steps.index(preflight)<steps.index(collect)<steps.index(grade)
    expression=grade['if'].removeprefix('${{').removesuffix('}}').strip()
    assert '!cancelled()' in expression  # Explicit status function overrides implicit success().
    values={'cancelled()':repr(cancelled),'steps.preflight.outcome':repr(preflight_outcome),
        'github.event_name':repr('schedule'),'inputs.mode':repr(''),
        'vars.GRADING_ENABLED':repr('true' if enabled else 'false'),
        'vars.GEMINI_GENERATION_ENABLED':repr('true' if enabled else 'false')}
    for token,value in values.items():expression=expression.replace(token,value)
    expression=expression.replace('!=','<>').replace('!','not ').replace('<>','!=')
    expression=expression.replace('&&',' and ').replace('||',' or ')
    assert eval(expression,{'__builtins__':{}},{}) is should_grade
