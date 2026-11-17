import { expect, test, type Page } from "@playwright/test";

// Explicit UI fixtures and synthetic audio: never used by the application or saved to practice data.
function wav(seconds = 2): Buffer {
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

type Json = Record<string, unknown>;

const timedLines = [
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

function tokensFor(
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

const review = {
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

const technical = {
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

const pass = (status = "done", extra: Json = {}) => ({
  status,
  model: status === "done" ? "test-double" : null,
  error: null,
  ...extra,
});

const donePasses = () => ({
  memory: pass(),
  technical: pass(),
  communication: pass(),
  writer: pass(),
});

function attempt(overrides: Json = {}, analysisOverrides: Json = {}): Json {
  return {
    id: "attempt-1",
    session_id: "review-ui",
    number: 1,
    created_at: "2026-11-16T12:00:00Z",
    duration: 116,
    transcript: timedLines.map((l) => l.text).join(" "),
    transcript_source: "whisper",
    transcription_version: 2,
    segments: [],
    acoustics: { wpm: 120, pause_count: 3, filler_count: 1 },
    assessment: null,
    status: "ready",
    errors: {},
    audio_url: "/review-audio.wav",
    lines: timedLines,
    tokens: tokensFor(timedLines, true),
    learner_note: null,
    note_state: "submitted",
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

const reviewMessage = {
  id: 1,
  role: "assistant",
  content: 'Your aside landed [[L3:"what good is an app"]].',
  created_at: "2026-11-16T12:05:00Z",
  attempt_number: 1,
  kind: "review",
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
};

function session(overrides: Json = {}): Json {
  return {
    id: "review-ui",
    topic_id: "auth",
    topic: {
      id: "auth",
      title: "Authentication vs. authorization",
      category: "Security",
      difficulty: "beginner",
      prompt: "Explain the difference.",
    },
    created_at: "2026-11-16T12:00:00Z",
    duration: 120,
    style: "Conversational",
    prompt_kind: "Concept explanation",
    prompt: "Explain the difference between authentication and authorization.",
    stage: "review1",
    completed_at: null,
    recall: null,
    review_due: null,
    attempts: [attempt()],
    messages: [reviewMessage],
    ...overrides,
  };
}

async function serve(page: Page, state: { current: Json }) {
  await page.route("**/api/sessions/review-ui", (route) =>
    route.fulfill({ json: state.current }),
  );
  await page.route("**/review-audio.wav", (route) =>
    route.fulfill({ body: wav(), contentType: "audio/wav" }),
  );
}

const sse = (events: Json[]) =>
  events.map((e) => "data: " + JSON.stringify(e) + "\n\n").join("");

test("review page shows inline fillers and pauses and highlights a line from a chat time link", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await serve(page, { current: session() });
  await page.goto("/#/session/review-ui");
  // The review exists, so the Review tab opens first.
  await expect(page.getByRole("tab", { name: "Review" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const chat = page.getByRole("region", { name: "Coach chat" });
  await expect(chat.getByText("Your aside landed")).toBeVisible();
  await expect(chat.getByText("“what good is an app”")).toBeVisible();
  await chat.getByRole("button", { name: "1:24" }).click();
  await expect(page.getByRole("tab", { name: "Transcript" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const transcript = page.getByRole("tabpanel", { name: "Transcript" });
  await expect(
    transcript.getByText(
      "1:56 · 1 filler, 1 possible · 3 pauses over 1s · longest 1.6s",
    ),
  ).toBeVisible();
  await expect(transcript.locator("mark.filler:not(.possible)")).toHaveText([
    "uh",
    "um",
  ]);
  await expect(transcript.locator("mark.filler.possible")).toHaveText(
    "You know",
  );
  await expect(transcript.locator(".pause")).toHaveText(["0.8s", "1.6s"]);
  await expect(transcript.locator('[data-line="L2"] .ts')).toHaveText("0:40");
  await expect(transcript.locator('[data-line="L3"]')).toHaveClass(/highlight/);
  await expect(transcript.locator('[data-line="L1"]')).not.toHaveClass(
    /highlight/,
  );
  await page.screenshot({
    path: "test-results/review-transcript-desktop.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("note box send and skip", async ({ page }) => {
  const state = {
    current: session({
      attempts: [
        attempt(
          { note_state: "pending" },
          {
            review: null,
            passes: { ...donePasses(), writer: pass("waiting") },
          },
        ),
      ],
      messages: [],
    }),
  };
  const bodies: Json[] = [];
  await serve(page, state);
  await page.route("**/api/attempts/attempt-1/note", (route) => {
    bodies.push(route.request().postDataJSON());
    state.current = session({
      attempts: [
        attempt({ note_state: bodies.at(-1)!.skip ? "skipped" : "submitted" }),
      ],
    });
    return route.fulfill({ json: attempt() });
  });
  await page.goto("/#/session/review-ui");
  const box = page.getByRole("region", { name: "How did that go?" });
  await expect(box).toBeVisible();
  await expect(
    box.getByRole("button", { name: "Send", exact: true }),
  ).toBeDisabled();
  await box
    .getByLabel("Your own read of this attempt")
    .fill("I rambled at the start.");
  await box.getByRole("button", { name: "Send", exact: true }).click();
  await expect(box).toHaveCount(0);
  expect(bodies).toEqual([{ text: "I rambled at the start." }]);

  state.current = session({
    attempts: [
      attempt(
        { note_state: "pending" },
        { review: null, passes: { ...donePasses(), writer: pass("waiting") } },
      ),
    ],
    messages: [],
  });
  await page.reload();
  await page
    .getByRole("region", { name: "How did that go?" })
    .getByRole("button", { name: "Skip", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "How did that go?" }),
  ).toHaveCount(0);
  expect(bodies[1]).toEqual({ skip: true });
});

test("failed pass shows retry and keeps transcript", async ({ page }) => {
  const passes = {
    memory: pass(),
    technical: pass(),
    communication: {
      status: "failed",
      model: null,
      error: "The local model could not be reached. Your recording is safe.",
    },
    writer: pass("pending"),
  };
  const state = {
    current: session({
      attempts: [attempt({ status: "partial" }, { passes, review: null })],
      messages: [],
    }),
  };
  await serve(page, state);
  let retried = 0;
  await page.route("**/api/attempts/attempt-1/retry", (route) => {
    retried++;
    return route.fulfill({ json: { status: "pending" } });
  });
  await page.goto("/#/session/review-ui");
  await expect(
    page.getByText(
      "The local model could not be reached. Your recording is safe.",
    ),
  ).toBeVisible();
  // No review yet, so the Transcript tab opens first and keeps the transcript.
  const transcript = page.getByRole("tabpanel", { name: "Transcript" });
  await expect(transcript.locator('[data-line="L3"]')).toContainText(
    "what good is an app",
  );
  // The technical result that finished stays readable.
  await page.getByRole("tab", { name: "Review" }).click();
  await expect(
    page.getByText("Usability came up but without an example."),
  ).toBeVisible();
  await expect(page.getByText("Not in reference").first()).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).first().click();
  await expect.poll(() => retried).toBe(1);
});

test("edited transcript shows line labels instead of times", async ({
  page,
}) => {
  const untimed = timedLines.map((l) => ({ ...l, start: null, end: null }));
  await serve(page, {
    current: session({
      attempts: [
        attempt({
          transcript_source: "manual",
          lines: untimed,
          tokens: tokensFor(untimed, false),
        }),
      ],
      messages: [
        {
          ...reviewMessage,
          parts: [
            { type: "text", text: "Look at " },
            { type: "ref", line_id: "L3", start: null, quote: "" },
          ],
        },
      ],
    }),
  });
  await page.goto("/#/session/review-ui");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await chat.getByRole("button", { name: "line 3" }).click();
  const transcript = page.getByRole("tabpanel", { name: "Transcript" });
  await expect(transcript.locator('[data-line="L3"]')).toHaveClass(/highlight/);
  await expect(transcript.locator(".ts")).toHaveCount(0);
  await expect(transcript.locator(".pause")).toHaveCount(0);
});

test("too-short attempt shows no scores", async ({ page }) => {
  const skipped = pass("skipped");
  await serve(page, {
    current: session({
      attempts: [
        attempt(
          { note_state: "pending" },
          {
            review: { too_short: true },
            technical: null,
            passes: {
              memory: skipped,
              technical: skipped,
              communication: skipped,
              writer: skipped,
            },
          },
        ),
      ],
      messages: [],
    }),
  });
  await page.goto("/#/session/review-ui");
  await expect(
    page.getByText(
      "No substantive explanation was recorded. Record again when you’re ready.",
    ),
  ).toBeVisible();
  await expect(page.locator(".score-chip")).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "How did that go?" }),
  ).toHaveCount(0);
});

test("scores, key points and checklist stay in review tab while chat grows", async ({
  page,
}) => {
  const state = { current: session() };
  await serve(page, state);
  const sent: Json[] = [];
  let id = 10;
  await page.route("**/api/sessions/review-ui/chat", (route) => {
    const body = route.request().postDataJSON();
    sent.push(body);
    const user = {
      id: id++,
      role: "user",
      content: body.message,
      created_at: "2026-11-16T12:10:00Z",
      attempt_number: 1,
      kind: "chat",
      parts: [{ type: "text", text: body.message }],
    };
    const reply = {
      id: id++,
      role: "assistant",
      content: `Reply ${sent.length} [[L1]]`,
      created_at: "2026-11-16T12:10:01Z",
      attempt_number: 1,
      kind: "chat",
      parts: [
        { type: "text", text: `Reply ${sent.length} ` },
        { type: "ref", line_id: "L1", start: 0, quote: "" },
      ],
    };
    state.current = {
      ...state.current,
      messages: [...(state.current.messages as Json[]), user, reply],
    };
    return route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { delta: `Reply ${sent.length} ` },
        { delta: "[[L1]]" },
        { done: true, message: reply },
      ]),
    });
  });
  await page.goto("/#/session/review-ui");
  const panel = page.getByRole("tabpanel", { name: "Review" });
  await expect(
    panel.getByRole("button", { name: "Overall 5.5" }),
  ).toBeVisible();
  const chips = await panel.locator(".score-chip").allInnerTexts();
  expect(chips.slice(0, 8)).toEqual([
    "Overall 5.5",
    "Clarity 6.5",
    "Structure 6.0",
    "Conciseness 4.0",
    "Technical accuracy 7.0",
    "Technical coverage 3.0",
    "Handling uncertainty 6.0",
    "Playfulness 6.5",
  ]);
  await expect(
    panel.getByRole("button", { name: "Structure 6.0" }),
  ).toHaveAttribute("title", "The backend arrived late.");
  await panel.getByRole("button", { name: "Structure 6.0" }).click();
  await expect(panel.getByText("The backend arrived late.")).toBeVisible();
  await expect(
    panel.getByText("Coaching estimates, not measurements."),
  ).toBeVisible();
  await expect(
    panel.getByText("Most of the time went before the backend."),
  ).toBeVisible();
  await expect(
    panel.getByRole("heading", { name: "For attempt 2" }),
  ).toBeVisible();
  await expect(panel.getByText("Name 3 concrete decisions")).toBeVisible();
  const before = await panel.innerText();
  const chat = page.getByRole("region", { name: "Coach chat" });
  const composer = chat.getByPlaceholder(
    "Ask about your attempt or the topic…",
  );
  for (let n = 1; n <= 10; n++) {
    await composer.fill(`Question ${n}`);
    await chat.getByRole("button", { name: "Send message" }).click();
    await expect(
      chat
        .locator(".message.coach:not(.streaming)")
        .filter({ hasText: new RegExp(`^Reply ${n} 0:00$`) }),
    ).toBeVisible();
    await expect(composer).toBeEnabled();
  }
  expect(sent[0]).toEqual({ message: "Question 1", attempt_number: 1 });
  expect(await panel.innerText()).toBe(before);
  // The review message stays first however long the chat grows.
  await expect(chat.locator(".message").first()).toContainText(
    "Your aside landed",
  );
});

test("coach messages render headings, bold and lists, never raw HTML", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const text = "## Three priorities\n\n1. **Lead** with the definition at ";
  const rest =
    '.\n2. Close with a summary.\n\n- One bullet\n\n<script>window.__md = 1</script> <img src=x onerror="window.__md = 2"> stays text.';
  const markdownReview = {
    ...reviewMessage,
    content: `${text}[[L3]]${rest}`,
    parts: [
      { type: "text", text },
      { type: "ref", line_id: "L3", start: 84, quote: "" },
      { type: "text", text: rest },
    ],
  };
  await serve(page, { current: session({ messages: [markdownReview] }) });
  await page.goto("/#/session/review-ui");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await expect(
    chat.getByRole("heading", { name: "Three priorities" }),
  ).toBeVisible();
  await expect(chat.locator("strong", { hasText: "Lead" })).toBeVisible();
  const items = chat.locator("ol > li");
  await expect(items).toHaveCount(2);
  // Tailwind's reset hides list markers; coach lists show their numbers and bullets.
  expect(
    await items.first().evaluate((el) => getComputedStyle(el).listStyleType),
  ).toBe("decimal");
  expect(
    await chat
      .locator("ul > li")
      .evaluate((el) => getComputedStyle(el).listStyleType),
  ).toBe("disc");
  await expect(
    items.first().getByRole("button", { name: "1:24" }),
  ).toBeVisible();
  await expect(chat.locator("ul > li")).toHaveText("One bullet");
  await expect(chat.getByText("## Three priorities")).toHaveCount(0);
  await expect(chat.getByText("**Lead**")).toHaveCount(0);
  await expect(
    chat.getByText("<script>window.__md = 1</script>", { exact: false }),
  ).toBeVisible();
  await expect(chat.locator("script, img")).toHaveCount(0);
  // A review that opens with a heading starts flush with the top of its bubble.
  expect(
    await chat
      .locator(".md-heading")
      .evaluate((el) => getComputedStyle(el).marginTop),
  ).toBe("0px");
  await page.screenshot({
    path: "test-results/review-markdown-desktop.png",
    fullPage: true,
  });
  expect(await page.evaluate(() => (window as { __md?: number }).__md)).toBe(
    undefined,
  );
  expect(errors).toEqual([]);
});

test("chat shows the server's refusal while the coach is busy", async ({
  page,
}) => {
  await serve(page, { current: session() });
  await page.route("**/api/sessions/review-ui/chat", (route) =>
    route.fulfill({
      status: 409,
      json: { detail: "The coach is already answering. Try again shortly." },
    }),
  );
  await page.goto("/#/session/review-ui");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await chat
    .getByPlaceholder("Ask about your attempt or the topic…")
    .fill("Hi");
  await chat.getByRole("button", { name: "Send message" }).click();
  await expect(chat.getByRole("alert")).toContainText(
    "The coach is already answering. Try again shortly.",
  );
  // The question never reached the coach, so it is back in the box to send again.
  const box = chat.getByPlaceholder("Ask about your attempt or the topic…");
  await expect(box).toHaveValue("Hi");
});

test("a chat question survives a failed connection but not a stored one", async ({
  page,
}) => {
  await serve(page, { current: session() });
  let mode: "abort" | "stream-error" = "abort";
  await page.route("**/api/sessions/review-ui/chat", (route) =>
    mode === "abort"
      ? route.abort("connectionrefused")
      : route.fulfill({
          contentType: "text/event-stream",
          body: sse([{ error: "The local model did not respond." }]),
        }),
  );
  await page.goto("/#/session/review-ui");
  const chat = page.getByRole("region", { name: "Coach chat" });
  const box = chat.getByPlaceholder("Ask about your attempt or the topic…");
  await box.fill("Why hash the key?");
  await chat.getByRole("button", { name: "Send message" }).click();
  await expect(chat.getByRole("alert")).toContainText(
    "local server could not be reached",
  );
  await expect(box).toHaveValue("Why hash the key?");
  // An error inside the stream comes after the question was stored: the box stays empty.
  mode = "stream-error";
  await chat.getByRole("button", { name: "Send message" }).click();
  await expect(chat.getByRole("alert")).toContainText(
    "The local model did not respond.",
  );
  await expect(box).toHaveValue("");
});

test("phone width shows chat with transcript and review sheet", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await serve(page, { current: session() });
  await page.goto("/#/session/review-ui");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await expect(
    chat.getByPlaceholder("Ask about your attempt or the topic…"),
  ).toBeVisible();
  await expect(page.getByRole("tab", { name: "Review" })).toHaveCount(0);
  await page.getByRole("button", { name: "Transcript & review" }).click();
  await expect(page.getByRole("tab", { name: "Review" })).toBeVisible();
  await expect(
    page
      .getByRole("tabpanel", { name: "Review" })
      .getByText("Most of the time went before the backend."),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Close transcript and review" })
    .click();
  await expect(page.getByRole("tab", { name: "Review" })).toHaveCount(0);
  // A time link opens the sheet on the transcript.
  await chat.getByRole("button", { name: "1:24" }).click();
  await expect(
    page
      .getByRole("tabpanel", { name: "Transcript" })
      .locator('[data-line="L3"]'),
  ).toHaveClass(/highlight/);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "test-results/review-mobile.png",
    fullPage: true,
  });
});

test("day 2 screen shows only topic, prompt and checklist", async ({
  page,
}) => {
  await serve(page, { current: session({ stage: "record2" }) });
  await page.goto("/#/session/review-ui");
  await expect(
    page.getByRole("heading", { name: "Authentication vs. authorization" }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Explain the difference between authentication and authorization.",
    ),
  ).toBeVisible();
  await expect(
    page.getByText("Answer the question in 15 seconds"),
  ).toBeVisible();
  await expect(page.getByText("Name 3 concrete decisions")).toBeVisible();
  await expect(
    page.getByText("Most of the time went before the backend."),
  ).toHaveCount(0);
  await expect(page.getByText("Your aside landed")).toHaveCount(0);
  await expect(page.getByText("Overall 5.5")).toHaveCount(0);
  await expect(
    page.getByPlaceholder("Ask about your attempt or the topic…"),
  ).toHaveCount(0);
  await expect(page.getByText("CURATED REFERENCES")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
  // The attempt 1 review stays closed while attempt 2 is being recorded.
  await expect(page.getByRole("button", { name: /Review$/ })).toBeDisabled();
});

test("legacy attempt shows old summary and re-review button", async ({
  page,
}) => {
  await serve(page, {
    current: session({
      stage: "review2",
      completed_at: "2026-10-01T12:00:00Z",
      attempts: [
        attempt({
          number: 1,
          lines: null,
          tokens: null,
          analysis: null,
          note_state: "legacy",
          segments: [{ start: 0, end: 3, text: "Login gives access." }],
          transcript: "Login gives access.",
        }),
        attempt({
          id: "attempt-2",
          number: 2,
          lines: null,
          tokens: null,
          analysis: null,
          note_state: "legacy",
          transcript: "Login proves who you are.",
          assessment: {
            summary: "A clearer second explanation from the old coach.",
            concepts: [
              {
                concept_id: "identity-check",
                status: "correct",
                evidence: "proves who you are",
                feedback: "Good.",
              },
            ],
            next_steps: ["Explain permissions."],
            communication: [],
            rubric: "Old rubric",
            model: "old-model",
          },
        }),
      ],
      messages: [],
    }),
  });
  let rereviewed = 0;
  await page.route("**/api/attempts/attempt-2/rereview", (route) => {
    rereviewed++;
    return route.fulfill({ json: { status: "pending" } });
  });
  await page.goto("/#/session/review-ui");
  const panel = page.getByRole("tabpanel", { name: "Review" });
  await expect(
    panel.getByText("A clearer second explanation from the old coach."),
  ).toBeVisible();
  await expect(panel.getByText("Identity check")).toBeVisible();
  await expect(panel.getByText("Demonstrated")).toBeVisible();
  await panel
    .getByRole("button", { name: "Re-review with the new coach" })
    .click();
  await expect.poll(() => rereviewed).toBe(1);
  await page.getByRole("tab", { name: "Transcript" }).click();
  await expect(
    page.getByRole("tabpanel", { name: "Transcript" }),
  ).toContainText("Login proves who you are.");
});

test("a streaming reply shows markers as an ellipsis until it is done", async ({
  page,
}) => {
  await serve(page, { current: session() });
  // Controllable stream: the reply pauses mid-marker until the test releases it.
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      if (!String(input).endsWith("/chat")) return original(input, init);
      const encoder = new TextEncoder();
      const w = window as unknown as { release?: () => void };
      const body = new ReadableStream({
        start(controller) {
          const send = (event: object) =>
            controller.enqueue(
              encoder.encode("data: " + JSON.stringify(event) + "\n\n"),
            );
          send({ delta: "See " });
          // A marker split across chunks, and an event split across reads.
          controller.enqueue(encoder.encode('data: {"delta": "[[L'));
          controller.enqueue(encoder.encode('3"}\n\n'));
          w.release = () => {
            send({ delta: ' and [[L1:"the app"]] too.' });
            send({
              done: true,
              message: {
                id: 99,
                role: "assistant",
                content: "",
                created_at: "2026-11-16T12:10:00Z",
                attempt_number: 1,
                kind: "chat",
                parts: [{ type: "text", text: "Final reply." }],
              },
            });
            controller.close();
          };
        },
      });
      return new Response(body, {
        headers: { "Content-Type": "text/event-stream" },
      });
    };
  });
  await page.goto("/#/session/review-ui");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await chat
    .getByPlaceholder("Ask about your attempt or the topic…")
    .fill("Hi");
  await chat.getByRole("button", { name: "Send message" }).click();
  const streaming = chat.locator(".message.streaming");
  await expect(streaming).toHaveText("See …");
  await page.evaluate(() =>
    (window as unknown as { release: () => void }).release(),
  );
  await expect(streaming).toHaveCount(0);
  await expect(
    chat.getByPlaceholder("Ask about your attempt or the topic…"),
  ).toBeEnabled();
});

