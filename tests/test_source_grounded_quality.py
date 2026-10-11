import json
from types import SimpleNamespace
import pytest
from src.schemas import AuditedProEssayBundle,AuditedBundledEssayFeedback,ComparisonEvidence,NumericEvidence,GeneratedNumericEvidence,AuditedCorrection,LanguageCheck
from src.graders.quality_contract import (chart_matrix,chart_guide,validate_comparisons,
    validate_numeric_evidence,validate_generated_numbers,validate_edit_coverage,QUALITY_CONTRACT)
from src.graders.essay_bundle import grade_bundle,prepare_bundle,verify_saved_quality,PROMPT_VERSION
from src.graders.essay_grader import language_units
from src.parsers import digest
from conftest import essay,FakeDashboard,FakeSheets,FakeDrive
from test_hybrid_bundle import originals,audited

def spec(binding):
    return binding.essays[0].model_copy(update={'task':1,'data_kind':'static',
        'question':'The table shows ratings of three courses in 2011.',
        'ground_truth':'Column order Information / Teaching / Tutor / Printed / Other. Economics=59/95/90/81/60; Law=72/62/76/70/80; Commerce=95/95/93/85/81.'})

def item(binding,original='A full introduction.\nOverview.\nFirst detail.\nFinal detail.'):
    s=spec(binding); data=essay(original,s).model_dump(exclude={'original','word_count','paragraph_count','band_scores'})
    data.update(source_digest=digest(original),numeric_checks=[],comparisons=[],numeric_evidence=[],generated_numbers=[],language_checks=[])
    return AuditedBundledEssayFeedback(**data)

def comparison(quote,scope='table',key='',scope_quote='',targets=None,valid=True,relation='minimum',location='revision:1'):
    return ComparisonEvidence(location=location,quote=quote,relation=relation,scope=scope,scope_key=key,scope_quote=scope_quote,targets=targets or ['r2c2'],valid=valid)

def revision(value,text):
    value.upgraded_paragraphs[0][0].text=text
    return value

def test_verified_legacy_notation_and_json_matrices_match(binding):
    s=spec(binding); matrix=chart_matrix(s); guide=chart_guide(matrix)
    assert guide['global_minimum']==59 and guide['column_stats']['Teaching']=={'minimum':62,'maximum':95,'range':33}
    assert guide['column_stats']['Printed']['range']==15
    s.ground_truth=json.dumps({'columns':matrix['columns'],'rows':{'Economics':[59,95,90,81,60],'Law':[72,62,76,70,80],'Commerce':[95,95,93,85,81]}})
    assert chart_matrix(s)==matrix

def test_unparsed_or_incomplete_trusted_data_not_guessed(binding):
    s=spec(binding);s.ground_truth='The minimum is 59. A chart was attached.'
    with pytest.raises(ValueError,match='structured chart matrix'):chart_matrix(s)
    s.ground_truth='Columns A/B. First=1/2; Second=3/4/5.'
    with pytest.raises(ValueError,match='row width'):chart_matrix(s)
    s.ground_truth='Columns A/B. First=1/2; Second=unknown/4.'
    with pytest.raises(ValueError,match='partial matrix'):chart_matrix(s)

def test_thousands_negative_and_decimal_cells_keep_their_true_values(binding):
    s=spec(binding);s.ground_truth='Columns A/B. First=1,000/20.5; Second=-3/4.'
    matrix=chart_matrix(s)
    assert matrix['cells']['r1c1']['value']==1000 and matrix['cells']['r1c2']['value']==20.5
    assert matrix['cells']['r2c1']['value']==-3

def test_false_global_minimum_and_disguised_column_scope_rejected(binding):
    s=spec(binding); matrix=chart_matrix(s); value=item(binding)
    quote='Law Teaching had the lowest percentage of students.'
    revision(value,quote);value.comparisons=[comparison(quote)]
    with pytest.raises(ValueError,match='arithmetic'):validate_comparisons(value,'Original.',matrix)
    value.comparisons=[comparison(quote,scope='column',key='Teaching',scope_quote='Law Teaching')]
    with pytest.raises(ValueError,match='explicit visible scope'):validate_comparisons(value,'Original.',matrix)

