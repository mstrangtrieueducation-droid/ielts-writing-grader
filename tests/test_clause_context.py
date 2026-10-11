import pytest
from src.schemas import NumericEvidence,GeneratedNumericEvidence
from src.graders.quality_contract import (chart_matrix,validate_comparisons,validate_numeric_evidence,
    validate_generated_numbers,strict_boundary_facts,mentions)
from test_source_grounded_quality import spec,item,revision,comparison,numeric,universities

def test_scope_prefix_in_same_clause_is_valid(binding):
    value=item(binding);matrix=chart_matrix(spec(binding))
    revision(value,'Regarding Teaching, Law had the lowest percentage.')
    value.comparisons=[comparison('Law had the lowest percentage',scope='column',key='Teaching',scope_quote='Regarding Teaching')]
    validate_comparisons(value,'Original.',matrix)

@pytest.mark.parametrize('text',['Regarding Teaching, Commerce scored well. Law had the lowest percentage.',
    'Regarding Teaching, Commerce scored well, whereas Law had the lowest percentage.'])
def test_scope_cannot_be_borrowed_from_unquoted_other_clause(binding,text):
    value=item(binding);matrix=chart_matrix(spec(binding));revision(value,text)
    value.comparisons=[comparison('Law had the lowest percentage',scope='column',key='Teaching',scope_quote='Regarding Teaching')]
    with pytest.raises(ValueError,match='explicit visible scope'):validate_comparisons(value,'Original.',matrix)

def test_two_values_respectively_are_not_shared_by_both_rows(binding):
    value=item(binding);matrix=universities(binding)
    text='Australia and Canada had 13 and 12 Medicine universities, respectively.'
    # Values adjacent to respectively are deliberately explicit in this format.
    text='For Medicine, Australia and Canada recorded 13 and 12, respectively.'
    numeric(value,text,'accurate',(['r1c2'],'eq',13))
    value.numeric_evidence.append(NumericEvidence(check_index=1,kind='cells',cells=['r2c2'],operator='eq',value=12))
    validate_numeric_evidence(value,text,matrix)
    revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote=text,kind='cells',cells=e.cells,operator='eq',value=e.value) for e in value.numeric_evidence]
    validate_generated_numbers(value,matrix)
    value.numeric_evidence[0].cells=['r2c2']
    with pytest.raises(ValueError):validate_numeric_evidence(value,text,matrix)

def test_multi_subject_respectively_does_not_hide_wrong_shared_country_numbers(binding):
    value=item(binding);matrix=universities(binding)
    text='Australia and Canada had Medicine and Psychology counts of 13 and 17, respectively.'
    numeric(value,text,'accurate',(['r1c2'],'eq',13))
    value.numeric_evidence.append(NumericEvidence(check_index=1,kind='cells',cells=['r1c3'],operator='eq',value=17))
    with pytest.raises(ValueError,match='omits a group'):validate_numeric_evidence(value,text,matrix)

def test_numeric_quote_can_use_its_own_clause_category(binding):
    value=item(binding);matrix=universities(binding)
    text='Regarding Medicine, Australia recorded 13 universities.';revision(value,text)
    value.generated_numbers=[GeneratedNumericEvidence(location='revision:1',quote='Australia recorded 13 universities',kind='cells',cells=['r1c2'],operator='eq',value=13)]
    validate_generated_numbers(value,matrix)
    revision(value,'Regarding Medicine, Canada recorded 12 universities. Australia recorded 13 universities.')
    with pytest.raises(ValueError,match='association'):validate_generated_numbers(value,matrix)

def test_computed_boundary_facts_are_matrix_based_not_student_or_class_based(binding):
    s=spec(binding);s.ground_truth='Columns Tutors/Other. Alpha=40/70; Beta=43/71.'
    facts=strict_boundary_facts('Tutors exceed 40 for both groups; Other exceeds 70 for both.',chart_matrix(s))
    assert [f['threshold'] for f in facts]==[40,70]
    assert facts[0]['equal_cells']['r1c1']['row']=='Alpha'
    assert facts[1]['equal_cells']['r1c2']['value']==70
    assert strict_boundary_facts('A Task2 essay.',None)==[]

def test_normal_inflections_and_country_alias_do_not_make_fake_missing_context():
    assert mentions('In terms of tutoring','Tutor')
    assert mentions('for the United Kingdom','UK')
    assert not mentions('for Ukraine','UK')
