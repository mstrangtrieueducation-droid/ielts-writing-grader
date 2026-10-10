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

Cost controls remain unchanged: Flash only, text-only essays, one generation attempt, medium thinking,
maximum 8,192 output tokens including thinking, durable class budget 14,900 VND, and any separately
authorized trial ceiling. More input/output tokens can change the bill even when the model's unit
price is unchanged. Editing or testing these instructions locally does not call the grading API.
