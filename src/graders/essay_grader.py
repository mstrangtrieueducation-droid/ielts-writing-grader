import json
import re
from ..schemas import EssayResult, Transcription, QualityReview
from ..parsers import word_count, essay_paragraphs, digest
from ..media import validate_page_audit, validate_references

RUBRIC = '''Assess strictly against the actual assigned teacher theory, outline and chart ground truth.
For Task1 verify each original year, category, quantity, unit, axis, legend and numerical comparison;
overview includes relevant trends/extrema/turning points supported by this specific chart.
Do not invent a peak for a non-trend chart. Counts: number of cars, not amount of cars/how much cars.
Check comma thousands versus decimal points in context, not a blind substitution.
Teacher presentation rules: minimum150(Task1)/250(Task2), exactly4 paragraphs, 3–5 sentences
per body unless the trusted specification overrides. Distinguish these course rules from grammar.
Flag contractions, informal like used to list examples, and sentence-initial So/Because/But as
teacher register requirements; a complete Because-clause followed by a main clause is not ungrammatical.
Explain EVERY independently present clause error, missing finite verb, agreement, dangling modifier,
causal jump, incorrect connector, unclear reference, absent first/second idea signpost, omitted outline
chain and opinion redundancy. Accept precise formal equivalents, not rigid phrase substitution.
Each correction quotes an EXACT original substring and supplies a specific Vietnamese explanation
and a corrected sentence. Do not flag OCR uncertainty as a student error.
Do not invent mandatory articles: quantified phrases such as 'three courses' are grammatical;
adding 'the' can be a stylistic choice, not a missing-article error. Separate optional refinements
from actual errors. Do not falsely claim an ambiguous or imprecise expression is ungrammatical.
Report actual application of taught theory with examples. Upgrade to a coherent four-paragraph
essay preserving the assigned position/ideas, with typed spans: yellow stance/attribution,
blue functional connectors, green hedging; plain for other text. Extract4–6 useful collocations.
No blanket praise, system narration or teacher-confirmation claim. For assessment only, include
TR(or TA), CC, LR, GRA band scores0–9 in half-point steps with feedback justification.
For homework band_scores must be empty. All student-facing text must be Vietnamese except essays,
original quotes, suggestions and collocations.'''

def source_quote(quote, original):
    if quote in original:
        return quote
    # Recover only a unique whitespace-normalized quote from the actual source.
    # Words, case, punctuation and numbers must be unchanged; ambiguity stays blocked.
    tokens=re.split(r'\s+',quote.strip())
    if not tokens or not any(tokens):
        raise ValueError('Correction quotes text absent from the actual essay')
    matches=list(re.finditer(r'\s+'.join(re.escape(t) for t in tokens),original))
    if len(matches)!=1:
        raise ValueError('Correction quotes text absent or ambiguous in the actual essay')
    return matches[0].group()

def validate_essay(result, original, spec, assessment=False):
    if result.exercise != spec.exercise or result.original != original:
        raise ValueError('Original essay/exercise identity changed')
    if result.word_count != word_count(original):
        raise ValueError('Model word count differs from deterministic count')
    paragraphs = essay_paragraphs(original)
    if result.paragraph_count != len(paragraphs):
        raise ValueError('Paragraph count differs from source text')
    for item in result.corrections:
        item.original=source_quote(item.original,original)
    if assessment:
        required = {'TA' if spec.task == 1 else 'TR', 'CC', 'LR', 'GRA'}
        if set(result.band_scores) != required or any(not 0 <= v <= 9 or v*2 != int(v*2) for v in result.band_scores.values()):
            raise ValueError('Invalid assessment band scores')
    elif result.band_scores:
        raise ValueError('Homework must not manufacture IELTS test scores')
    minimum = spec.minimum_words or (150 if spec.task == 1 else 250)
    if result.status == 'Đạt yêu cầu' and (result.word_count < minimum or result.paragraph_count != spec.paragraphs):
        raise ValueError('Passing verdict contradicts length/paragraph requirements')
    upgraded = '\n\n'.join(''.join(s.text for s in paragraph) for paragraph in result.upgraded_paragraphs)
    if word_count(upgraded) < minimum:
        raise ValueError('Upgraded essay below required word count')
    return result

