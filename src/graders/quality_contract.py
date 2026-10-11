"""Source-grounded acceptance checks, without another model call or feedback edits.

The model identifies claims; arithmetic is recomputed locally from a trusted matrix.
Unparsed sources, missing evidence and contradictions are held, never regenerated.
This supplements, rather than replaces, independent pedagogical review.
"""
import json
import math
import re
from operator import eq, gt, ge, lt, le

CONTRACT_VERSION='source-grounded-quality-v01'
QUALITY_CONTRACT='''Before emitting the SAME response, audit the final feedback, not just the original.
Classify each correction: grammar/data/clarity/punctuation/register/optional. Ambiguous attachment,
reference or group order is clarity, not an established numerical/grammar error. If one reasonable
reading is correct, explain how to make it explicit; do not assert the student definitely meant the
wrong reading. Keep optional refinements separate from actual errors.
Use the TRUSTED CHART MATRIX and precomputed extrema/ranges. For every minimum/maximum claim
in your suggestions, revision and collocation examples, return comparisons with an exact quote,
location (revision:1..4, suggestion:1..N, example:1..N), relation minimum/maximum, scope, scope_key,
targets, scope_quote and valid. Cell IDs are r1c1 etc. table/row/column target cell IDs;
row_ranges/column_ranges target row/column labels; row_dominance targets row labels.
Within-row/column claims MUST visibly say for/in/among/within/across the named scope; a category
merely appearing in the subject does not restrict the comparison. scope_quote must quote that
restricting phrase. A row_dominance claim explicitly covers all shown subjects/categories.
Range means max minus min, not a minimum individual value. No unsupported sum of unique entities.
Comparing SEPARATE subject totals across verified disjoint countries is different from adding
subjects together to claim unique universities. Overlap BETWEEN subjects does not invalidate the
first comparison. Never invent a ban on addition or require a different overview only because
another accurate overview is possible. Read the whole table context before labelling global scope
wrong; an unclear scope calls for clarification, not a false data-error accusation.
When the trusted source explicitly authorizes additive counts across disjoint rows, column_totals
provides computed totals. column_totals comparison targets are column labels, scope_key is empty,
and scope_quote must visibly include the trusted aggregation_scope_label. Do not infer permission
to sum percentages, overlapping groups or unique entities. Do not introduce aggregate numerals in
rewrites: the current numerical schema audits individual cells, not aggregate values.
row_dominance targets are ROW LABELS (never cell IDs), and scope_key is empty. table scope_key
and scope_quote are empty. Return evidence for EVERY extreme, including collocation examples.
Write self-contained suggestions/examples with named subjects and comparison scope; references
such as 'its course' must not replace the named scope in evidence. Do not use generic superlative
examples unless their scope is verifiable. Before finalizing, list every real change between the
original and revision and ensure the explanation covers it, including paragraph-final full stops,
proper-name capitalization, surveyed versus examined and who awards/receives a rating.
All generated claims must be valid. Original incorrect extrema may be evidenced at location original
with valid=false; this is required to support a data correction without numerals. Do not declare
an ambiguous original definitively false by selecting only its least favourable interpretation.
Return numeric_evidence for each numeric_check: check_index (1-based), kind cells/context, cells,
operator eq/gt/ge/lt/le, value. Use one item per asserted value; a wrong group attribution uses ALL
groups asserted for that value. Context is only for trusted question numbers (year/ranking), no cells.
The program will recompute inequalities and exact values. A correct value for explicitly identified
groups is accurate even if another value in the sentence is wrong: isolate claims. Loose true bounds
may be imprecise but never incorrect. Correct values with unclear group order may be ambiguous.
Return generated_numbers for EVERY numeral in ALL suggestions, revision paragraphs and collocation
examples, with location, exact quote, kind cells/context, cells, operator, value. Quote enough context
to identify each referenced row AND column unambiguously. All these generated assertions must be
true against the trusted matrix; a correctly detected original error does not excuse a wrong rewrite.
Context numbers may only be a stated top-ranking limit or a year actually given in the question;
never label a wrong university count as a context number merely because it equals a year/ranking.
Do not fix a real error only in the revision: include its source quote and explanation. In particular
check abbreviations/proper-country capitalization and paragraph-final punctuation. Check suggestions,
revision and collocation examples AGAIN within this response: none may retain/create a data error.
For Task2 comparisons, numeric_evidence and generated_numbers are empty; do not impose chart rules.
Evidence arrays are private checks, never system narration in student-facing feedback.
'''

