import type { Page, Route } from "@playwright/test";

// Explicit UI fixtures and synthetic audio: never used by the application or saved to practice
// data. Every shape below copies the keys the real backend returns (see the Task 2 report and
// backend/app/main.py): a thread, an attempt, a message, History and Ready rows, a recommendation.

export type Json = Record<string, unknown>;

export function wav(seconds = 2): Buffer {
  const samples = 16000 * seconds;
  const b = Buffer.alloc(44 + samples * 2);
  b.write("RIFF");
  b.writeUInt32LE(b.length - 8, 4);
  b.write("WAVEfmt ", 8);
  b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20);
  b.writeUInt16LE(1, 22);
  b.writeUInt32LE(16000, 24);
  b.writeUInt32LE(32000, 28);
  b.writeUInt16LE(2, 32);
  b.writeUInt16LE(16, 34);
  b.write("data", 36);
  b.writeUInt32LE(samples * 2, 40);
  return b;
}

export const timedLines = [
  {
    id: "L1",
    start: 0,
    end: 40,
    text: "So the app helps people, uh, um, track their tasks.",
  },
  {
    id: "L2",
    start: 40,
    end: 84,
    text: "You know, the front end matters most.",
  },
  {
    id: "L3",
    start: 84,
    end: 116,
    text: "Because what good is an app if it is hard to use?",
  },
];

export function tokensFor(
  lines: { id: string; start: number | null; text: string }[],
  timed: boolean,
) {
  const tokens: Json[] = [];
  for (const line of lines) {
    const words = line.text.split(" ");
    for (let i = 0; i < words.length; i++) {
      const raw = words[i];
      const start = timed && line.start != null ? line.start + i : null;
      if (timed && line.id === "L1" && raw === "track")
        tokens.push({ type: "pause", seconds: 0.8, line_id: "L1" });
      if (timed && line.id === "L3" && raw === "Because")
        tokens.push({ type: "pause", seconds: 1.6, line_id: "L3" });
      if (raw === "uh," || raw === "um,")
        tokens.push({
          type: "filler",
          text: raw.replace(",", ""),
          line_id: line.id,
          start,
        });
      else if (raw === "You" && words[i + 1] === "know,") {
        tokens.push({
          type: "possible_filler",
          text: "You know",
          line_id: line.id,
          start,
        });
        i++;
      } else tokens.push({ type: "word", text: raw, line_id: line.id, start });
    }
  }
  return tokens;
}

const coreScores = [
  ["Overall", 5.5, "A clear start that ran long before the backend."],
  ["Clarity", 6.5, "Most sentences were easy to follow."],
  ["Structure", 6, "The backend arrived late."],
  ["Conciseness", 4, "The opening took most of the time."],
  ["Technical accuracy", 7, "What you said was mostly right."],
  ["Technical coverage", 3, "Storage and sync were not reached."],
  ["Handling uncertainty", 6, "You named one open question."],
] as const;

export const review = {
  scores: [
    { name: "Playfulness", score: 6.5, reason: "The aside landed." },
    ...coreScores.map(([name, score, reason]) => ({ name, score, reason })),
  ],
  key_points: [
    {
      text: "Most of the time went before the backend.",
      line_ids: ["L3"],
    },
    { text: "The playful aside landed; trim the buildup.", line_ids: ["L2"] },
    { text: "Pick one storage option and say why.", line_ids: [] },
  ],
  checklist: ["Answer the question in 15 seconds", "Name 3 concrete decisions"],
  comparison: null,
};

export const technical = {
  concepts: [
    {
      concept_id: "usability",
      status: "partial",
      line_ids: ["L3"],
      note: "Usability came up but without an example.",
    },
  ],
  corrections: [
    {
      line_id: "L2",
      claim: "The front end matters most.",
      correction: "The data model shapes the app as much as the front end.",
      basis: "model",
      reference_ids: [],
      verified: false,
    },
  ],
  senior_points: [
    { point: "Start from requirements and scale.", basis: "model" },
  ],
};

