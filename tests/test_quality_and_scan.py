import pytest
from src.graders.essay_grader import grade_essay
from src.graders.essay_grader import source_quote
from src.schemas import EssayResult, QualityReview
from src.parsers import essay_paragraphs
import src.pipeline as module
from src.pipeline import Pipeline
from src.state import StateStore
from conftest import FakeDrive, FakeSheets, FakeDashboard, essay

def test_form_single_newline_paragraphs_preserve_four_paragraphs():
    text='Introduction.\r\nOverview.\r\nFirst detail.\r\nSecond detail.'
    assert len(essay_paragraphs(text))==4
    assert text=='Introduction.\r\nOverview.\r\nFirst detail.\r\nSecond detail.'

def test_blank_line_paragraphs_allow_wrapped_lines():
    assert len(essay_paragraphs('Introduction\nwrapped line.\n\nOverview.\n\nDetail one.\n\nDetail two.'))==4

def test_model_quote_recovers_only_unique_source_whitespace():
    assert source_quote('slightly higher scores','slightly higher  scores')=='slightly higher  scores'
    with pytest.raises(ValueError,match='absent or ambiguous'):
        source_quote('slightly higher scores','slightly lower  scores')
    with pytest.raises(ValueError,match='absent or ambiguous'):
        source_quote('higher scores','higher  scores; higher   scores')

def test_one_pass_has_no_review_and_no_attachments(binding,settings):
    original=' '.join(['word']*260)
    class AI:
        def __init__(self): self.calls=[]
        def structured(self,model,prompt,schema,attachments):
            self.calls.append(schema)
            assert schema is EssayResult and attachments==()
            assert 'check every original clause' in prompt
            return essay(original,binding.essays[0])
    ai=AI()
    assert grade_essay(ai,settings,binding.essays[0],original,[('scan',b'private notebook','application/pdf')]).original==original
    assert ai.calls==[EssayResult]

def test_invalid_quote_held_without_paid_retry_even_after_restart(binding,settings):
    original=' '.join(['word']*260)
    class AI:
        def __init__(self): self.calls=[]
        def structured(self,model,prompt,schema,*_):
            self.calls.append(schema)
            result=essay(original,binding.essays[0])
            from src.schemas import Correction
            result.corrections=[Correction(section='Detail',original='invented quote',error='Invalid quote',suggested='word')]
            return result
    ai=AI()
    checkpoints=[]
    with pytest.raises(ValueError,match='absent'):
        grade_essay(ai,settings,binding.essays[0],original,[],checkpoint=checkpoints.append)
    assert checkpoints[0]['status']=='reserved' and checkpoints[-1]['status']=='held'
    with pytest.raises(ValueError,match='no automatic paid'):
        grade_essay(ai,settings,binding.essays[0],original,[],pending=checkpoints[-1])
    assert ai.calls==[EssayResult]

def test_one_pass_validated_checkpoint_reused_without_model(binding,settings):
    original=' '.join(['word']*260)
    class AI:
        def structured(self,model,prompt,schema,*_):
            return essay(original,binding.essays[0])
    checkpoints=[]
    grade_essay(AI(),settings,binding.essays[0],original,[],checkpoint=checkpoints.append)
    assert grade_essay(None,settings,binding.essays[0],original,[],pending=checkpoints[-1]).word_count==260

def test_unresolved_legacy_review_preserved_without_regeneration(binding,settings):
    original=' '.join(['word']*260)
    from src.parsers import digest
    pending={'source_digest':digest(original+'\0'+binding.essays[0].model_dump_json()+'\0False'),
        'result':essay(original,binding.essays[0]).model_dump(mode='json'),
        'review':QualityReview(approved=False,issues=['Clarify comparison scope.']).model_dump()}
    with pytest.raises(ValueError,match='no automatic paid'):
        grade_essay(None,settings,binding.essays[0],original,[],pending=pending)
    with pytest.raises(ValueError,match='frozen original'):
        grade_essay(None,settings,binding.essays[0],original+' changed',[],pending=pending)

def test_assessment_has_no_notebook_gate_and_moves_only_after_delivery(binding,settings,monkeypatch):
    binding=binding.model_copy(update={'assignment_type':'assessment','task_code':'TEST3'})
    drive=FakeDrive()
    original_listing=drive.folder_files
    drive.folder_files=lambda folder:[{'id':'scan_file_123','name':'IELTS45_Nguyễn Test_TEST3.pdf','mimeType':'application/pdf'}] if folder=='incoming' else original_listing(folder)
    sheets=FakeSheets([]); sheets.fail_once=True; dashboard=FakeDashboard(); store=StateStore(drive,'state')
    pipeline=Pipeline(settings,sheets,drive,None,store,dashboard)
    monkeypatch.setattr(module,'grade_notebook',lambda *_: (_ for _ in ()).throw(AssertionError('No notebook gate for tests')))
    monkeypatch.setattr(module,'transcribe',lambda *_:{1:'Original assessment essay'})
    seen=[]
    def grade(ai,settings,spec,original,refs,assessment,*_): seen.append(assessment); return essay(original,spec)
    monkeypatch.setattr(module,'grade_essay',grade)
    assert pipeline.run([binding])['errors'] and not drive.moved
    assert pipeline.run([binding])['completed']==1 and len(drive.moved)==1 and seen==[True]

def test_preexisting_grading_not_automatically_regraded(binding,settings,monkeypatch):
    drive=FakeDrive(); sheets=FakeSheets([['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    sheets.has_prior_grading=lambda *_:True
    pipeline=Pipeline(settings,sheets,drive,None,StateStore(drive,'state'),FakeDashboard())
    monkeypatch.setattr(module,'grade_notebook',lambda *_: (_ for _ in ()).throw(AssertionError('No automatic historical regrade')))
    assert pipeline.run([binding])['errors'] and not drive.downloaded
