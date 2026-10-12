import pytest
from types import SimpleNamespace as N
from src.graders.balanced_plan import pro_request,validate_response

def test_balanced_keeps_theory_and_full_corrections_without_arbitrary_four_error_limit():
    specs=[N(exercise=i,task=1,question='Table',ground_truth='A=1',minimum_words=150) for i in [1,2]]
    row=pro_request('test',specs,{'1':'Source one.','2':'Source two.'},{'content':'Taught theory\nVERBATIM TEACHER WORKED MODEL\nOld model'})
    r=row['request'];assert r['generationConfig']['maxOutputTokens']==5200
    schema=r['generationConfig']['responseJsonSchema']
    assert 'maxItems' not in schema['$defs']['CompleteShortEssay']['properties']['corrections']
    text=r['contents'][0]['parts'][0]['text']
    assert 'Taught theory' in text and 'Old model' not in text
    value={'essays':[{'exercise':i,'estimated_band':5,'summary_vi':'Nhận xét','taught_application_vi':'Áp dụng bài học',
        'corrections':[{'section':'Detail','original':'Source','error':'Lỗi','suggested':'Correct'} for _ in range(6)],
        'revised_paragraphs':[' '.join(['word']*40) for _ in range(4)]} for i in [1,2]]}
    assert len(validate_response(value,{'1':'Source one.','2':'Source two.'},{1:150,2:150},'STOP').essays[0].corrections)==6
    with pytest.raises(ValueError):validate_response(value,{'1':'Source one.','2':'Source two.'},{1:150,2:150},'MAX_TOKENS')
