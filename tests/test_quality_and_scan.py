import pytest
from src.graders.essay_grader import grade_essay
from src.graders.essay_grader import source_quote
from src.schemas import EssayResult, ThoroughFlashResult, ThoroughFlashTask1Result, QualityReview
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
            assert schema is ThoroughFlashResult and attachments==()
            assert 'check every original clause' in prompt
            return essay(original,binding.essays[0])
    ai=AI()
    assert grade_essay(ai,settings,binding.essays[0],original,[('scan',b'private notebook','application/pdf')]).original==original
    assert ai.calls==[ThoroughFlashResult]

def test_essay_pro_config_rejected_without_paid_call(binding,settings):
    settings.essay_model='gemini-3.1-pro-preview'
    with pytest.raises(ValueError,match='no Pro fallback'):
        grade_essay(None,settings,binding.essays[0],'Original text',[])

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
    assert ai.calls==[ThoroughFlashResult]

def test_one_pass_validated_checkpoint_reused_without_model(binding,settings):
    original=' '.join(['word']*260)
    class AI:
        def structured(self,model,prompt,schema,*_):
            return essay(original,binding.essays[0])
    checkpoints=[]
    grade_essay(AI(),settings,binding.essays[0],original,[],checkpoint=checkpoints.append)
    assert grade_essay(None,settings,binding.essays[0],original,[],pending=checkpoints[-1]).word_count==260

def test_task1_requires_numeric_coverage_and_linked_corrections(binding,settings):
    from src.schemas import FlashTask1Result,NumericCheck
    from src.graders.essay_grader import validate_essay
    spec=binding.essays[0].model_copy(update={'task':1,'ground_truth':'A=90; B=93'})
    original='A and B exceed 90%.'
    base=essay(original,spec).model_dump()
    claim={'original_claim':original,'verdict':'incorrect','evidence':'A is exactly 90%; B is 93%.','correction_quote':original}
    result=FlashTask1Result(**base,numeric_checks=[claim])
    with pytest.raises(ValueError,match='lacks corresponding correction'):
        validate_essay(result,original,spec)
    from src.schemas import Correction
    result.corrections=[Correction(section='Body',original=original,error='Equality invalidates exceeding.',suggested='A and B are at least 90%.')]
    assert validate_essay(result,original,spec).numeric_checks[0].verdict=='incorrect'
    result.numeric_checks=[]
    with pytest.raises(ValueError,match='every original numeral'):
        validate_essay(result,original,spec)
    result.numeric_checks=[NumericCheck(**claim)]
    class AI:
        calls=0
        def structured(self,model,prompt,schema,attachments):
            self.calls+=1
            assert schema is ThoroughFlashTask1Result and not attachments
            assert 'not >=' in prompt and 'mathematically true but loose' in prompt
            return result
    checkpoints=[];ai=AI()
    grade_essay(ai,settings,spec,original,[],checkpoint=checkpoints.append)
    assert isinstance(grade_essay(None,settings,spec,original,[],pending=checkpoints[-1]),FlashTask1Result)
    assert ai.calls==1

def test_language_segments_include_unpunctuated_intro_and_decimal_values():
    from src.graders.essay_grader import language_units
    units=language_units('Introduction without final punctuation\r\nThe value was 20.5%. It rose.\r\nLast sentence.')
    assert [u['text'] for u in units]==['Introduction without final punctuation','The value was 20.5%.','It rose.','Last sentence.']
    assert [u['unit_id'] for u in units]==[1,2,3,4]

def language_result(original,spec):
    from src.graders.essay_grader import language_units
    from src.schemas import Correction
    base=essay(original,spec).model_dump()
    base['paragraph_count']=len(essay_paragraphs(original))
    base['corrections']=[Correction(section='Body',original='force students giving up cars',
        error='Force somebody to do something requires the infinitive.',suggested='force students to give up cars').model_dump()]
    checks=[{'unit_id':u['unit_id'],'verdict':'issues' if 'force students' in u['text'] else 'clear',
        'correction_indices':[1] if 'force students' in u['text'] else []} for u in language_units(original)]
    return ThoroughFlashResult(**base,language_checks=checks)

def test_language_coverage_and_references_reject_omissions(binding):
    from src.graders.essay_grader import validate_essay
    from src.schemas import LanguageCheck
    original='Introduction with no final period\r\nThey force students giving up cars. Another sentence.'
    result=language_result(original,binding.essays[0])
    assert validate_essay(result,original,binding.essays[0]) is result
    result.language_checks.pop()
    with pytest.raises(ValueError,match='every source segment exactly once'):
        validate_essay(result,original,binding.essays[0])
    result=language_result(original,binding.essays[0])
    result.language_checks[1]=LanguageCheck(unit_id=2,verdict='clear',correction_indices=[])
    with pytest.raises(ValueError,match='Correction lacks'):
        validate_essay(result,original,binding.essays[0])
    result.language_checks[0]=LanguageCheck(unit_id=1,verdict='issues',correction_indices=[1])
    with pytest.raises(ValueError,match='does not match'):
        validate_essay(result,original,binding.essays[0])

def test_thorough_one_pass_schema_replays_and_never_pays_to_repair(binding,settings):
    original='They force students giving up cars. Another sentence.'
    result=language_result(original,binding.essays[0]);calls=[];checkpoints=[]
    class AI:
        def structured(self,model,prompt,schema,attachments):
            calls.append(schema)
            assert not attachments and 'Sentence-final punctuation' in prompt
            assert 'UNTRUSTED SOURCE SEGMENTS' in prompt and 'no repeated quotes' in prompt
            return schema.model_validate(result.model_dump())
    value=grade_essay(AI(),settings,binding.essays[0],original,[],checkpoint=checkpoints.append)
    assert isinstance(value,ThoroughFlashResult)
    assert isinstance(grade_essay(None,settings,binding.essays[0],original,[],pending=checkpoints[-1]),ThoroughFlashResult)
    assert len(calls)==1 and checkpoints[-1]['mode']=='flash-one-pass-v03-language-and-data'
    assert len(checkpoints[-1]['prompt_sha256'])==64
    result.language_checks=[];checkpoints=[]
    with pytest.raises(ValueError,match='every source segment'):
        grade_essay(AI(),settings,binding.essays[0],original,[],checkpoint=checkpoints.append)
    with pytest.raises(ValueError,match='no automatic paid regeneration'):
        grade_essay(None,settings,binding.essays[0],original,[],pending=checkpoints[-1])
    assert len(calls)==2

def test_correct_repeated_top200_references_are_in_task1_reading_guide(binding,settings):
    spec=binding.essays[0].model_copy(update={'task':1,'ground_truth':'Universities in the top 200 in 2011.'})
    original='The table covers the top 200 in 2011.\nOverall, the USA leads the top 200.'
    from src.graders.essay_grader import language_units
    class AI:
        def structured(self,model,prompt,schema,attachments):
            assert schema is ThoroughFlashTask1Result and not attachments
            assert 'Numeric-bearing unit IDs (cover every numeral in ALL these segments): [1, 2]' in prompt
            assert 'EACH repeated ranking/year' in prompt
            base=essay(original,spec).model_dump()
            base['paragraph_count']=len(essay_paragraphs(original))
            return schema(**base,language_checks=[{'unit_id':u['unit_id'],'verdict':'clear','correction_indices':[]} for u in language_units(original)],
                numeric_checks=[{'original_claim':u['text'],'verdict':'accurate','evidence':'Trusted top-200 ranking and year 2011.','correction_quote':''} for u in language_units(original)])
    assert grade_essay(AI(),settings,spec,original,[],checkpoint=lambda _:None).word_count>0

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
