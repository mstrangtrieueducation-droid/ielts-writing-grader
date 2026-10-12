import pytest
from types import SimpleNamespace as N
from src.graders.economy_plan import *

def test_pair_preserves_both_essays_and_rules_but_omits_models():
    specs=[N(exercise=i,task=1,question='Table',ground_truth='A=1') for i in [1,2]]
    context={'content':'Required theory\nVERBATIM TEACHER WORKED MODEL\nLong model'}
    row=pro_request('test',specs,{'1':'Essay one.','2':'Essay two.'},context)
    text=row['request']['contents'][0]['parts'][0]['text']
    assert all(s in text for s in ['Required theory','Essay one.','Essay two.','A=1'])
    assert 'Long model' not in text
    assert row['request']['generationConfig']['maxOutputTokens']==800
    images=[{'file_uri':str(i),'mime_type':'image/jpeg'} for i in range(5)]
    f=flash_request('test',images,{'a':'handwritten model'})
    assert len(f['request']['contents'][0]['parts'])==6
    assert f['request']['generationConfig']['maxOutputTokens']==99
    with pytest.raises(ValueError):flash_request('test',images+[images[0]],{})

def test_short_output_rejects_truncation_fabricated_quotes_and_duplicate_scores():
    value={'scores':[{'exercise':i,'estimated_band':5,'note_vi':'Ước lượng'} for i in [1,2]],
           'corrections':[{'exercise':1,'original':'wrong','corrected':'right','reason_vi':'Lỗi thật'}]}
    validate_pro_result(value,{'1':'wrong','2':'Second essay'},'STOP')
    with pytest.raises(ValueError):validate_pro_result(value,{'1':'wrong','2':'Second essay'},'MAX_TOKENS')
    with pytest.raises(ValueError):validate_pro_result(value,{'1':'Other source','2':'Second essay'},'STOP')
    assert bounded_cost('gemini-3.1-pro-preview',10000,800,'batch')<500
    assert ensure_budget([3500]*21,[1705]*19)<25000
    with pytest.raises(ValueError):ensure_budget([3500]*21,[10000])
    with pytest.raises(ValueError):ensure_budget([100000]*21,[1705]*19)
    with pytest.raises(ValueError):validate_notebook_result({'state':'complete','missing_groups':['model'],'unreadable_pages':[]},['model'],'STOP')