NUMBER=r'[-+]?\d+(?:,\d{3})*(?:\.\d+)?'
EXTREME=re.compile(r'\b(?:highest|lowest|largest|smallest|greatest|least|most\s+(?:favou?red|popular|appealing))\b',re.I)

def numbers(text):
    if re.search(r'\d,\d{1,2}(?!\d)',text):
        raise ValueError('Ambiguous decimal/list comma requires verified numeric notation')
    return [float(m.group().replace(',','')) for m in re.finditer(NUMBER,text)]

def quoted_operator(text,value):
    patterns=((r'\b(?:not exceed(?:s|ed|ing)?|not surpass(?:es|ed|ing)?|no more than)\s*'+NUMBER,'le'),
        (r'\b(?:at least|no less than|no fewer than)\s*'+NUMBER,'ge'),
        (r'\b(?:exceed(?:s|ed|ing)?|over|more than|above|greater than)\s*'+NUMBER,'gt'),
        (r'\b(?:below|less than|fewer than|under)\s*'+NUMBER,'lt'),
        (NUMBER+r'\s*%?\s*(?:or|and)\s*(?:above|higher|more)\b','ge'),
        (NUMBER+r'\s*%?\s*(?:or|and)\s*(?:below|lower|less)\b','le'))
    for pattern,op in patterns:
        if any(numbers(m.group())[-1]==value for m in re.finditer(pattern,text,re.I)):return op
    return 'eq'

def named_rows(text,matrix):
    def position(label):
        offset=text.casefold().find(label.casefold().rstrip('s'))
        return offset if offset>=0 else len(text)
    return sorted((r for r in matrix['rows'] if mentions(text,r)),key=position)

def chart_matrix(spec):
    """Compile only an explicit matrix, never infer cells from narrative/scan/OCR.

    Source authors can supply JSON {columns:[...],rows:{label:[values...]}}.
    The already verified legacy notation Columns X/Y; A=1/2; B=3/4 also works.
    """
    if spec.task!=1:
        return None
    text=spec.ground_truth.strip()
    if text.startswith('{'):
        try: matrix=json.loads(text)
        except json.JSONDecodeError as exc:raise ValueError('Trusted chart matrix JSON is invalid') from exc
        if set(matrix)!= {'columns','rows'}:
            raise ValueError('Trusted chart matrix requires exact columns and rows')
        columns=matrix['columns']; rows=matrix['rows']
    else:
        header=re.search(r'\bColumns?\s+(?:order\s+)?([^.;]+)[.;]',text,re.I)
        if not header:
            raise ValueError('Verified structured chart matrix required before new grading')
        columns=[c.strip() for c in header.group(1).split('/')]
        rows={}
        candidates=list(re.finditer(r'(?:^|[.;])\s*([\w ()-]+?)\s*=',text))
        parsed=list(re.finditer(r'(?:^|[.;])\s*([\w ()-]+?)\s*=\s*('+NUMBER+r'(?:\s*/\s*'+NUMBER+r')+)\s*(?=[.;]|$)',text))
        if len(candidates)!=len(parsed):
            raise ValueError('Unparsed trusted chart row; never accept a partial matrix')
        for match in parsed:
            name=match.group(1).strip()
            if name in rows:raise ValueError('Duplicate trusted chart row')
            rows[name]=numbers(match.group(2))
    if not isinstance(columns,list) or not columns or any(not isinstance(c,str) or not c.strip() for c in columns) or len(set(c.casefold() for c in columns))!=len(columns):
        raise ValueError('Trusted chart columns are missing or ambiguous')
    if not isinstance(rows,dict) or not rows or len({r.casefold() for r in rows})!=len(rows):
        raise ValueError('Trusted chart rows are missing or ambiguous')
    cells={}
    for ri,(row,values) in enumerate(rows.items(),1):
        if not isinstance(row,str) or not row.strip() or not isinstance(values,list) or len(values)!=len(columns):
            raise ValueError('Trusted chart row width differs from columns')
        for ci,(column,value) in enumerate(zip(columns,values),1):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('Trusted chart cell must be a finite number')
            cells[f'r{ri}c{ci}']={'row':row,'column':column,'value':value}
    matrix={'columns':columns,'rows':list(rows),'cells':cells,
            'context_numbers':sorted(set(numbers(spec.question)))}
    if spec.column_total_policy=='additive_counts_across_disjoint_rows':
        if not spec.aggregation_scope_label.strip():
            raise ValueError('Verified aggregation requires a visible source scope label')
        matrix['aggregation_scope_label']=spec.aggregation_scope_label
        matrix['column_totals']={col:sum(c['value'] for c in cells.values() if c['column']==col) for col in columns}
    return matrix

