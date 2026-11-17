export type Stage = "record1" | "review1" | "record2" | "review2";
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
export interface Attempt2Item {
  session_id: string;
  topic: Topic;
  attempt2_after: string | null;
  available: boolean;
}
export interface Session {
  id: string;
  topic_id: string;
  topic: Topic;
  created_at: string;
  duration: number;
  style: string;
  prompt_kind: string;
  prompt: string;
  stage: Stage;
  completed_at: string | null;
  attempt2_after?: string | null;
  recall: string | null;
  review_due: string | null;
  attempts: Attempt[];
  messages: Message[];
}
export interface HistoryItem {
  id: string;
  topic: Topic;
  created_at: string;
  completed_at: string | null;
  review_due: string | null;
  attempt_count: number;
  stage: Stage;
  attempt2_after?: string | null;
  coverage: {
    attempt: number;
    correct: number | null;
    total: number;
    wpm: number | null;
    pitch_range_semitones: number | null;
    filler_count: number | null;
  }[];
}
export interface Review {
  topic_id: string;
  topic: Topic;
  due: string;
  interval_days: number;
  repetitions: number;
  overdue: boolean;
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