test("attempt 2 review shows score changes and chats about attempt 2 only", async ({
  page,
}) => {
  const second = attempt(
    { id: "attempt-2", number: 2 },
    {
      review: {
        ...review,
        checklist: ["Lead with the answer"],
        comparison: {
          changes: [{ name: "Structure", before: 6, after: 8 }],
          what_changed: "The backend came up in the first minute this time.",
        },
      },
    },
  );
  const state = {
    current: session({
      stage: "review2",
      attempts: [attempt(), second],
      messages: [
        reviewMessage,
        {
          ...reviewMessage,
          id: 2,
          attempt_number: 2,
          content: "Attempt two review.",
          parts: [{ type: "text", text: "Attempt two review." }],
        },
      ],
    }),
  };
  await serve(page, state);
  const sent: Json[] = [];
  await page.route("**/api/sessions/review-ui/chat", (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { delta: "Ok." },
        {
          done: true,
          message: {
            id: 3,
            role: "assistant",
            content: "Ok.",
            created_at: "2026-11-17T12:00:00Z",
            attempt_number: 2,
            kind: "chat",
            parts: [{ type: "text", text: "Ok." }],
          },
        },
      ]),
    });
  });
  await page.goto("/#/session/review-ui");
  const panel = page.getByRole("tabpanel", { name: "Review" });
  await expect(panel.getByText("Structure 6.0 → 8.0")).toBeVisible();
  await expect(
    panel.getByText("The backend came up in the first minute this time."),
  ).toBeVisible();
  await expect(
    panel.getByRole("heading", { name: "For next time" }),
  ).toBeVisible();
  await expect(panel.getByText("Lead with the answer")).toBeVisible();
  const chat = page.getByRole("region", { name: "Coach chat" });
  await expect(chat.getByText("Attempt two review.")).toBeVisible();
  await expect(chat.getByText("Your aside landed")).toHaveCount(0);
  await chat
    .getByPlaceholder("Ask about your attempt or the topic…")
    .fill("Why?");
  await chat.getByRole("button", { name: "Send message" }).click();
  await expect
    .poll(() => sent)
    .toEqual([{ message: "Why?", attempt_number: 2 }]);
});