def transcribe(ai, settings, binding, files, counts):
    prompt = 'Transcribe each assigned exercise verbatim. Preserve paragraph breaks with blank lines. '
    prompt += 'Unreadable/cropped handwriting => readable=false, do not reconstruct. A genuinely blank/uncompleted answer is readable and may be empty. '
    prompt += json.dumps({'exercises':[{'exercise':e.exercise,'question':e.question} for e in binding.essays], 'student_files':counts})
    if 'flash' not in settings.notebook_model.lower():
        raise ValueError('Scan transcription requires Flash; Pro is text-only')
    result = ai.structured(settings.notebook_model, prompt, Transcription, files)
    validate_page_audit(result.page_audit, counts)
    if sorted(x.exercise for x in result.essays) != sorted(x.exercise for x in binding.essays):
        raise ValueError('Scan transcription lacks or duplicates an exercise')
    for essay in result.essays:
        validate_references(essay.pages, counts)
        if not essay.readable:
            raise ValueError('Handwriting cannot be read confidently')
    return {x.exercise:x.original for x in result.essays}

def grade_essay(ai, settings, spec, original, reference_files, assessment=False, checkpoint=None, pending=None):
    # The verified text specification replaces repeated full lesson/chart scans.
    # Fail closed if Task 1 numerical evidence has not been frozen as text.
    if spec.task == 1 and not spec.ground_truth.strip():
        raise ValueError('Task 1 requires verified chart data in the text specification')
    count = word_count(original)
    paragraphs = len(essay_paragraphs(original))
    prompt = RUBRIC + '\nTRUSTED SPECIFICATION:\n' + spec.model_dump_json()
    prompt += f'\nassessment={assessment}; verified word_count={count}; paragraph_count={paragraphs}\n'
    prompt += 'Keep the verified counts unchanged. Form paragraphs may use a single newline, with no blank line.\n'
    prompt += 'UNTRUSTED STUDENT ESSAY JSON:\n' + json.dumps(original,ensure_ascii=False)
    prompt += 'Correction.original must be copied character-for-character, including repeated spaces and punctuation. Do not tidy a quote.\n'
    prompt += 'Finish all grading in this single response. Before returning JSON, check every original clause, numeric comparison, taught requirement, correction and revision for consistency. Be concise in explanations without omitting independent errors.\n'
    source_digest=digest(original+'\0'+spec.model_dump_json()+'\0'+str(assessment))
    if pending:
        if pending.get('source_digest')!=source_digest:
            raise ValueError('Pending essay review does not match frozen original/specification')
        if pending.get('status') in ('received','validated'):
            result=validate_essay(EssayResult.model_validate(pending['result']),original,spec,assessment)
            if checkpoint and pending['status']=='received':
                checkpoint({**pending,'status':'validated','result':result.model_dump(mode='json')})
            return result
        if pending.get('review') and QualityReview.model_validate(pending['review']).approved:
            return validate_essay(EssayResult.model_validate(pending['result']),original,spec,assessment)
        # Preserve unresolved legacy audits and sent/failed calls. Never silently repay.
        raise ValueError('Saved essay attempt is unresolved; no automatic paid regeneration')
    work={'source_digest':source_digest,'status':'reserved','mode':'one_pass_text_v1'}
    if checkpoint:
        checkpoint(work.copy())  # Durable BEFORE the charge; a crash cannot auto-regenerate.
    try:
        result=ai.structured(settings.essay_model,prompt,EssayResult,())
        work.update(status='received',result=result.model_dump(mode='json'))
        if checkpoint:
            checkpoint(work.copy())
        result=validate_essay(result,original,spec,assessment)
    except Exception:
        work['status']='held'
        if checkpoint:
            checkpoint(work.copy())
        raise
    work.update(status='validated',result=result.model_dump(mode='json'))
    if checkpoint:
        checkpoint(work.copy())
    return result
