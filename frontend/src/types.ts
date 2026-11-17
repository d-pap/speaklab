export type ConceptStatus = "correct" | "partial" | "missing" | "incorrect";
export interface Topic {
  id: string;
  title: string;
  category: string;
  difficulty: string;
  prompt: string;
}
export interface ConceptResult {
  concept_id: string;
  status: ConceptStatus;
  evidence: string;
  feedback: string;
}
export interface Assessment {
  insights?: {
    version: number;
    note: string;
    sources: { title: string; url: string }[];
    claims: {
      evidence: string;
      verdict: "supported" | "incorrect" | "needs_nuance" | "unverified";
      explanation: string;
      correction: string;
      references: { id: string; text: string }[];
    }[];
    vocabulary: {
      evidence: string;
      original: string;
      alternative: string;
      meaning: string;
      reason: string;
      practice: string;
    }[];
  };
  summary: string;
  concepts: ConceptResult[];
  next_steps: string[];
  communication: { suggestion: string; evidence: string }[];
  rubric: string;
  model: string;
}
export interface Point {
  time: number;
  value: number | null;
}
export interface Acoustics {
  delivery_windows?: {
    start: number;
    end: number;
    loudness_range_db: number | null;
    pitch_range_semitones: number | null;
  }[];
  analysis_version?: number;
  fillers_per_minute?: number | null;
  filler_candidates?: Record<string, number>;
  filler_events?: {
    term: string;
    text: string;
    kind: string;
    char_start: number;
    char_end: number;
    start: number | null;
    timing: string;
  }[];
  repetitions?: { text: string; char_start: number; char_end: number }[];
  vocal_foundations?: {
    foundation: string;
    observation: string;
    practice: string;
    start: number | null;
    basis: string;
  }[];
  readability?: {
    available: boolean;
    grade_band?: number[];
    words: number;
    sentences: number;
    method: string;
    basis: string;
    limitation: string;
    reason?: string;
    repeated_words: { word: string; count: number }[];
  };
  duration?: number;
  active_fraction?: number;
  pause_count?: number;
  pause_seconds?: number;
  pauses?: { start: number; duration: number }[];
  extended_silences?: { start: number; duration: number }[];
  loudness_dbfs?: number;
  loudness_range_db?: number | null;
  pitch_median_hz?: number | null;
  pitch_range_semitones?: number | null;
  clipping_fraction?: number;
  loudness_track?: Point[];
  pitch_track?: Point[];
  word_count?: number;
  wpm?: number;
  fillers?: Record<string, number>;
  filler_count?: number;
  rate_track?: Point[];
  note?: string;
  suggestions?: string[];
  limitations?: string[];
}
export interface Attempt {
  transcription_version?: number;
  id: string;
  session_id: string;
  number: number;
  created_at: string;
  duration: number;
  transcript: string | null;
  transcript_source: string | null;
  segments: { start: number; end: number; text: string }[] | null;
  acoustics: Acoustics | null;
  assessment: Assessment | null;
  status: string;
  errors: Record<string, string>;
  audio_url: string;
  lines?: Line[] | null;
  tokens?: Token[] | null;
  analysis?: Analysis | null;
  learner_note?: string | null;
  note_state?: NoteState | null;
  /** The question type, style and target length this attempt was recorded with. */
  prompt_kind: string;
  style: string;
  target_duration: number;
  /** The question text for this attempt's question type ("" for a retired topic). */
  prompt: string;
}
export type NoteState = "pending" | "submitted" | "skipped" | "legacy";
export interface Line {
  id: string;
  start: number | null;
  end: number | null;
  text: string;
}
export type Token =
  | { type: "word"; text: string; line_id: string; start: number | null }
  | { type: "filler"; text: string; line_id: string; start: number | null }
  | {
      type: "possible_filler";
      text: string;
      line_id: string;
      start: number | null;
    }
  | { type: "pause"; seconds: number; line_id: string };
export type PassName = "memory" | "technical" | "communication" | "writer";
export type PassStatus =
  "pending" | "running" | "waiting" | "done" | "failed" | "skipped";