export const pass = (status = "done", extra: Json = {}) => ({
  status,
  model: status === "done" ? "test-double" : null,
  error: null,
  ...extra,
});

export const donePasses = () => ({
  memory: pass(),
  technical: pass(),
  communication: pass(),
  writer: pass(),
});

export const authTopic = {
  id: "auth",
  title: "Authentication vs. authorization",
  category: "Networking and web development",
  difficulty: "beginner",
  prompt:
    "Explain authentication and authorization using a real application. What can go wrong if you confuse them?",
};

/** The real `prompts` map for the auth topic: one question per offered question type. */
export const authPrompts = {
  "Concept explanation":
    "Explain authentication and authorization using a real application. What can go wrong if you confuse them?",
  "How it works":
    "Walk another engineer through how authentication vs. authorization works, step by step.",
  Compare:
    "Compare authentication and authorization in a shared document application.",
  "Trade-off":
    "Explain a benefit, a cost, and a case where authentication vs. authorization may be the wrong choice.",
  "Defend a decision":
    "Choose a practical use of authentication vs. authorization. Defend your choice and discuss an alternative.",
  "Nontechnical audience":
    "Explain authentication vs. authorization to a curious nontechnical colleague using an everyday example.",
};

export const SESSION_ID = "review-ui";

/** ATTEMPT as returned in thread `attempts[]` and by POST /api/topics/{id}/attempts. */
export function attempt(
  overrides: Json = {},
  analysisOverrides: Json = {},
): Json {
  const promptKind = (overrides.prompt_kind as string) ?? "Concept explanation";
  return {
    id: "attempt-1",
    session_id: SESSION_ID,
    number: 1,
    created_at: "2026-11-16T12:00:00Z",
    mime: "audio/wav",
    duration: 116,
    transcript: timedLines.map((l) => l.text).join(" "),
    transcript_source: "whisper",
    segments: [],
    acoustics: { wpm: 120, pause_count: 3, filler_count: 1 },
    assessment: null,
    status: "ready",
    errors: {},
    retranscribe: 0,
    transcription_version: 2,
    lines: timedLines,
    tokens: tokensFor(timedLines, true),
    learner_note: null,
    note_state: "submitted",
    note_deadline: "2026-11-16T12:05:00Z",
    chat_summary: null,
    chat_summary_through: 0,
    chat_summary_model: null,
    prompt_kind: promptKind,
    style: "Conversational",
    target_duration: 120,
    scheduled_at: null,
    audio_url: "/review-audio.wav",
    prompt:
      authPrompts[promptKind as keyof typeof authPrompts] ?? authTopic.prompt,
    analysis: {
      version: 1,
      voice_summary: [],
      stats: {
        duration: 116,
        fillers: 1,
        possible_fillers: 1,
        pauses_over_1s: 3,
        longest_pause: 1.6,
      },
      passes: donePasses(),
      technical,
      communication: null,
      timing: [],
      review,
      ...analysisOverrides,
    },
    ...overrides,
  };
}

export function message(overrides: Json = {}): Json {
  return {
    id: 1,
    session_id: SESSION_ID,
    role: "assistant",
    content: 'Your aside landed [[L3:"what good is an app"]].',
    created_at: "2026-11-16T12:05:00Z",
    attempt_number: 1,
    kind: "review",
    model: null,
    parts: [
      { type: "text", text: "Your aside landed " },
      {
        type: "ref",
        line_id: "L3",
        start: 84,
        quote: "what good is an app",
      },
      { type: "text", text: ". Keep that energy." },
    ],
    ...overrides,
  };
}

export const reviewMessage = message();

/** GET /api/topics/{topic_id}/thread: one reviewed attempt, recorded today. */
export function thread(overrides: Json = {}): Json {
  return {
    topic: authTopic,
    prompts: authPrompts,
    session_id: SESSION_ID,
    attempts: [attempt()],
    messages: [reviewMessage],
    recording: {
      can_record: false,
      reason: "Next attempt opens tomorrow",
      replace_number: null,
      next_number: 2,
    },
    latest_checklist: review.checklist,
    next_attempt_after: "2026-11-17",
    ...overrides,
  };
}

