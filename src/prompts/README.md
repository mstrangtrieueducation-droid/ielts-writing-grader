# Flash one-pass prompt v03

Active entry point: `graders/essay_grader.py`, version `flash-one-pass-v03-language-and-data`.
The shared rubric, the exact verified lesson specification and the language instructions in
`flash-language-v03.txt` are combined in one request. Task 1 adds the numerical audit and
the complete list of numeric-bearing source segments, including repeated ranking/year values.

Compact private `language_checks` index every source segment and link all corrections by their
1-based array indices. They are reading coverage, not proof that the model's semantic judgments
are correct. Source-based quality verification remains mandatory for staged trials. Never publish
a rejected result just because its JSON and coverage are valid.

The new prompt does not replay or amend old student results. Saved attempts retain their old schema;
each new attempt freezes the complete prompt hash before the paid request. Rejected/held attempts
do not acquire automatic paid repairs.

Cost controls for the Flash path: text-only essays, one generation attempt, medium thinking,
maximum 8,192 output tokens including thinking, durable class budget 14,900 VND, and any separately
authorized trial ceiling. More input/output tokens can change the bill even when the model's unit
price is unchanged. Editing or testing these instructions locally does not call the grading API.

## Hybrid proposal, 10 October 2026

`graders/essay_bundle.py` freezes `hybrid-two-essays-v01`. Flash reads notebook scans and
explicitly assigned student-outline requirements in the same notebook inspection. A teacher's
outline in `EssaySpec` is not evidence that a student has submitted an outline. Pro receives
only verified textual specifications and the two originals of ONE student, in ONE request.
The shared rubric is sent once. Original text and deterministic counts are restored locally;
all individual corrections, revisions, collocations and private coverage remain required.
Pro cannot take PDF/images, inspect notebooks, perform a separate reviewer call or repair a
held attempt. Frozen Flash results are not silently regraded by the hybrid path.

The hybrid student/task ledger totals Flash and Pro charges across job IDs. Its default ceiling
is 1,000 VND, while the existing 14,900 VND class/task ceiling also applies. This is an application
budget based on an assumed exchange rate, not a Google billing limit or an assurance of completion.
The full 8,192-token Pro output reserve alone exceeds 1,000 VND. Consequently this configuration
holds fresh hybrid grading BEFORE notebook generation, with a budget error; it does not obtain
an incomplete low-token response and call that a thorough 1,000 VND result. Generation remains OFF.
No automatic cost-limit increase is authorized by this code.

The latest requested economical trial can use Pro Flex with the SAME model, medium thinking and
8,192-token output allowance. Flex price is half Standard; no Standard fallback or generation retry
is allowed. This requires its own explicitly approved budget and selected-student authorization;
the production 1,000 VND limit and generation-OFF flags remain unchanged. A tier-unconfirmed
response preserves raw output/full reserve and freezes the cost scope instead of claiming savings.
The new shared bundle version checks punctuation, rating complements, respectively group order
and static-chart language. Explicit `data_kind=static` also blocks peak language in suggestions,
the revision and collocation examples. None of these guards proves exhaustive semantic correctness:
the real pilot still requires review against its actual originals and verified source data.

Correction locations (12 October 2026): new independent Batch prompts include
`correction-locations-v01.txt`. Frozen requests and returned grading text stay intact.
The display numbers corrections separately within each essay as `Lỗi N`. Locations
come from exact quote offsets in the unchanged original, never the model's `Unit`
audit IDs. Task 1 paragraphs with a clearly identifiable introduction and overview
use Introduction / Overview / Detail; two genuinely separate body paragraphs use
Detail 1 / Detail 2. Otherwise use the actual paragraph number. Sentence numbers
restart in each paragraph; a quote crossing sentences displays a range. Repeated
quotes retain all matching locations. No annotation in a paragraph does not mean
that paragraph is missing. Do not infer the student's layout from the four-paragraph
suggested revision, or silently add paragraph breaks to the original.
