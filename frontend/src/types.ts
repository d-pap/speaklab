export type Stage = "record1" | "feedback" | "learn" | "record2" | "compare";
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
}
export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
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
export interface Lesson {
  estimated_minutes: number;
  personalized: boolean;
  objectives: string[];
  sections: {
    title: string;
    minutes: number;
    body: string;
    context?: string;
    practice?: string;
    question: string;
  }[];
  sources: { title: string; url: string }[];
}
export interface Comparison {
  available: boolean;
  newly_demonstrated: string[];
  corrected: string[];
  remaining: string[];
  note: string;
  concepts: { id: string; name: string }[];
  prior_session: {
    id: string;
    date: string;
    available: boolean;
    days_elapsed: number;
    previously_demonstrated: number;
    recalled: number;
  } | null;
}
