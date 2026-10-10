import pytest
from src.graders.essay_grader import grade_essay
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

def test_quality_audit_requires_resolution(binding,settings):
    original=' '.join(['word']*260)
    class AI:
        def __init__(self): self.calls=[]
        def structured(self,model,prompt,schema,*_):
            self.calls.append(schema)
            return essay(original,binding.essays[0]) if schema is EssayResult else QualityReview(approved=False,issues=['Chưa nhận xét tín hiệu mở ý thứ nhất.'])
    ai=AI()
    with pytest.raises(ValueError,match='quality audit'): grade_essay(ai,settings,binding.essays[0],original,[])
    assert ai.calls==[EssayResult,QualityReview]*3

def test_invalid_model_quote_is_repaired_before_quality_audit(binding,settings):
    original=' '.join(['word']*260)
    class AI:
        def __init__(self): self.calls=[]
        def structured(self,model,prompt,schema,*_):
            self.calls.append(schema)
            if schema is QualityReview: return QualityReview(approved=True,issues=[])
            result=essay(original,binding.essays[0])
            if len(self.calls)==1:
                from src.schemas import Correction
                result.corrections=[Correction(section='Detail',original='invented quote',error='Invalid quote',suggested='word')]
            else: assert 'failed validation' in prompt
            return result
    ai=AI()
    assert grade_essay(ai,settings,binding.essays[0],original,[]).original==original
    assert ai.calls==[EssayResult,EssayResult,QualityReview]

def test_quality_audit_passes_verified_result(binding,settings):
    original=' '.join(['word']*260)
    class AI:
        def structured(self,model,prompt,schema,*_):
            return essay(original,binding.essays[0]) if schema is EssayResult else QualityReview(approved=True,issues=[])
    assert grade_essay(AI(),settings,binding.essays[0],original,[]).word_count==260

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
    def grade(ai,settings,spec,original,refs,assessment): seen.append(assessment); return essay(original,spec)
    monkeypatch.setattr(module,'grade_essay',grade)
    assert pipeline.run([binding])['errors'] and not drive.moved
    assert pipeline.run([binding])['completed']==1 and len(drive.moved)==1 and seen==[True]

def test_preexisting_grading_not_automatically_regraded(binding,settings,monkeypatch):
    drive=FakeDrive(); sheets=FakeSheets([['Time','Name','Notes','Essay'],['09/10/2026 23:00:00','Nguyễn Test','notebook_file_123','Essay']])
    sheets.has_prior_grading=lambda *_:True
    pipeline=Pipeline(settings,sheets,drive,None,StateStore(drive,'state'),FakeDashboard())
    monkeypatch.setattr(module,'grade_notebook',lambda *_: (_ for _ in ()).throw(AssertionError('No automatic historical regrade')))
    assert pipeline.run([binding])['errors'] and not drive.downloaded
