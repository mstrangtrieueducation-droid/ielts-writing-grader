"""Narrow deterministic safeguards; not a claim to automate semantic judgement."""
import re
from pathlib import Path

POLICY = (Path(__file__).resolve().parents[1]/'prompts'/'teaching-fairness-v01.txt').read_text(encoding='utf8')

# These are regression examples, not the prompt's definition of acceptable abbreviations.
EXPANSIONS = {'US': 'United States', 'UK': 'United Kingdom',
              'UN': 'United Nations', 'GDP': 'gross domestic product'}

def expanded(text):
    for short, full in EXPANSIONS.items():
        text = re.sub(r'\b'+short+r'\b', full, text)
    return re.sub(r'\s+', ' ', text).strip()

def validate_teaching_fairness(item, spec):
    for correction in item.corrections:
        # Identical meaning/grammar with only a conventional expansion is not an error.
        # A real article/capitalisation/quantity change remains available for review.
        if correction.original != correction.suggested and expanded(correction.original) == expanded(correction.suggested):
            raise ValueError('Conventional abbreviation expansion alone is not a correction')
    # Only an explicit, trusted lesson directive activates the ordering check.
    # The JSON line is frozen with the teacher's lesson, never taken from pupil text.
    import json
    lines = [line.removeprefix('RESIDUAL_CATEGORY_LAST:').strip()
             for line in spec.taught_theory.splitlines() if line.startswith('RESIDUAL_CATEGORY_LAST:')]
    if not lines or spec.task != 1:
        return
    if len(lines) != 1:
        raise ValueError('Ambiguous residual-category lesson directive')
    rule = json.loads(lines[0])
    labels, named = rule['labels'], rule['named_categories']
    if not labels or not named or any(not isinstance(x,str) or not x.strip() for x in labels+named):
        raise ValueError('Incomplete residual-category lesson directive')
    paragraphs = [''.join(s.text for s in p) for p in item.upgraded_paragraphs]
    def positions(text, terms):
        return [m for term in terms for m in re.finditer(r'(?<!\w)'+re.escape(term)+r'(?!\w)',text,re.I)]
    body = '\n\n'.join(paragraphs[2:])
    residual = positions(body, labels)
    if not residual:
        raise ValueError('Revision omits the assigned residual category')
    first = min(m.start() for m in residual)
    if positions('\n\n'.join(paragraphs[2:-1]), labels) or any(m.start()>first for m in positions(body,named)):
        raise ValueError('Residual category must follow named categories in the final Detail')