test("a long review keeps the page at the top on load and when the review arrives", async ({
  page,
}) => {
  const long = "A long paragraph of review prose for this attempt. ".repeat(
    400,
  );
  const waiting = session({
    attempts: [
      attempt(
        { status: "processing" },
        { review: null, passes: { ...donePasses(), writer: pass("running") } },
      ),
    ],
    messages: [],
  });
  const state = { current: waiting };
  await serve(page, state);
  await page.goto("/#/session/review-ui");
  const heading = page.getByRole("heading", {
    name: "Authentication vs. authorization",
  });
  await expect(heading).toBeInViewport();
  await expect(page.getByText("Writing your review…").first()).toBeVisible();
  // The writer finishes; polling brings the long review in.
  state.current = session({
    messages: [
      {
        ...reviewMessage,
        content: long,
        parts: [{ type: "text", text: long }],
      },
    ],
  });
  await expect(page.locator(".message.review")).toBeVisible({
    timeout: 10000,
  });
  await expect(heading).toBeInViewport();
  await page.reload();
  await expect(page.locator(".message.review")).toBeVisible();
  await expect(heading).toBeInViewport();
});

test("after attempt 2 the switch reaches attempt 1's review, but not while recording attempt 2", async ({
  page,
}) => {
  const second = attempt(
    { id: "attempt-2", number: 2 },
    {
      review: {
        ...review,
        key_points: [
          { text: "Second attempt key point.", line_ids: [] },
          ...review.key_points.slice(1),
        ],
        comparison: {
          changes: [{ name: "Structure", before: 6, after: 8 }],
          what_changed: "Clearer this time.",
        },
      },
    },
  );
  const messages = [
    reviewMessage,
    {
      ...reviewMessage,
      id: 2,
      attempt_number: 2,
      content: "Attempt two review.",
      parts: [{ type: "text", text: "Attempt two review." }],
    },
  ];
  const state = {
    current: session({
      stage: "review2",
      attempts: [attempt(), second],
      messages,
    }),
  };
  await serve(page, state);
  const panel = page.getByRole("tabpanel", { name: "Review" });
  const chat = page.getByRole("region", { name: "Coach chat" });
  for (const completed of [null, "2026-11-17T12:00:00Z"]) {
    state.current = { ...state.current, completed_at: completed };
    await page.goto("/#/session/review-ui");
    await page.reload();
    await expect(
      page.getByRole("button", { name: "Attempt 2" }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(panel.getByText("Second attempt key point.")).toBeVisible();
    await expect(chat.getByText("Attempt two review.")).toBeVisible();
    await page.getByRole("button", { name: "Attempt 1" }).click();
    await expect(
      panel.getByRole("heading", { name: "For attempt 2" }),
    ).toBeVisible();
    await expect(
      panel.getByText("Most of the time went before the backend."),
    ).toBeVisible();
    await expect(chat.getByText("Your aside landed")).toBeVisible();
    await expect(chat.getByText("Attempt two review.")).toHaveCount(0);
  }
  state.current = session({
    stage: "record2",
    attempts: [attempt()],
    messages,
  });
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Attempt 1" })).toHaveCount(0);
  await expect(
    page.getByText("Most of the time went before the backend."),
  ).toHaveCount(0);
  await expect(page.getByText("Your aside landed")).toHaveCount(0);
});

test("the stepper offers attempt 2's recorder only before attempt 2 is saved", async ({
  page,
}) => {
  const state = {
    current: session({
      stage: "review2",
      attempts: [
        attempt(),
        attempt(
          { id: "attempt-2", number: 2, note_state: "pending" },
          {
            review: null,
            passes: { ...donePasses(), writer: pass("waiting") },
          },
        ),
      ],
    }),
  };
  await serve(page, state);
  await page.goto("/#/session/review-ui");
  const stages = page.getByRole("navigation", { name: "Practice stages" });
  await expect(
    stages.getByRole("button", { name: /Review again/ }),
  ).toBeEnabled();
  await expect(
    stages.getByRole("button", { name: /Try again/ }),
  ).toBeDisabled();
  state.current = session({ stage: "review1" });
  await page.reload();
  await expect(stages.getByRole("button", { name: /Try again/ })).toBeEnabled();
});

test("a too-short attempt 1 can be recorded again; a too-short attempt 2 cannot", async ({
  page,
}) => {
  const skipped = pass("skipped");
  const tooShort = {
    review: { too_short: true },
    technical: null,
    passes: {
      memory: skipped,
      technical: skipped,
      communication: skipped,
      writer: skipped,
    },
  };
  const state = {
    current: session({ attempts: [attempt({}, tooShort)], messages: [] }),
  };
  await serve(page, state);
  const bodies: Json[] = [];
  await page.route("**/api/sessions/review-ui/stage", (route) => {
    bodies.push(route.request().postDataJSON());
    state.current = { ...state.current, stage: "record1" };
    return route.fulfill({ json: state.current });
  });
  await page.goto("/#/session/review-ui");
  await page.getByRole("button", { name: "Record again" }).click();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
  expect(bodies).toEqual([{ stage: "record1" }]);

  state.current = session({
    stage: "review2",
    completed_at: "2026-11-17T12:00:00Z",
    attempts: [attempt(), attempt({ id: "attempt-2", number: 2 }, tooShort)],
    messages: [],
  });
  await page.reload();
  await expect(
    page.getByText("No substantive explanation was recorded for this attempt."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Record again" })).toHaveCount(
    0,
  );
});

test("earlier versions stay viewable after re-review and on normal attempts", async ({
  page,
}) => {
  const legacy = attempt({
    lines: null,
    tokens: null,
    analysis: null,
    note_state: "legacy",
    assessment: {
      summary: "Old coach summary.",
      concepts: [],
      next_steps: [],
      communication: [],
      rubric: "Old rubric",
      model: "old-model",
    },
  });
  const state = { current: session({ attempts: [legacy], messages: [] }) };
  await serve(page, state);
  await page.route("**/api/attempts/attempt-1/rereview", (route) => {
    state.current = session({
      attempts: [attempt({ note_state: "skipped" })],
    });
    return route.fulfill({ json: { status: "pending" } });
  });
  await page.route("**/api/attempts/attempt-1/analysis-history", (route) =>
    route.fulfill({
      json: [
        {
          id: 1,
          created_at: "2026-11-16T12:00:00Z",
          attempt: { ...legacy, transcript: "Archived transcript." },
        },
      ],
    }),
  );
  await page.goto("/#/session/review-ui");
  const panel = page.getByRole("tabpanel", { name: "Review" });
  await panel
    .getByRole("button", { name: "Re-review with the new coach" })
    .click();
  // The attempt is no longer legacy, but its archived analysis stays reachable.
  await expect(
    panel.getByText("Most of the time went before the backend."),
  ).toBeVisible();
  await panel
    .getByText("Earlier versions and re-review", { exact: true })
    .click();
  await panel.getByRole("button", { name: "View previous analyses" }).click();
  await panel.getByText(/Saved before re-review/).click();
  await expect(panel.getByText("Archived transcript.")).toBeVisible();
  await expect(
    panel.getByText("Old coach summary.", { exact: true }),
  ).toBeVisible();

  // A normal attempt offers the same viewer and a re-review, collapsed.
  state.current = session();
  await page.reload();
  await expect(
    panel.getByRole("button", { name: "Re-review this attempt" }),
  ).toBeHidden();
  await panel
    .getByText("Earlier versions and re-review", { exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Re-review this attempt" }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "View previous analyses" }),
  ).toBeVisible();
});

test("leaving mid-reply keeps the newly opened session on screen", async ({
  page,
}) => {
  await serve(page, { current: session() });
  await page.route("**/api/sessions/other-session", (route) =>
    route.fulfill({
      json: session({
        id: "other-session",
        topic: {
          id: "hash-maps",
          title: "Hash maps",
          category: "Data structures",
          difficulty: "beginner",
          prompt: "Explain a hash map.",
        },
        attempts: [attempt({ session_id: "other-session" })],
        messages: [],
      }),
    }),
  );
  let release!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  let chatDone = false;
  await page.route("**/api/sessions/review-ui/chat", async (route) => {
    await gate;
    await route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { delta: "Late reply." },
        {
          done: true,
          message: {
            id: 50,
            role: "assistant",
            content: "Late reply.",
            created_at: "2026-11-17T12:00:00Z",
            attempt_number: 1,
            kind: "chat",
            parts: [{ type: "text", text: "Late reply." }],
          },
        },
      ]),
    });
    chatDone = true;
  });
  await page.goto("/#/session/review-ui");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await chat
    .getByPlaceholder("Ask about your attempt or the topic…")
    .fill("Hi");
  await chat.getByRole("button", { name: "Send message" }).click();
  await page.evaluate(() => (location.hash = "#/session/other-session"));
  await expect(page.getByRole("heading", { name: "Hash maps" })).toBeVisible();
  release();
  await expect.poll(() => chatDone).toBe(true);
  await page.waitForTimeout(500);
  await expect(page.getByRole("heading", { name: "Hash maps" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Authentication vs. authorization" }),
  ).toHaveCount(0);
  expect(page.url()).toContain("#/session/other-session");
});

const passNames = ["technical", "communication", "writer", "chat", "memory"];
async function mockModels(page: Page, selected = "qwen3.5:9b-q4_K_M") {
  await page.route("**/api/models", (route) =>
    route.fulfill({
      json: {
        selected,
        models: ["qwen3.5:9b-q4_K_M", "gemma4:e4b"].map((name) => ({
          name,
          parameters: "9B",
          quantization: "Q4_K_M",
          size_bytes: 6000000000,
          selectable: true,
          reason: null,
        })),
      },
    }),
  );
}

test("today lists second attempts and opens tomorrow label", async ({
  page,
}) => {
  let stageBody: Json | null = null;
  const topic = (id: string, title: string) => ({
    id,
    title,
    category: "Systems",
    difficulty: "Intermediate",
    prompt: "Explain it.",
  });
  await page.route("**/api/attempt2", (route) =>
    route.fulfill({
      json: [
        {
          session_id: "a2-ready",
          topic: topic("t1", "Hash maps"),
          attempt2_after: "2026-11-16",
          available: true,
        },
        {
          session_id: "a2-later",
          topic: topic("t2", "Caching"),
          attempt2_after: "2026-11-18",
          available: false,
        },
      ],
    }),
  );
  await page.route("**/api/sessions/a2-ready/stage", (route) => {
    stageBody = route.request().postDataJSON();
    return route.fulfill({
      status: 409,
      json: {
        detail: "Attempt 2 opens tomorrow so it tests what you remember.",
      },
    });
  });
  await page.goto("/#/today");
  const list = page.getByRole("region", { name: "Second attempts" });
  await expect(list.getByText("Hash maps")).toBeVisible();
  await expect(list.getByText("Caching")).toBeVisible();
  await expect(list.getByText("Opens tomorrow")).toHaveCount(1);
  await expect(
    list.getByRole("button", { name: "Record attempt 2" }),
  ).toHaveCount(1);
  await list.getByRole("button", { name: "Record attempt 2" }).click();
  expect(stageBody).toEqual({ stage: "record2" });
  await expect(page.getByRole("alert")).toContainText(
    "Attempt 2 opens tomorrow",
  );
});

test("the in-progress banner leaves out sessions whose attempt 2 is open", async ({
  page,
}) => {
  const item = (
    id: string,
    title: string,
    stage: string,
    attempt2_after: string | null,
  ) => ({
    id,
    topic: {
      id,
      title,
      category: "Systems",
      difficulty: "Intermediate",
      prompt: "Explain it.",
    },
    created_at: "2026-11-15T12:00:00Z",
    completed_at: null,
    review_due: null,
    attempt_count: 1,
    stage,
    attempt2_after,
    coverage: [],
  });
  let sessions = [
    item("open-a2", "Hash maps", "review1", "2000-01-01"),
    item("recording-a2", "Queues", "record2", "2000-01-01"),
    item("day-one", "Caching", "review1", "2999-01-01"),
  ];
  await page.route("**/api/sessions", (route) =>
    route.fulfill({ json: sessions }),
  );
  await page.route("**/api/attempt2", (route) => route.fulfill({ json: [] }));
  await page.goto("/#/today");
  const banner = page.locator(".resume-banner");
  // Day 1: attempt 2 isn't open yet, so the banner still leads back to the review.
  await expect(banner).toContainText("Caching");
  sessions = sessions.slice(0, 2);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Today’s practice" }),
  ).toBeVisible();
  // Day 2: the attempt 1 review would undo the recall test; "Record attempt 2" is the way in.
  await expect(banner).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Continue session/ }),
  ).toHaveCount(0);
});

