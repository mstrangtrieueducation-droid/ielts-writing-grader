import pytest
from types import SimpleNamespace
from src.retry import RateLimiter
from src.graders.copy_grader import grade_notebook
from src.sheet_service import SheetService
from src.schemas import EssayResult
from src.graders.essay_grader import validate_essay
from src.announcements import draft
from conftest import notebook, essay

def test_second_notebook_audit_disagreement_holds(binding,settings):
    class AI:
        def __init__(self): self.calls=[]
        def structured(self,model,*_):
            self.calls.append(model)
            return notebook('missing' if len(self.calls)==1 else 'complete')
    ai=AI()
    with pytest.raises(ValueError,match='disagree'):
        grade_notebook(ai,settings,binding,[],[],{'notebook_file_123':1})
    assert ai.calls==['flash','flash']

def test_pro_notebook_config_rejected_without_model(binding,settings):
    settings.notebook_model='gemini-3.1-pro-preview'
    with pytest.raises(ValueError,match='Pro is prohibited'):
        grade_notebook(None,settings,binding,[],[],{})

def test_vocabulary_failure_recheck_stays_flash(binding,settings):
    from src.graders.vocab_grader import grade_vocabulary
    binding=binding.model_copy(update={'vocabulary':binding.notebook_requirements})
    class AI:
        def __init__(self):self.calls=[]
        def structured(self,model,*_):
            self.calls.append(model)
            return notebook('typed_or_printed')
    ai=AI()
    grade_vocabulary(ai,settings,binding,[],[],{'notebook_file_123':1})
    assert ai.calls==['flash','flash']

def test_rate_limiter_enforces_spacing():
    now=[10.0]; waits=[]
    def wait(delay): waits.append(delay); now[0]+=delay
    limiter=RateLimiter(6,clock=lambda:now[0],sleeper=wait)
    limiter.wait(); limiter.wait(); assert waits==[10.0]

def test_tracker_header_ambiguity_rejected(binding):
    service=object.__new__(SheetService)
    service.values=lambda *_:[['Writing W29','Writing W29']]
    with pytest.raises(ValueError): service.feedback_column('spreadsheet',binding)

def test_tracker_formula_not_overwritten(binding):
    service=object.__new__(SheetService)
    service.feedback_column=lambda *_:'AI'
    service.values=lambda *args,**kwargs:[['=A1']]
    with pytest.raises(ValueError,match='formula'): service.write_feedback('sheet',binding,{'row':7},'block')

def test_pass_cannot_ignore_minimum_words(binding):
    result=essay('Only five words are here.',binding.essays[0]); result.status='Đạt yêu cầu'
    with pytest.raises(ValueError,match='length'): validate_essay(result,result.original,binding.essays[0])

def test_assessment_scores_required_and_no_homework_bands(binding):
    result=essay(' '.join(['word']*260),binding.essays[0])
    with pytest.raises(ValueError,match='band'): validate_essay(result,result.original,binding.essays[0],True)
    result.band_scores={'TR':6,'CC':6,'LR':6,'GRA':6}
    validate_essay(result,result.original,binding.essays[0],True)
    with pytest.raises(ValueError,match='Homework'): validate_essay(result,result.original,binding.essays[0],False)

def test_no_zalo_draft_before_all_delivery_evidence(binding):
    store=SimpleNamespace(jobs={},identity=lambda *_:'job')
    assert draft(binding,[{'id':'S1'}],store) is None
    store.jobs['job']={'phase':'complete','tracker_evidence':{'exact_readback':True},'dashboard_evidence':{'live_ui_verified':False}}
    assert draft(binding,[{'id':'S1'}],store) is None
