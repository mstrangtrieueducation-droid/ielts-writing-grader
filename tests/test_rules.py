from datetime import datetime
import pytest
from pydantic import ValidationError
from src.parsers import parse_filename, match_student, parse_receipt, drive_ids, word_count
from src.policy import receipt_allowed, eligible_binding, check_suppression
from src.sheet_service import replace_comment
from src.graders.copy_grader import validate_check
from src.graders.essay_grader import validate_essay
from src.schemas import Correction
from conftest import notebook, essay

def test_filename_and_exact_identity():
    assert parse_filename('IELTS49_Nguyen Thu Hang_W27.pdf')==('IELTS 49','Nguyen Thu Hang','W27')
    assert parse_filename('IELTS 49_Nguyễn_Thu_Hằng_TEST4.pdf')[1]=='Nguyễn Thu Hằng'
    with pytest.raises(ValueError): parse_filename('scan.pdf')
    roster=[{'name':'Nguyễn Vũ Bảo Châu','id':'1'}]
    assert match_student('Bảo Châu',roster,{'Bảo Châu':'Nguyễn Vũ Bảo Châu'})['id']=='1'
    with pytest.raises(ValueError): match_student('Châu',roster,{})

def test_receipt_boundary_is_not_grading_deadline(binding):
    assert receipt_allowed(binding,parse_receipt('09/10/2026 23:59:59'))
    assert not receipt_allowed(binding,parse_receipt('10/10/2026 00:00:00'))
    assert not receipt_allowed(binding,parse_receipt('2026-10-09T17:00:00Z'))
    archived=binding.model_copy(update={'next_writing_date':datetime(2026,9,29).date()})
    assert not receipt_allowed(archived,parse_receipt('28/09/2026 12:00:00'))

def test_lesson_exclusions(binding):
    assert not eligible_binding(binding.model_copy(update={'lesson':21}))
    assert not eligible_binding(binding.model_copy(update={'lesson':39}))
    assert not eligible_binding(binding.model_copy(update={'lesson':1}))
    assert eligible_binding(binding.model_copy(update={'lesson':1,'early_lesson_authorized':True}))
    with pytest.raises(ValidationError): type(binding).model_validate({**binding.model_dump(),'lesson':6})

def test_comment_preserves_manual_and_receipt():
    old='✅ ĐÃ NỘP\nCô ghi riêng.\n【KẾT QUẢ CHẤM WRITING】\nold\n【HẾT KẾT QUẢ CHẤM】\nGhi chú sau.'
    block='【KẾT QUẢ CHẤM WRITING】\nnew\n【HẾT KẾT QUẢ CHẤM】'
    assert replace_comment(old,block)=='✅ ĐÃ NỘP\nCô ghi riêng.\n'+block+'\nGhi chú sau.'
    with pytest.raises(ValueError): replace_comment(old+old,block)

def test_all_pages_and_actual_item_evidence(binding):
    result=notebook()
    validate_check(result,binding.notebook_requirements,{'notebook_file_123':1})
    with pytest.raises(ValueError): validate_check(result,binding.notebook_requirements,{'notebook_file_123':2})
    result.items[0].pages=[]
    with pytest.raises(ValueError): validate_check(result,binding.notebook_requirements,{'notebook_file_123':1})

def test_fabricated_correction_rejected(binding):
    original=' '.join(['word']*260)
    result=essay(original,binding.essays[0])
    result.corrections=[Correction(section='Body',original='fabricated quote',error='lỗi không có trong nguồn',suggested='new sentence')]
    with pytest.raises(ValueError): validate_essay(result,original,binding.essays[0])

def test_deterministic_words_and_gate():
    assert word_count("don't well-known 999,963") == 4
    with pytest.raises(ValueError): check_suppression({'state':'too_late','essays':[{}]})
    assert drive_ids('https://drive.google.com/file/d/abcdefghijk/view, abcdefghijk')==['abcdefghijk']