def chart_guide(matrix):
    if matrix is None:return None
    cells=matrix['cells']; out={**matrix,'global_minimum':min(c['value'] for c in cells.values()),
        'global_maximum':max(c['value'] for c in cells.values()),'column_stats':{},'row_stats':{}}
    for axis in ('column','row'):
        for label in matrix['columns' if axis=='column' else 'rows']:
            values=[c['value'] for c in cells.values() if c[axis]==label]
            out[axis+'_stats'][label]={'minimum':min(values),'maximum':max(values),'range':max(values)-min(values)}
    return out

def generated_texts(item):
    out={f'revision:{i}':''.join(s.text for s in p) for i,p in enumerate(item.upgraded_paragraphs,1)}
    out.update({f'suggestion:{i}':c.suggested for i,c in enumerate(item.corrections,1)})
    out.update({f'example:{i}':c.usage_example for i,c in enumerate(item.collocations,1)})
    return out

def mentions(text,label):
    words=re.findall(r'\w+',label.casefold())
    # Ordinary inflections do not change a table category (Tutor/tutors, print/printed).
    def pattern(word):
        if word=='print':return r'print(?:ed)?'
        if word.endswith('s') and len(word)>3:return re.escape(word[:-1])+r's?'
        return re.escape(word)+r's?'
    return bool(words) and all(re.search(r'\b'+pattern(w)+r'\b',text,re.I) for w in words)

def validate_comparisons(item,original,matrix):
    if matrix is None:
        if item.comparisons:raise ValueError('Task2 must not acquire chart comparison evidence')
        return
    texts=generated_texts(item);texts['original']=original
    covered={k:[] for k in texts}
    for check in item.comparisons:
        text=texts.get(check.location)
        if text is None or check.quote not in text or not EXTREME.search(check.quote):
            raise ValueError('Comparison evidence quote/location is absent or not an extreme claim')
        if check.location!='original' and not check.valid:
            raise ValueError('Generated feedback contains an invalid comparison')
        if not matrix:raise ValueError('Task2 must not acquire chart comparison evidence')
        cells=matrix['cells']; extreme=min if check.relation=='minimum' else max
        if len(set(check.targets))!=len(check.targets):raise ValueError('Comparison targets duplicate')
        if check.scope in ('table','row','column'):
            if not set(check.targets)<=set(cells):raise ValueError('Unknown comparison cell ID')
            if check.scope=='table':
                if check.scope_key or check.scope_quote:raise ValueError('Whole-table scope cannot hide a restricted scope')
                group=list(cells.values())
            else:
                labels=matrix['rows' if check.scope=='row' else 'columns']
                if check.scope_key not in labels:raise ValueError('Unknown comparison scope')
                if not check.scope_quote or check.scope_quote not in check.quote or not mentions(check.scope_quote,check.scope_key) or not re.search(r'\b(?:for|in|among|within|across)\b',check.scope_quote,re.I):
                    raise ValueError('Restricted comparison lacks an explicit visible scope')
                group=[c for c in cells.values() if c[check.scope]==check.scope_key]
                if any(cells[t][check.scope]!=check.scope_key for t in check.targets):raise ValueError('Comparison target lies outside scope')
            expected=extreme(c['value'] for c in group)
            actual=all(cells[t]['value']==expected for t in check.targets)
            if any(not mentions(check.quote,cells[t]['row']) or not mentions(check.quote,cells[t]['column']) for t in check.targets):
                raise ValueError('Comparison quote does not identify its targets')
        elif check.scope in ('row_ranges','column_ranges'):
            axis='row' if check.scope=='row_ranges' else 'column';labels=matrix['rows' if axis=='row' else 'columns']
            if check.scope_key or not set(check.targets)<=set(labels) or not re.search(r'\b(?:range|disparity|difference|gap|spread)\b',check.quote,re.I):
                raise ValueError('Range comparison must identify a real range')
            ranges={k:max(c['value'] for c in cells.values() if c[axis]==k)-min(c['value'] for c in cells.values() if c[axis]==k) for k in labels}
            actual=all(ranges[t]==extreme(ranges.values()) for t in check.targets)
            if any(not mentions(check.quote,t) for t in check.targets):raise ValueError('Range quote lacks its category')
        elif check.scope=='column_totals':
            totals=matrix.get('column_totals')
            label=matrix.get('aggregation_scope_label','')
            if not totals or check.scope_key or not set(check.targets)<=set(totals):
                raise ValueError('Column totals require source-verified additive counts')
            if (not check.scope_quote or check.scope_quote not in check.quote
                or label.casefold() not in check.scope_quote.casefold()
                or not re.search(r'\btotal\b',check.quote,re.I)
                or any(not mentions(check.quote,t) for t in check.targets)):
                raise ValueError('Total comparison lacks its explicit aggregation scope')
            actual=all(totals[t]==extreme(totals.values()) for t in check.targets)
        else:
            if check.scope_key or not set(check.targets)<=set(matrix['rows']):raise ValueError('Unknown dominance target')
            if not check.scope_quote or check.scope_quote not in check.quote or not re.search(r'\b(?:all|each|every|across)\b',check.scope_quote,re.I) or not re.search(r'\b(?:categories|subjects|disciplines|columns|fields)\b',check.scope_quote,re.I):
                raise ValueError('Row dominance requires visible across-category scope')
            actual=all(all(c['value']==extreme(x['value'] for x in cells.values() if x['column']==c['column']) for c in cells.values() if c['row']==t) for t in check.targets)
            if any(not mentions(check.quote,t) for t in check.targets):raise ValueError('Dominance quote lacks its row')
        if actual!=check.valid:raise ValueError('Comparison verdict contradicts trusted chart arithmetic')
        covered[check.location].extend(m.span() for m in re.finditer(re.escape(check.quote),text))
    for location,text in texts.items():
        if location=='original':continue
        if any(not any(a<=m.start() and m.end()<=b for a,b in covered[location]) for m in EXTREME.finditer(text)):
            raise ValueError('Generated extreme claim lacks source-grounded comparison evidence')

