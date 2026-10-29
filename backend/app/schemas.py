from typing import Literal

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
    stage: Literal["record1", "feedback", "learn", "record2", "compare"]


class ConceptResult(StrictModel):
    concept_id: str
    status: Literal["correct", "partial", "missing", "incorrect"]
    evidence: str = Field(
        max_length=700,
        description="Only a verbatim transcript substring; no commentary or quote wrappers. Empty string if missing.",
    )
    feedback: str = Field(max_length=1000)


class CoachingPoint(StrictModel):
    suggestion: str = Field(max_length=700)
    evidence: str = Field(
        max_length=500,
        description="Only a verbatim transcript substring supporting this suggestion; no commentary or quote wrappers.",
    )


class Assessment(StrictModel):
    summary: str = Field(max_length=1200)
    concepts: list[ConceptResult] = Field(min_length=1, max_length=16)
    next_steps: list[str] = Field(min_length=1, max_length=3)
    communication: list[CoachingPoint] = Field(max_length=3)


class TranscriptEdit(StrictModel):
    text: str = Field(min_length=1, max_length=30000)


class ClaimReview(StrictModel):
    evidence: str = Field(min_length=1, max_length=500)
    verdict: Literal["supported", "incorrect", "needs_nuance", "unverified"]
    explanation: str = Field(min_length=1, max_length=600)
    correction: str = Field(max_length=600)
    reference_ids: list[str] = Field(max_length=4)


class VocabularySuggestion(StrictModel):
    evidence: str = Field(min_length=1, max_length=500)
    original: str = Field(min_length=1, max_length=150)
    alternative: str = Field(min_length=1, max_length=150)
    meaning: str = Field(min_length=1, max_length=350)
    reason: str = Field(min_length=1, max_length=350)
    practice: str = Field(min_length=1, max_length=350)


class InsightReview(StrictModel):
    claims: list[ClaimReview] = Field(max_length=4)
    vocabulary: list[VocabularySuggestion] = Field(max_length=3)


class Reanalysis(StrictModel):
    retranscribe: bool = False


class ModelSelection(StrictModel):
    model: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


class TutorInput(StrictModel):
    message: str = Field(min_length=1, max_length=2500)


class TutorReply(StrictModel):
    answer: str = Field(min_length=1, max_length=6000)
    check_question: str = Field(max_length=500)


class Completion(StrictModel):
    recall: Literal["again", "hard", "good", "easy"] = "good"