/** A topic with no recording yet: the real response has every list empty. */
export function emptyThread(
  topic: Json = authTopic,
  prompts: Json = authPrompts,
): Json {
  return {
    topic,
    prompts,
    session_id: null,
    attempts: [],
    messages: [],
    recording: {
      can_record: true,
      reason: null,
      replace_number: null,
      next_number: 1,
    },
    latest_checklist: [],
    next_attempt_after: null,
  };
}

export async function serve(
  page: Page,
  state: { current: Json },
  topicId = "auth",
) {
  await page.route("**/api/models", (route) =>
    route.fulfill({
      json: {
        selected: "qwen3.5:9b-q4_K_M",
        models: ["qwen3.5:9b-q4_K_M", "gemma4:e4b"].map((name) => ({
          name,
          size_bytes: 6000000000,
          parameters: "9B",
          quantization: "Q4_K_M",
          selectable: true,
          reason: null,
        })),
      },
    }),
  );
  await page.route("**/api/settings/passes", (route) =>
    route.fulfill({
      json: Object.fromEntries(
        ["technical", "communication", "writer", "chat", "memory"].map(
          (name) => [
            name,
            {
              model: "qwen3.5:9b-q4_K_M",
              num_ctx: 8192,
              num_predict: name === "writer" ? 4096 : 2048,
            },
          ],
        ),
      ),
    }),
  );
  await page.route(`**/api/topics/${topicId}/thread`, (route) =>
    route.fulfill({ json: state.current }),
  );
  await page.route("**/review-audio.wav", (route) =>
    route.fulfill({ body: wav(), contentType: "audio/wav" }),
  );
}

export const sse = (events: Json[]) =>
  events.map((e) => "data: " + JSON.stringify(e) + "\n\n").join("");

export const topic = (
  id: string,
  title: string,
  category = "AI and machine learning",
  difficulty = "intermediate",
  prompt = "Explain it.",
) => ({ id, title, category, difficulty, prompt });

/** A GET /api/history row. */
export function historyRow(t: Json, overrides: Json = {}): Json {
  return {
    topic_id: t.id,
    topic: t,
    session_id: `thread-${t.id}`,
    attempt_count: 1,
    last_attempt_at: "2026-11-16T15:46:37.777536+00:00",
    next_attempt_after: "2026-11-17",
    can_record: true,
    coverage: {
      attempt: 1,
      correct: 1,
      total: 4,
      wpm: 132,
      pitch_range_semitones: 4.2,
      filler_count: 2,
    },
    ...overrides,
  };
}

/** A GET /api/practice/ready row. */
export function readyRow(t: Json, overrides: Json = {}): Json {
  const row = historyRow(t, overrides);
  delete row.coverage;
  return { review_due: null, due: false, ...row, ...overrides };
}

/** Mock the list endpoints Today, History and the library read, so no test touches e2e data. */
export async function mockLists(
  page: Page,
  lists: {
    history?: Json[];
    ready?: Json[];
    recommend?: (includePractised: boolean, url: URL) => Json | null;
    topics?: Json[];
  } = {},
) {
  await page.route("**/api/history", (route) =>
    route.fulfill({ json: lists.history ?? [] }),
  );
  await page.route("**/api/practice/ready", (route) =>
    route.fulfill({ json: lists.ready ?? [] }),
  );
  await page.route(/\/api\/topics\/recommend(\?.*)?$/, (route: Route) => {
    const url = new URL(route.request().url());
    const include = url.searchParams.get("include_practised") === "true";
    const body = lists.recommend
      ? lists.recommend(include, url)
      : {
          topic: authTopic,
          practised: false,
          reason: "A fresh perspective for your next practice",
        };
    return body
      ? route.fulfill({ json: body })
      : route.fulfill({
          status: 404,
          json: {
            detail:
              "You have practised every topic that matches. Include practised topics to see them.",
          },
        });
  });
  if (lists.topics)
    await page.route("**/api/topics", (route) =>
      route.fulfill({ json: lists.topics }),
    );
}