test("per-pass model selects save", async ({ page }) => {
  let busy = true;
  let saved: Json | null = null;
  let singleCalls = 0;
  let passGets = 0;
  const current: Json = Object.fromEntries(
    passNames.map((p) => [
      p,
      {
        model: "qwen3.5:9b-q4_K_M",
        num_ctx: 8192,
        num_predict: p === "writer" ? 4096 : 2048,
      },
    ]),
  );
  await mockModels(page);
  await page.route("**/api/settings/model", (route) => {
    singleCalls++;
    return route.fulfill({
      json: { selected: route.request().postDataJSON().model },
    });
  });
  await page.route("**/api/settings/passes", (route) => {
    if (route.request().method() === "GET") {
      passGets++;
      return route.fulfill({ json: current });
    }
    if (busy)
      return route.fulfill({
        status: 409,
        json: {
          detail:
            "Wait for recording analysis to finish before changing models.",
        },
      });
    saved = route.request().postDataJSON();
    return route.fulfill({ json: (saved as Json).passes });
  });
  await page.goto("/#/settings");
  await page.getByText("Advanced: model per step").click();
  for (const label of [
    "Technical review",
    "Communication review",
    "Review writer",
    "Chat",
    "Coach notes",
  ])
    await expect(page.getByRole("combobox", { name: label })).toHaveValue(
      "qwen3.5:9b-q4_K_M",
    );
  await page
    .getByRole("combobox", { name: "Review writer" })
    .selectOption("gemma4:e4b");
  await page.getByRole("button", { name: "Save step models" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Wait for recording analysis",
  );
  busy = false;
  await page.getByRole("button", { name: "Save step models" }).click();
  await expect(page.getByText("Step models saved")).toBeVisible();
  const passes = (saved as unknown as { passes: Record<string, Json> }).passes;
  expect(passes.writer).toEqual({
    model: "gemma4:e4b",
    num_ctx: 8192,
    num_predict: 4096,
  });
  expect(passes.technical.model).toBe("qwen3.5:9b-q4_K_M");
  // the single picker uses one request; the server sets all five steps
  saved = null;
  for (const p of passNames) (current[p] as Json).model = "gemma4:e4b";
  const getsBefore = passGets;
  await page
    .getByRole("combobox", { name: "Model for feedback & coaching" })
    .selectOption("gemma4:e4b");
  await page.getByRole("button", { name: "Use model", exact: true }).click();
  await expect(page.getByText("Model saved.")).toBeVisible();
  expect(singleCalls).toBe(1);
  expect(saved).toBeNull();
  expect(passGets).toBeGreaterThan(getsBefore);
  for (const label of ["Technical review", "Review writer", "Coach notes"])
    await expect(page.getByRole("combobox", { name: label })).toHaveValue(
      "gemma4:e4b",
    );
});

test("each step's context size and output limit can be changed", async ({
  page,
}) => {
  let saved: Json | null = null;
  const current: Json = Object.fromEntries(
    passNames.map((p) => [
      p,
      {
        model: "qwen3.5:9b-q4_K_M",
        num_ctx: 8192,
        num_predict: p === "writer" ? 4096 : 2048,
      },
    ]),
  );
  await mockModels(page);
  await page.route("**/api/settings/passes", (route) => {
    if (route.request().method() === "GET")
      return route.fulfill({ json: current });
    saved = route.request().postDataJSON();
    return route.fulfill({ json: (saved as Json).passes });
  });
  await page.goto("/#/settings");
  await page.getByText("Advanced: model per step").click();
  // The coach and chat replaced the tutor; Settings says so.
  await expect(
    page.getByRole("heading", { name: "Coach", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/tutor/i)).toHaveCount(0);
  const context = page.getByRole("spinbutton", {
    name: "Review writer context size",
  });
  const output = page.getByRole("spinbutton", {
    name: "Review writer output limit",
  });
  await expect(context).toHaveValue("8192");
  await expect(output).toHaveValue("4096");
  const save = page.getByRole("button", { name: "Save step models" });
  await expect(save).toBeDisabled();
  await context.fill("99999");
  await expect(save).toBeDisabled();
  await expect(page.getByText("Context size: 4096 to 32768")).toBeVisible();
  await context.fill("");
  await expect(save).toBeDisabled();
  await context.fill("16384");
  await page
    .getByRole("spinbutton", { name: "Chat output limit" })
    .fill("1024");
  await save.click();
  await expect(page.getByText("Step models saved")).toBeVisible();
  const passes = (saved as unknown as { passes: Record<string, Json> }).passes;
  expect(passes.writer).toEqual({
    model: "qwen3.5:9b-q4_K_M",
    num_ctx: 16384,
    num_predict: 4096,
  });
  expect(passes.chat).toEqual({
    model: "qwen3.5:9b-q4_K_M",
    num_ctx: 8192,
    num_predict: 1024,
  });
});

test("coach notes edit, over-limit warning, restore", async ({ page }) => {
  let content = "Focus: clarity.";
  let versions = [
    {
      id: 2,
      content: "Focus: clarity.",
      created_at: "2026-11-16T10:00:00Z",
      source: "memory",
      model: "qwen3.5:9b-q4_K_M",
      folded_attempt_ids: [],
    },
    {
      id: 1,
      content: "Focus: structure.",
      created_at: "2026-11-15T10:00:00Z",
      source: "learner",
      model: null,
      folded_attempt_ids: [],
    },
  ];
  // The real GET, PUT and restore responses: the current version plus every version.
  const view = () => ({
    current: { id: versions[0].id, content, model: versions[0].model },
    versions,
  });
  let putBody: Json | null = null;
  await mockModels(page);
  await page.route("**/api/coach-notes", (route) => {
    if (route.request().method() === "PUT") {
      putBody = route.request().postDataJSON();
      content = (putBody as Json).content as string;
      versions = [
        {
          id: 3,
          content,
          created_at: "2026-11-17T10:00:00Z",
          source: "learner",
          model: null,
          folded_attempt_ids: [],
        },
        ...versions,
      ];
    }
    return route.fulfill({ json: view() });
  });
  await page.route("**/api/coach-notes/*/restore", (route) => {
    content = "Focus: structure.";
    versions = [
      {
        id: 4,
        content,
        created_at: "2026-11-17T11:00:00Z",
        source: "restore",
        model: null,
        folded_attempt_ids: [],
      },
      ...versions,
    ];
    return route.fulfill({ json: view() });
  });
  await page.goto("/#/settings");
  const region = page.getByRole("region", {
    name: "What your coach remembers",
  });
  await expect(region.getByText("Focus: clarity.").first()).toBeVisible();
  await region.getByRole("button", { name: "Edit" }).click();
  // Restoring while a draft is open would leave the draft over the restored notes.
  await region.getByText("Previous versions").click();
  const restores = region.getByRole("button", { name: "Restore" });
  await expect(restores).toHaveCount(2);
  await expect(restores.first()).toBeDisabled();
  await expect(restores.last()).toBeDisabled();
  await region.getByText("Previous versions").click();
  const box = region.getByRole("textbox");
  await box.fill(Array(401).fill("word").join(" "));
  await expect(region.getByText("401 / 400 words")).toBeVisible();
  await expect(region.getByTestId("word-count")).toHaveClass(/over/);
  await expect(region.getByRole("button", { name: "Save" })).toBeDisabled();
  await box.fill("Focus: pacing.");
  await expect(region.getByText("2 / 400 words")).toBeVisible();
  await region.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => putBody).toEqual({ content: "Focus: pacing." });
  await region.getByText("Previous versions").click();
  await expect(region.getByText(/learner/).first()).toBeVisible();
  await region.getByRole("button", { name: "Restore" }).last().click();
  await expect(region.getByText("Focus: structure.").first()).toBeVisible();
  await region.getByRole("button", { name: "Edit" }).click();
  await region.getByRole("button", { name: "Cancel" }).click();
  await expect(region.getByRole("textbox")).toHaveCount(0);
});

test("today second attempts shows load error with retry", async ({ page }) => {
  let fail = true;
  await page.route("**/api/attempt2", (route) =>
    fail
      ? route.fulfill({ status: 500, json: { detail: "Queue unavailable." } })
      : route.fulfill({
          json: [
            {
              session_id: "a2",
              topic: {
                id: "t1",
                title: "Hash maps",
                category: "Systems",
                difficulty: "Intermediate",
                prompt: "Explain it.",
              },
              attempt2_after: "2026-11-16",
              available: true,
            },
          ],
        }),
  );
  await page.goto("/#/today");
  const list = page.getByRole("region", { name: "Second attempts" });
  await expect(list.getByRole("alert")).toContainText("Queue unavailable.");
  fail = false;
  await list.getByRole("button", { name: "Retry" }).click();
  await expect(list.getByText("Hash maps")).toBeVisible();
  await expect(list.getByRole("alert")).toHaveCount(0);
});
