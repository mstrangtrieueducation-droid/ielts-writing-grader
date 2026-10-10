from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Requirement(Strict):
    id: str
    text: str

class EssaySpec(Strict):
    exercise: int = Field(ge=1)
    task: Literal[1, 2]
    question: str = Field(min_length=10)
    taught_theory: str = Field(min_length=20)
    assigned_outline: str
    ground_truth: str
    chart_file_ids: list[str] = Field(default_factory=list)
    minimum_words: int | None = None
    paragraphs: int = 4
    body_min_sentences: int = 3
    body_max_sentences: int = 5

class Binding(Strict):
    task_code: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]*$')
    class_name: str
    assignment_type: Literal['vocabulary', 'notebook', 'homework', 'assessment']
    lesson: int = Field(ge=1, le=54)
    ready: bool = False
    source_verified: bool = False
    version: str
    source_reference: str = Field(min_length=5)
    source_file_ids: list[str] = Field(min_length=1)
    notebook_requirements: list[Requirement] = Field(default_factory=list)
    notebook_copy_scope: str = ''
    vocabulary: list[Requirement] = Field(default_factory=list)
    essays: list[EssaySpec] = Field(default_factory=list)
    form_spreadsheet_id: str = ''
    form_tab: str = ''
    name_column: str = 'B'
    class_column: str | None = 'C'
    receipt_column: str = 'A'
    notebook_columns: list[str] = Field(default_factory=list)
    essay_columns: dict[int, str] = Field(default_factory=dict)
    submission_start_row: int = 2
    tracker_tab: str = 'THEO DÕI TOÀN DIỆN'
    tracker_header_range: str = 'A1:ZZ5'
    tracker_header_exact: str
    roster_name_column: str = 'B'
    roster_id_column: str = 'A'
    roster_start_row: int = 7
    roster_end_row: int
    dashboard_link_column: str | None = None
    next_writing_date: date | None = None
    next_writing_evidence: str = ''
    due_at: datetime | None = None
    aliases: dict[str, str] = Field(default_factory=dict)
    notebook_overrides: dict[str, str] = Field(default_factory=dict)
    regrade_authorizations: dict[str, str] = Field(default_factory=dict)
    early_lesson_authorized: bool = False
    archive_before_20260930: bool = False

    @model_validator(mode='after')
    def coherent(self):
        if self.due_at and self.due_at.tzinfo is None:
            raise ValueError('Due time requires an explicit timezone')
        if self.assignment_type == 'homework' and not self.essays:
            raise ValueError('Homework requires explicit exercise specifications')
        if self.assignment_type == 'assessment' and not self.essays:
            raise ValueError('Assessment requires separate test specifications')
        if self.assignment_type != 'assessment':
            if not self.form_spreadsheet_id or not self.form_tab:
                raise ValueError('Component/homework requires original Form source')
            if not self.next_writing_date or not self.next_writing_evidence or not self.due_at:
                raise ValueError('Verified actual next Writing date and due time required')
        if self.assignment_type in ('homework', 'notebook') and not self.notebook_requirements:
            raise ValueError('Explicit assigned notebook checklist required')
        if self.assignment_type in ('homework', 'notebook') and len(self.notebook_copy_scope.strip())<20:
            raise ValueError('Explicit notebook copying boundary and excluded homework sources required')
        if self.assignment_type == 'vocabulary' and not self.vocabulary:
            raise ValueError('Explicit vocabulary checklist required')
        if self.roster_end_row < self.roster_start_row:
            raise ValueError('Invalid roster bounds')
        ids = [r.id for r in self.notebook_requirements]
        words = [r.id for r in self.vocabulary]
        exercises = [e.exercise for e in self.essays]
        if len(ids) != len(set(ids)) or len(words) != len(set(words)) or len(exercises) != len(set(exercises)):
            raise ValueError('Duplicate requirement/exercise IDs')
        if self.lesson == 6 and self.assignment_type == 'homework':
            raise ValueError('Lesson 6 is notebook-only')
        return self

class PageEvidence(Strict):
    file_id: str
    page: int = Field(ge=1)
    readable: bool
    description: str

class ItemCheck(Strict):
    id: str
    status: Literal['complete', 'missing', 'typed_or_printed', 'digital_overlay', 'uncertain']
    explanation_vi: str
    pages: list[PageEvidence]

class NotebookResult(Strict):
    items: list[ItemCheck]
    page_audit: list[PageEvidence]
    summary_vi: str

class ExtractedEssay(Strict):
    exercise: int
    original: str
    readable: bool
    pages: list[PageEvidence]

class Transcription(Strict):
    essays: list[ExtractedEssay]
    page_audit: list[PageEvidence]

class Correction(Strict):
    section: str
    original: str = Field(min_length=1)
    error: str = Field(min_length=3)
    suggested: str = Field(min_length=1)

class Collocation(Strict):
    phrase: str
    type: str
    meaning_vi: str
    usage_example: str

class ColoredSpan(Strict):
    text: str
    color: Literal['plain', 'yellow', 'blue', 'green']

class EssayResult(Strict):
    exercise: int
    status: Literal['Đạt yêu cầu', 'Cần sửa', 'Cần sửa và nộp lại']
    original: str
    word_count: int
    paragraph_count: int
    summary_vi: str = Field(min_length=30)
    taught_application_vi: str = Field(min_length=15)
    corrections: list[Correction]
    upgraded_paragraphs: list[list[ColoredSpan]] = Field(min_length=4, max_length=4)
    collocations: list[Collocation] = Field(min_length=4, max_length=6)
    band_scores: dict[str, float] = Field(default_factory=dict)

class NumericCheck(Strict):
    original_claim: str = Field(min_length=1)
    verdict: Literal['accurate', 'incorrect', 'imprecise', 'ambiguous']
    evidence: str = Field(min_length=5)
    correction_quote: str

class FlashTask1Result(EssayResult):
    # Private QA evidence, not an extra student-facing checklist/card.
    numeric_checks: list[NumericCheck]

class QualityReview(Strict):
    approved: bool
    issues: list[str]

    @model_validator(mode='after')
    def consistent(self):
        if self.approved and self.issues or not self.approved and not self.issues:
            raise ValueError('Quality review approval contradicts issue list')
        return self