export interface PassState {
  status: PassStatus;
  model: string | null;
  error: string | null;
  warning?: string | null;
}
export interface TranscriptStats {
  duration?: number;
  fillers?: number;
  possible_fillers?: number;
  pauses_over_1s?: number;
  longest_pause?: number | null;
}
export interface TechnicalAnalysis {
  concepts: {
    concept_id: string;
    status: ConceptStatus;
    line_ids: string[];
    note: string;
  }[];
  corrections: {
    line_id: string;
    claim: string;
    correction: string;
    basis: "reference" | "model";
    reference_ids: string[];
    verified?: boolean;
  }[];
  senior_points: { point: string; basis: "reference" | "model" }[];
}
export interface CommunicationAnalysis {
  sections: { label: string; first_line: string; last_line: string }[];
  points: {
    kind: "strength" | "problem";
    line_id: string;
    observation: string;
    rewrite: string;
  }[];
  gaps: {
    section_label: string;
    kind: "knowledge" | "communication" | "unclear";
    reason: string;
  }[];
  focus: { area: string; observation: string }[];
}
export interface Score {
  name: string;
  score: number;
  reason: string;
}
export interface ReviewStructure {
  accuracy_unscored?: string;
  scores: Score[];
  key_points: { text: string; line_ids: string[] }[];
  checklist: string[];
  comparison: {
    changes: { name: string; before: number; after: number }[];
    what_changed: string;
  } | null;
}
export type AttemptReview = ReviewStructure | { too_short: true };
export interface SectionTiming {
  label: string;
  start: number;
  end: number;
  seconds: number;
  percent: number;
}
export interface Analysis {
  version: number;
  voice_summary: string[];
  stats: TranscriptStats;
  passes: Record<PassName, PassState>;
  technical: TechnicalAnalysis | null;
  communication: CommunicationAnalysis | null;
  timing: SectionTiming[];
  review: AttemptReview | null;
}
export type MessagePart =
  | { type: "text"; text: string }
  | { type: "ref"; line_id: string; start: number | null; quote: string };
export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  attempt_number: number;
  kind: "review" | "chat";
  parts: MessagePart[];
  model?: string | null;
  feedback?: ResponseFeedback | null;
}
export interface ResponseFeedback {
  id: number;
  rating: 1 | -1;
  reason: string | null;
  comment: string;
  preferred_response: string;
  updated_at: string;
}
export interface PassSetting {
  model: string;
  num_ctx: number;
  num_predict: number;
}
export type PassSettings = Record<
  "technical" | "communication" | "writer" | "chat" | "memory",
  PassSetting
>;
export interface CoachNotesVersion {
  id: number;
  content: string;
  created_at: string;
  source: string;
  model: string | null;
  folded_attempt_ids: string[];
}
export interface CoachNotes {
  current: { id: number | null; content: string; model: string | null };
  versions: CoachNotesVersion[];
}
export interface RecordingState {
  can_record: boolean;
  reason: string | null;
  /** Set when the latest attempt was too short: the next recording replaces it. */
  replace_number: number | null;
  next_number: number;
}
/** One topic's practice thread (GET /api/topics/{id}/thread). */
export interface Thread {
  topic: Topic;
  study_reference?: {
    example: string;
    sources: { title: string; url: string }[];
  } | null;
  /** The question for each offered question type. */
  prompts: Record<string, string>;
  session_id: string | null;
  attempts: Attempt[];
  messages: Message[];
  recording: RecordingState;
  latest_checklist: string[];
  next_attempt_after: string | null;
}
export interface Coverage {
  attempt: number;
  correct: number | null;
  total: number;
  wpm: number | null;
  pitch_range_semitones: number | null;
  filler_count: number | null;
}
interface ThreadSummary {
  topic_id: string;
  topic: Topic;
  session_id: string;
  attempt_count: number;
  last_attempt_at: string;
  next_attempt_after: string | null;
  can_record: boolean;
}
/** A History row (GET /api/history): one per topic with a recording. */
export interface HistoryRow extends ThreadSummary {
  coverage: Coverage;
}
/** A practised topic with a new attempt open (GET /api/practice/ready). */
export interface ReadyRow extends ThreadSummary {
  review_due: string | null;
  due: boolean;
}
export interface Recommendation {
  topic: Topic;
  practised: boolean;
  reason: string;
}
export interface Health {
  status: string;
  ollama: boolean;
  whisper: boolean;
  model: string;
  models: string[];
  data_dir: string;
  server_name: string;
  ollama_url: string;
  whisper_url: string;
}