def validate_numeric_evidence(item,original,matrix):
    if matrix is None:
        if item.numeric_evidence:raise ValueError('Task2 must not acquire numerical cell evidence')
        return
    checks=item.numeric_checks; linked={i:[] for i in range(1,len(checks)+1)}
    for evidence in item.numeric_evidence:
        if evidence.check_index not in linked:raise ValueError('Numeric evidence references absent check')
        check=checks[evidence.check_index-1]
        if evidence.value not in numbers(check.original_claim):raise ValueError('Numeric evidence value absent from original claim')
        if evidence.kind=='context':
            if evidence.cells or evidence.operator!='eq' or evidence.value not in matrix['context_numbers']:
                raise ValueError('Context number is not verified by the question')
            truth=True
        else:
            if not evidence.cells or len(set(evidence.cells))!=len(evidence.cells) or not set(evidence.cells)<=set(matrix['cells']):
                raise ValueError('Numeric evidence references absent or duplicate chart cells')
            contexts=[u for u in re.split(r'(?<=[.!?])\s+|\n|\b(?:while|whereas|however)\b',original,flags=re.I) if check.original_claim in u]
            if len(contexts)==1:
                named=named_rows(contexts[0],matrix)
                for left,right in zip(named,named[1:]):
                    pair=r'\b'+re.escape(left)+r'\s*(?:,\s*)?(?:and|&)\s+'+re.escape(right)+r'\b'
                    if re.search(pair,contexts[0],re.I) and not {left,right}<={matrix['cells'][cid]['row'] for cid in evidence.cells}:
                        raise ValueError('Numeric evidence omits a group explicitly sharing the claim')
            if quoted_operator(check.original_claim,evidence.value)!=evidence.operator:
                raise ValueError('Numeric operator contradicts the original comparison')
            truth=all({'eq':eq,'gt':gt,'ge':ge,'lt':lt,'le':le}[evidence.operator](matrix['cells'][cid]['value'],evidence.value) for cid in evidence.cells)
        linked[evidence.check_index].append((evidence,truth))
    for index,assertions in linked.items():
        check=checks[index-1]
        if set(numbers(check.original_claim))!={e.value for e,_ in assertions}:
            raise ValueError('Numeric evidence does not cover every value in its claim')
        valid=all(t for _,t in assertions)
        if (check.verdict=='incorrect')==valid:raise ValueError('Numeric verdict contradicts trusted chart arithmetic')
        if check.verdict=='ambiguous':
            units=[u for u in re.split(r'(?<=[.!?])\s+|\n',original) if check.original_claim in u]
            if len(units)==1 and all(e.kind=='cells' and e.operator=='eq' and all(mentions(units[0],matrix['cells'][cid]['row']) and mentions(units[0],matrix['cells'][cid]['column']) for cid in e.cells) for e,_ in assertions):
                raise ValueError('Explicitly identified correct values cannot be labelled ambiguous')