def test_valid_restricted_minimum_tied_global_maximum_and_range(binding):
    matrix=chart_matrix(spec(binding));value=item(binding)
    quote='Law had the lowest percentage for Teaching.'
    revision(value,quote);value.comparisons=[comparison(quote,scope='column',key='Teaching',scope_quote='for Teaching')]
    validate_comparisons(value,'Original.',matrix)
    quote='Economics Teaching and Commerce Teaching had the highest percentages.'
    revision(value,quote);value.comparisons=[comparison(quote,targets=['r1c2','r3c2'],relation='maximum')]
    validate_comparisons(value,'Original.',matrix)
    quote='Printed resources had the smallest disparity.'
    revision(value,quote);value.comparisons=[comparison(quote,scope='column_ranges',targets=['Printed'])]
    validate_comparisons(value,'Original.',matrix)

def test_collocation_example_cannot_hide_invalid_extreme_and_missing_audit(binding):
    matrix=chart_matrix(spec(binding));value=item(binding)
    value.collocations[0].usage_example='Law Teaching had the lowest percentage.'
    with pytest.raises(ValueError,match='lacks source-grounded'):validate_comparisons(value,'Original.',matrix)
    value.comparisons=[comparison(value.collocations[0].usage_example,location='example:1')]
    with pytest.raises(ValueError,match='arithmetic'):validate_comparisons(value,'Original.',matrix)

def universities(binding):
    s=spec(binding);s.question='Universities in the top 200 in 2011.'
    s.ground_truth='Columns Biology/Medicine/Psychology. Australia=9/13/17; Canada=9/12/14; New Zealand=6/2/4.'
    return chart_matrix(s)

def numeric(value,claim,verdict,evidence):
    value.numeric_checks=[{'original_claim':claim,'verdict':verdict,'evidence':'Trusted source cells compared independently.','correction_quote':''}]
    # Assignment to a mutable Pydantic list is intentionally validated here.
    from src.schemas import NumericCheck
    value.numeric_checks=[NumericCheck(**n) for n in value.numeric_checks]
    value.numeric_evidence=[NumericEvidence(check_index=1,kind='cells',cells=evidence[0],operator=evidence[1],value=evidence[2])]

def test_correct_subclaim_not_poisoned_by_other_error_in_same_sentence(binding):
    matrix=universities(binding);value=item(binding)
    claim='compared to 9 Biology universities'
    numeric(value,claim,'ambiguous',(['r1c1','r2c1'],'eq',9))
    original='Australia and Canada had 13 Medicine and 17 Psychology universities, compared to 9 Biology universities.'
    with pytest.raises(ValueError,match='cannot be labelled ambiguous'):validate_numeric_evidence(value,original,matrix)
    value.numeric_checks[0].verdict='accurate';validate_numeric_evidence(value,original,matrix)
    value.numeric_evidence[0].cells=['r1c1']
    with pytest.raises(ValueError,match='omits a group'):validate_numeric_evidence(value,original,matrix)

def test_true_loose_bound_and_false_strict_inequality_are_distinguished(binding):
    value=item(binding);matrix=universities(binding)
    numeric(value,'not surpassing 8 universities each','imprecise',(['r3c1','r3c2','r3c3'],'le',8))
    validate_numeric_evidence(value,'not surpassing 8 universities each',matrix)
    value.numeric_checks[0].verdict='incorrect'
    with pytest.raises(ValueError,match='arithmetic'):validate_numeric_evidence(value,'not surpassing 8 universities each',matrix)
    matrix=chart_matrix(spec(binding));numeric(value,'exceeding 90% across Economics and Commerce','incorrect',(['r1c3','r3c3'],'gt',90))
    validate_numeric_evidence(value,'exceeding 90% across Economics and Commerce',matrix)
    value.numeric_evidence[0].operator='ge'
    with pytest.raises(ValueError,match='operator contradicts'):validate_numeric_evidence(value,'exceeding 90% across Economics and Commerce',matrix)

