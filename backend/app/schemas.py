from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Style = Literal["Conversational", "Thoughtful teacher", "Concise interview", "Animated storyteller"]
PromptKind = Literal[
    "Concept explanation",
    "How it works",
    "Compare",
    "Trade-off",
    "Defend a decision",
    "Nontechnical audience",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionCreate(StrictModel):
    topic_id: str = Field(max_length=80)
    duration: int = Field(default=120, ge=120, le=300)
    style: Style = "Conversational"
    prompt_kind: PromptKind = "Concept explanation"


class StageChange(StrictModel):
    stage: Literal["record1", "review1", "record2", "review2"]


class TranscriptEdit(StrictModel):
    text: str = Field(min_length=1, max_length=30000)


class CoachNotesEdit(StrictModel):
    content: str = Field(max_length=20000)


class ModelSelection(StrictModel):
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class PassConfig(StrictModel):
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    num_ctx: int
    num_predict: int


class PassSettings(StrictModel):
    passes: dict[str, PassConfig]


class ChatInput(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    attempt_number: Literal[1, 2]


class LearnerNote(StrictModel):
    text: str | None = Field(default=None, max_length=2000)
    skip: bool = False


# Coach pass outputs. ID fields are plain strings here; each pass narrows them with
# enums in the output schema it sends and checks them again after parsing.
class ConceptFinding(StrictModel):
    concept_id: str
    status: Literal["correct", "partial", "missing", "incorrect"]
    line_ids: list[str] = Field(max_length=8)
    note: str = Field(max_length=500)


class Correction(StrictModel):
    line_id: str
    claim: str = Field(min_length=1, max_length=400)
    correction: str = Field(min_length=1, max_length=600)
    basis: Literal["reference", "model"]
    reference_ids: list[str] = Field(max_length=4)


class SeniorPoint(StrictModel):
    point: str = Field(min_length=1, max_length=400)
    basis: Literal["reference", "model"]


class TechnicalAnalysis(StrictModel):
    concepts: list[ConceptFinding] = Field(min_length=1, max_length=16)
    corrections: list[Correction] = Field(max_length=4)
    senior_points: list[SeniorPoint] = Field(min_length=3, max_length=7)


class CorrectionReview(StrictModel):
    id: str
    verdict: Literal["supported", "incorrect", "needs_nuance", "unverified"]
    explanation: str = Field(min_length=1, max_length=600)
    correction: str = Field(max_length=600)
    reference_ids: list[str] = Field(max_length=4)


class CorrectionCheck(StrictModel):
    reviews: list[CorrectionReview] = Field(max_length=4)


class Section(StrictModel):
    label: str = Field(min_length=1, max_length=60)
    first_line: str
    last_line: str


class CommunicationPoint(StrictModel):
    kind: Literal["strength", "problem"]
    line_id: str
    observation: str = Field(min_length=1, max_length=500)
    rewrite: str = Field(max_length=600)


class SectionGap(StrictModel):
    section_label: str
    kind: Literal["knowledge", "communication", "unclear"]
    reason: str = Field(min_length=1, max_length=400)


class FocusObservation(StrictModel):
    area: str = Field(min_length=1, max_length=80)
    observation: str = Field(min_length=1, max_length=500)


class CommunicationAnalysis(StrictModel):
    sections: list[Section] = Field(min_length=1, max_length=6)
    points: list[CommunicationPoint] = Field(max_length=6)
    gaps: list[SectionGap] = Field(max_length=6)
    focus: list[FocusObservation] = Field(max_length=6)


class Score(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    score: float = Field(ge=0, le=10, multiple_of=0.5)
    reason: str = Field(min_length=1, max_length=120)


class KeyPoint(StrictModel):
    text: str = Field(min_length=1, max_length=500)
    line_ids: list[str] = Field(max_length=6)


class ScoreChange(StrictModel):
    name: str
    before: float
    after: float


class Comparison(StrictModel):
    changes: list[ScoreChange] = Field(max_length=12)
    what_changed: str = Field(min_length=1, max_length=800)


class ReviewStructure(StrictModel):
    scores: list[Score] = Field(min_length=7, max_length=10)
    key_points: list[KeyPoint] = Field(min_length=3, max_length=3)
    checklist: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(min_length=2, max_length=5)
    comparison: Comparison | None = None
