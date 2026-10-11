from types import SimpleNamespace as N
import json
import pytest
from src.graders.teaching_fairness import validate_teaching_fairness
from src.graders.essay_bundle import restore_bundle,grade_bundle
from test_hybrid_bundle import originals,audited

def item(original='',suggested='',body='Soccer was popular.',last='Other sports accounted for the rest.'):
    return N(corrections=[N(original=original,suggested=suggested)] if original else [],
             upgraded_paragraphs=[[N(text=s)] for s in ['Introduction.','Overview.',body,last]])
def spec(rule=True):
    return N(task=1,taught_theory=('RESIDUAL_CATEGORY_LAST:'+json.dumps({'labels':['Other sports'],
        'named_categories':['soccer','netball','tennis']})) if rule else 'No residual category assigned.')

@pytest.mark.parametrize('a,b', [('in the US','in the United States'),('in the UK','in the United Kingdom'),
    ('US dollars','United States dollars'),('the UN','the United Nations'),('GDP','gross domestic product')])
def test_expansion_only_is_not_a_student_error(a,b):
    with pytest.raises(ValueError,match='expansion alone'):validate_teaching_fairness(item(a,b),spec(False))

@pytest.mark.parametrize('a,b',[('in US','in the US'),('in the uk','in the UK'),
    ("don't",'do not'),('20 US dollars','20 thousand US dollars')])
def test_real_article_case_register_and_unit_changes_remain_reviewable(a,b):
    validate_teaching_fairness(item(a,b),spec(False))

def test_residual_last_only_for_explicit_lesson_rule():
    wrong=item(body='Soccer and other sports were popular.',last='Netball came next.')
    with pytest.raises(ValueError,match='final Detail'):validate_teaching_fairness(wrong,spec())
    validate_teaching_fairness(wrong,spec(False))
    validate_teaching_fairness(item(),spec())
    with pytest.raises(ValueError,match='final Detail'):
        validate_teaching_fairness(item(last='Other sports came next. Tennis was popular.'),spec())
    with pytest.raises(ValueError,match='omits'):
        validate_teaching_fairness(item(last='Netball was popular.'),spec())
    validate_teaching_fairness(item(last='Other workers earned less.'),spec(False))

def test_old_contract_replay_does_not_gain_new_fairness_gate(binding,monkeypatch):
    specs,texts,response=originals(binding)
    data=audited(response)
    from src.graders import essay_bundle as module
    def forbidden(*args):raise AssertionError('New contract applied to old output')
    monkeypatch.setattr(module,'validate_teaching_fairness',forbidden)
    restore_bundle(data,specs,texts)
    with pytest.raises(AssertionError,match='New contract'):
        restore_bundle(data,specs,texts,teaching_fairness=True)
    ai=N(structured=lambda *args: (_ for _ in ()).throw(AssertionError('Paid call during replay')))
    settings=N(essay_model='gemini-3.1-pro-preview')
    from src.parsers import digest
    _,source_digest=module.prepare_bundle(specs,texts)
    pending={'mode':'hybrid-two-essays-v06-clause-context-and-boundaries','model':settings.essay_model,
             'source_digest':source_digest,'status':'received','result':data.model_dump(),
             'prompt':'sealed old prompt','prompt_sha256':digest('sealed old prompt')}
    states=[]
    grade_bundle(ai,settings,specs,texts,states.append,pending)
    assert states[-1]['prompt']=='sealed old prompt'