def test_respectively_unclear_order_is_not_falsely_rejected(binding):
    value=item(binding);matrix=chart_matrix(spec(binding))
    numeric(value,'at 81%, 70% and 85% respectively','ambiguous',(['r1c4'],'eq',81))
    value.numeric_evidence.extend([NumericEvidence(check_index=1,kind='cells',cells=['r2c4'],operator='eq',value=70),NumericEvidence(check_index=1,kind='cells',cells=['r3c4'],operator='eq',value=85)])
    validate_numeric_evidence(value,'The figures for three courses were at 81%, 70% and 85% respectively.',matrix)

def test_missing_numeric_evidence_and_fake_context_rejected(binding):
    value=item(binding);matrix=universities(binding)
    numeric(value,'top 200 in 2011','accurate',(['r1c1'],'eq',200))
    value.numeric_evidence=[NumericEvidence(check_index=1,kind='context',cells=[],operator='eq',value=200)]
    with pytest.raises(ValueError,match='every value'):validate_numeric_evidence(value,'top 200 in 2011',matrix)
    value.numeric_evidence.append(NumericEvidence(check_index=1,kind='context',cells=[],operator='eq',value=2011))
    validate_numeric_evidence(value,'top 200 in 2011',matrix)
    value.numeric_evidence[0].cells=['r1c1']
    with pytest.raises(ValueError,match='Context number'):validate_numeric_evidence(value,'top 200 in 2011',matrix)

def test_capitalization_and_punctuation_need_explicit_annotation(binding):
    value=item(binding);original='The Uk figures were lower.\nFinal sentence without period'
    revision(value,'The UK figures were lower.')
    with pytest.raises(ValueError,match='Capitalization'):validate_edit_coverage(value,original)
    value.corrections=[AuditedCorrection(category='grammar',section='Body',original='Uk',error='Tên viết tắt phải viết hoa UK.',suggested='UK')]
    with pytest.raises(ValueError,match='punctuation'):validate_edit_coverage(value,original)
    value.corrections.append(AuditedCorrection(category='punctuation',section='Body',original='without period',error='Thiếu dấu chấm kết thúc câu.',suggested='without period.'))
    validate_edit_coverage(value,original)
    value.corrections=[];validate_edit_coverage(value,'The sentence ends inside a quotation “correctly.”')

def test_clarity_is_not_an_established_data_error(binding):
    value=item(binding);value.corrections=[AuditedCorrection(category='clarity',section='Overview',original='unclear phrase',error='Gộp nhóm sai dữ liệu.',suggested='clear phrase')]
    with pytest.raises(ValueError,match='falsely asserts'):validate_edit_coverage(value,'An unclear phrase.')
    value.corrections[0].category='data'
    with pytest.raises(ValueError,match='verified incorrect'):validate_edit_coverage(value,'An unclear phrase.')

def test_task2_not_forced_into_chart_scope(binding):
    value=item(binding);revision(value,'This is the greatest risk in this argument.')
    validate_comparisons(value,'Original.',None);validate_numeric_evidence(value,'Original.',None)
    validate_generated_numbers(value,None)