def validate_generated_numbers(item,matrix):
    if matrix is None:
        if item.generated_numbers:raise ValueError('Task2 must not acquire generated chart evidence')
        return
    texts=generated_texts(item);covered={k:[] for k in texts}
    for evidence in item.generated_numbers:
        text=texts.get(evidence.location)
        if text is None or evidence.quote not in text or evidence.value not in numbers(evidence.quote):
            raise ValueError('Generated numeric evidence quote/value is absent')
        if evidence.kind=='context':
            number=re.escape(str(int(evidence.value))) if evidence.value.is_integer() else re.escape(str(evidence.value))
            if evidence.cells or evidence.operator!='eq' or evidence.value not in matrix['context_numbers'] or not re.search(r'\b(?:top|in|for|during|year)\s*'+number+r'\b',evidence.quote,re.I):
                raise ValueError('Generated context number lacks a verified year/ranking reference')
            if re.search(r'\b(?:in|for|during|year)\s*'+number+r'\b',evidence.quote,re.I) and not 1000<=evidence.value<=9999:
                raise ValueError('Generated year reference is not a year')
        else:
            if not evidence.cells or len(set(evidence.cells))!=len(evidence.cells) or not set(evidence.cells)<=set(matrix['cells']):
                raise ValueError('Generated numeric evidence lacks real chart cells')
            refs=[matrix['cells'][cid] for cid in evidence.cells]
            if quoted_operator(evidence.quote,evidence.value)!=evidence.operator:
                raise ValueError('Generated numeric operator contradicts the written assertion')
            if not all(mentions(evidence.quote,c['row']) and mentions(evidence.quote,c['column']) for c in refs):
                raise ValueError('Generated number lacks an explicit row/category association')
            if not all({'eq':eq,'gt':gt,'ge':ge,'lt':lt,'le':le}[evidence.operator](c['value'],evidence.value) for c in refs):
                raise ValueError('Generated number contradicts trusted chart arithmetic')
            named=named_rows(evidence.quote,matrix)
            for left,right in zip(named,named[1:]):
                if re.search(r'\b'+re.escape(left)+r'\s*(?:,\s*)?(?:and|&)\s+'+re.escape(right)+r'\b',evidence.quote,re.I) and not {left,right}<={c['row'] for c in refs}:
                    raise ValueError('Generated numeric evidence omits a grouped row')
        for match in re.finditer(re.escape(evidence.quote),text):
            covered[evidence.location].extend((match.start()+n.start(),match.start()+n.end()) for n in re.finditer(NUMBER,evidence.quote) if float(n.group().replace(',',''))==evidence.value)
    for location,text in texts.items():
        if any(m.span() not in covered[location] for m in re.finditer(NUMBER,text)):
            raise ValueError('Generated numeral lacks verified source evidence')

def validate_edit_coverage(item,original):
    revision='\n'.join(generated_texts(item)[f'revision:{i}'] for i in range(1,5))
    for token in re.findall(r'\b[A-Za-z]{2,5}\b',original):
        if token!=token.upper() and re.search(r'\b'+re.escape(token.upper())+r'\b',revision):
            if not any(re.search(r'\b'+re.escape(token)+r'\b',c.original) and re.search(r'\b'+re.escape(token.upper())+r'\b',c.suggested) for c in item.corrections):
                raise ValueError('Capitalization error silently fixed only in revision')
    from ..parsers import essay_paragraphs
    for paragraph in essay_paragraphs(original):
        if paragraph.rstrip().rstrip('\"\'’”)]}').endswith(('.', '!', '?')):continue
        tail=paragraph.rstrip().split()[-1]
        if not any(tail in c.original and re.search(r'dấu chấm|chấm câu|kết thúc câu|punctuation|period|full stop',c.error,re.I) for c in item.corrections):
            raise ValueError('Paragraph-final punctuation lacks an explicit correction')
    for index,c in enumerate(item.corrections,1):
        if c.category in ('clarity','optional') and re.search(r'sai (?:số liệu|dữ liệu|ngữ pháp)',c.error,re.I):
            raise ValueError('Clarity/optional feedback falsely asserts an established error')
        if c.category=='data' and not any(n.verdict=='incorrect' and n.correction_quote and (n.correction_quote in c.original or c.original in n.correction_quote) for n in item.numeric_checks) and not any(x.location=='original' and not x.valid and (x.quote in c.original or c.original in x.quote) for x in item.comparisons):
            raise ValueError('Data correction lacks a verified incorrect original claim')

def validate_quality_contract(item,original,spec):
    matrix=chart_matrix(spec)
    validate_comparisons(item,original,matrix)
    validate_numeric_evidence(item,original,matrix)
    validate_generated_numbers(item,matrix)
    validate_edit_coverage(item,original)