def test_wrong_or_unaudited_revised_number_never_released(binding):
    value=item(binding);matrix=chart_matrix(spec(binding))
    text='Law had a Tutor rating of 62%.';revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote=text,kind='cells',cells=['r2c3'],operator='eq',value=62)]
    with pytest.raises(ValueError,match='arithmetic'):validate_generated_numbers(value,matrix)
    value.generated_numbers=[]
    with pytest.raises(ValueError,match='lacks verified'):validate_generated_numbers(value,matrix)
    text='Law had a Tutor rating of 76%.';revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote=text,kind='cells',cells=['r2c3'],operator='eq',value=76)]
    validate_generated_numbers(value,matrix)
    text='Economics and Commerce Tutor ratings exceeded 90%.';revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote=text,kind='cells',cells=['r1c3','r3c3'],operator='ge',value=90)]
    with pytest.raises(ValueError,match='operator contradicts'):validate_generated_numbers(value,matrix)
    value.generated_numbers[0].operator='gt'
    with pytest.raises(ValueError,match='arithmetic'):validate_generated_numbers(value,matrix)
    text='Economics and Commerce Tutor ratings were 90% or above.';revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote=text,kind='cells',cells=['r1c3','r3c3'],operator='ge',value=90)]
    validate_generated_numbers(value,matrix)

def test_generated_number_cannot_misuse_year_as_university_count(binding):
    value=item(binding);matrix=universities(binding)
    text='Canada had 2011 Biology universities.';revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote=text,kind='context',cells=[],operator='eq',value=2011)]
    with pytest.raises(ValueError,match='year/ranking'):validate_generated_numbers(value,matrix)
    text='The top 200 universities were surveyed in 2011.';revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote=text,kind='context',cells=[],operator='eq',value=n) for n in (200,2011)]
    validate_generated_numbers(value,matrix)

def test_new_prompt_source_guide_and_historical_replay_remain_separate(binding):
    specs,texts,response=originals(binding)
    prompt,_=prepare_bundle(specs,texts)
    assert QUALITY_CONTRACT in prompt and 'TRUSTED CHART MATRICES' in prompt
    pending={'model':'gemini-3.1-pro-preview','mode':'hybrid-two-essays-v03-complete-and-scoped-review',
        'status':'validated','source_digest':prepare_bundle(specs,texts,audited=False)[1],'result':response.model_dump()}
    assert len(grade_bundle(None,SimpleNamespace(essay_model='gemini-3.1-pro-preview'),specs,texts,lambda _:None,pending))==2

def test_bad_quality_is_held_and_never_regenerated(binding):
    specs,texts,response=originals(binding);response=audited(response)
    response.essays[0].upgraded_paragraphs[0][0].text='The USA is the highest.'+' learning'*260
    # Task2 does not acquire chart rules, but an unpunctuated intro still requires feedback.
    texts['1']='Original intro without a full stop';response.essays[0].source_digest=digest(texts['1'])
    response.essays[0].language_checks=[LanguageCheck(unit_id=1,verdict='clear',correction_indices=[])]
    calls=[];work=[]
    def generate(*args):calls.append(args);return response
    with pytest.raises(ValueError,match='punctuation'):
        grade_bundle(SimpleNamespace(structured=generate),SimpleNamespace(essay_model='gemini-3.1-pro-preview'),specs,texts,work.append)
    assert len(calls)==1 and work[-1]['status']=='held' and 'result' in work[-1]
    with pytest.raises(ValueError,match='no automatic paid regeneration'):
        grade_bundle(None,SimpleNamespace(essay_model='gemini-3.1-pro-preview'),specs,texts,work.append,work[-1])

def test_delivery_cannot_bypass_checked_payload(binding):
    specs,texts,response=originals(binding);response=audited(response);work=[]
    results=grade_bundle(SimpleNamespace(structured=lambda *_:response),SimpleNamespace(essay_model='gemini-3.1-pro-preview'),specs,texts,work.append)
    state={'bundle_work':work[-1],'source':{'essay_texts':texts},'payload':{'essays':[r.model_dump(mode='json') for r in results]}}
    b=binding.model_copy(update={'essays':specs})
    verify_saved_quality(state,b)
    state['payload']['essays'][0]['summary_vi']='Replaced unchecked feedback.'
    with pytest.raises(ValueError,match='Delivery differs'):verify_saved_quality(state,b)
    state['bundle_work']['mode']='unknown-contract'
    with pytest.raises(ValueError,match='Unknown delivery'):verify_saved_quality(state,b)
