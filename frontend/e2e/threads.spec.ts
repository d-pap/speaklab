import { expect, test, type Request } from "@playwright/test";
import {
  attempt,
  emptyThread,
  authPrompts,
  authTopic,
  historyRow,
  message,
  mockLists,
  pass,
  readyRow,
  review,
  serve,
  SESSION_ID,
  sse,
  thread,
  topic,
  wav,
  type Json,
} from "./fixtures";

const caching = topic(
  "caching",
  "Caching",
  "Engineering decisions and trade-offs",
  "intermediate",
  "Explain when a cache helps, what makes it difficult, and how you would choose an expiration strategy.",
);
const hashMaps = topic(
  "hash-maps",
  "Hash maps",
  "Data structures and algorithms",
  "beginner",
  "How does a hash map find a value so quickly? Explain it with a practical example.",
);
const rag = topic(
  "rag",
  "Retrieval-augmented generation",
  "AI and machine learning",
  "advanced",
  "Walk through a RAG system from user question to answer. Explain where it can fail.",
);

const fields = (request: Request) => {
  const body = request.postDataBuffer()?.toString("latin1") ?? "";
  const names = [...body.matchAll(/; name="([^"]+)"/g)].map((m) => m[1]);
  const value = (name: string) =>
    body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]*)`))?.[1];
  return { names, value };
};

test("practised topic opens its topic page, never attempt 1", async ({
  page,
}) => {
  const uploads: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/attempts"))
      uploads.push(r.url());
  });
  await mockLists(page, {
    history: [
      historyRow(authTopic, { session_id: SESSION_ID, can_record: false }),
    ],
    recommend: (include) =>
      include
        ? {
            topic: authTopic,
            practised: true,
            reason: "Room to deepen your understanding",
          }
        : {
            topic: rag,
            practised: false,
            reason: "A fresh perspective for your next practice",
          },
  });
  await serve(page, { current: thread() });
  // The library leaves practised topics out until they are included.
  await page.goto("/#/topics");
  const authTile = page.getByRole("button", {
    name: /Authentication vs\. authorization/,
  });
  await expect(page.getByRole("button", { name: /Hash maps/ })).toBeVisible();
  await expect(authTile).toHaveCount(0);
  await page.getByRole("button", { name: "Include practised" }).click();
  await authTile.click();
  await expect(authTile).toContainText("Practised");
  await page.getByRole("button", { name: "Open topic" }).click();
  await expect(page).toHaveURL(/#\/topic\/auth$/);
  await expect(page.getByRole("button", { name: "Attempt 1" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    page
      .getByRole("tabpanel", { name: "Review" })
      .getByText("Most of the time went before the backend."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toHaveCount(0);

  // Today's suggestion of a practised topic opens the same page.
  await page.goto("/#/today");
  await page.reload();
  const suggested = page.getByRole("region", { name: "Suggested topics" });
  await expect(suggested.getByText(rag.title)).toBeVisible();
  await suggested.getByRole("button", { name: "Include practised" }).click();
  await expect(suggested.getByText(authTopic.title)).toBeVisible();
  await expect(
    suggested.getByRole("button", { name: /Begin your practice/ }),
  ).toHaveCount(0);
  await suggested.getByRole("button", { name: /Open topic/ }).click();
  await expect(page).toHaveURL(/#\/topic\/auth$/);
  await expect(page.getByRole("button", { name: "Attempt 1" })).toBeVisible();
  expect(uploads).toEqual([]);
});

test("attempt pills switch reviews and chats", async ({ page }) => {
  const second = attempt(
    { id: "attempt-2", number: 2, created_at: "2026-11-17T12:00:00Z" },
    {
      review: {
        ...review,
        key_points: [{ text: "Second attempt key point.", line_ids: [] }],
        comparison: {
          changes: [{ name: "Structure", before: 6, after: 8 }],
          what_changed: "The backend came up in the first minute.",
        },
      },
    },
  );
  const third = attempt(
    {
      id: "attempt-3",
      number: 3,
      created_at: "2026-11-18T12:00:00Z",
      prompt_kind: "Compare",
    },
    {
      review: {
        ...review,
        key_points: [{ text: "Third attempt key point.", line_ids: [] }],
        checklist: ["Lead with the answer"],
        comparison: {
          changes: [{ name: "Structure", before: 8, after: 9 }],
          what_changed:
            "The question type changed, so read this as indicative.",
        },
      },
    },
  );
  const reviewFor = (n: number, text: string) =>
    message({
      id: n,
      attempt_number: n,
      content: text,
      parts: [{ type: "text", text }],
    });
  await serve(page, {
    current: thread({
      attempts: [attempt(), second, third],
      messages: [
        reviewFor(1, "Attempt one review."),
        reviewFor(2, "Attempt two review."),
        reviewFor(3, "Attempt three review."),
      ],
      recording: {
        can_record: true,
        reason: null,
        replace_number: null,
        next_number: 4,
      },
      latest_checklist: ["Lead with the answer"],
      next_attempt_after: "2026-11-19",
    }),
  });
  const sent: Json[] = [];
  await page.route(`**/api/sessions/${SESSION_ID}/chat`, (route) => {
    const body = route.request().postDataJSON();
    sent.push(body);
    return route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { delta: "Ok." },
        {
          done: true,
          message: message({
            id: 20,
            kind: "chat",
            attempt_number: body.attempt_number,
            content: "Ok.",
            parts: [{ type: "text", text: "Ok." }],
          }),
        },
      ]),
    });
  });
  await page.goto("/#/topic/auth");
  const pills = page.getByRole("group", { name: "Choose an attempt" });
  const panel = page.getByRole("tabpanel", { name: "Review" });
  const chat = page.getByRole("region", { name: "Coach chat" });
  // The latest attempt opens first.
  await expect(pills.getByRole("button")).toHaveText([
    "Attempt 1",
    "Attempt 2",
    "Attempt 3",
  ]);
  await expect(
    pills.getByRole("button", { name: "Attempt 3" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByText("Third attempt key point.")).toBeVisible();
  await expect(
    panel.getByRole("heading", { name: "Since attempt 2" }),
  ).toBeVisible();
  await expect(
    panel.getByRole("heading", { name: "For next time" }),
  ).toBeVisible();
  await expect(chat.getByText("Attempt three review.")).toBeVisible();
  await expect(chat.getByText("Attempt one review.")).toHaveCount(0);
  await expect(page.getByText(authPrompts.Compare)).toBeVisible();
  await expect(page.getByRole("button", { name: "New attempt" })).toBeEnabled();

  await pills.getByRole("button", { name: "Attempt 1" }).click();
  await expect(page).toHaveURL(/#\/topic\/auth\?attempt=1$/);
  await expect(
    pills.getByRole("button", { name: "Attempt 1" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    panel.getByText("Most of the time went before the backend."),
  ).toBeVisible();
  await expect(
    panel.getByRole("heading", { name: "For next time" }),
  ).toBeVisible();
  await expect(chat.getByText("Attempt one review.")).toBeVisible();
  await expect(chat.getByText("Attempt three review.")).toHaveCount(0);
  await expect(
    page.getByText(authPrompts["Concept explanation"]),
  ).toBeVisible();
  await chat
    .getByPlaceholder("Ask about your attempt or the topic…")
    .fill("Why?");
  await chat.getByRole("button", { name: "Send message" }).click();
  await expect
    .poll(() => sent)
    .toEqual([{ message: "Why?", attempt_number: 1 }]);

  // A link to an attempt opens it; an unknown attempt falls back to the latest.
  await page.goto("/#/topic/auth?attempt=2");
  await expect(
    pills.getByRole("button", { name: "Attempt 2" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(chat.getByText("Attempt two review.")).toBeVisible();
  await expect(
    panel.getByRole("heading", { name: "Since attempt 1" }),
  ).toBeVisible();
  await page.goto("/#/topic/auth?attempt=9");
  await expect(
    pills.getByRole("button", { name: "Attempt 3" }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("new attempt screen hides past feedback and offers a different angle", async ({
  page,
}) => {
  const open = {
    can_record: true,
    reason: null,
    replace_number: null,
    next_number: 2,
  };
  const state = { current: thread({ recording: open }) };
  await serve(page, state);
  const uploads: Request[] = [];
  await page.route("**/api/topics/auth/attempts", (route) => {
    uploads.push(route.request());
    const { value } = fields(route.request());
    // The 201 body is the new ATTEMPT before the pipeline has run.
    const saved = attempt({
      id: "attempt-2",
      number: 2,
      created_at: "2026-11-17T12:00:00Z",
      prompt_kind: value("prompt_kind") ?? "Concept explanation",
      status: "pending",
      note_state: "pending",
      transcript: null,
      transcript_source: null,
      segments: null,
      acoustics: null,
      lines: null,
      tokens: null,
      analysis: null,
    });
    state.current = thread({
      attempts: [attempt(), { ...saved, status: "ready" }],
      recording: {
        can_record: false,
        reason: "Next attempt opens tomorrow",
        replace_number: null,
        next_number: 3,
      },
    });
    return route.fulfill({ status: 201, json: saved });
  });
  await page.goto("/#/topic/auth");
  await page.getByRole("button", { name: "New attempt" }).click();
  await expect(page).toHaveURL(/#\/topic\/auth\/new$/);
  await expect(
    page.getByRole("heading", { name: authTopic.title }),
  ).toBeVisible();
  await expect(
    page.getByText(authPrompts["Concept explanation"]),
  ).toBeVisible();
  const checklist = page.getByRole("region", { name: "For next time" });
  await expect(checklist.getByRole("listitem")).toHaveText(review.checklist);
  const angle = page.getByRole("combobox", { name: "Try a different angle" });
  await expect(angle).toHaveValue("Concept explanation");
  // No reviews, chat or references while recording.
  await expect(
    page.getByText("Most of the time went before the backend."),
  ).toHaveCount(0);
  await expect(page.getByText("Your aside landed")).toHaveCount(0);
  await expect(page.locator(".score-chip")).toHaveCount(0);
  await expect(page.getByRole("tab")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Coach chat" })).toHaveCount(0);
  await expect(page.getByText("CURATED REFERENCES")).toHaveCount(0);
  await expect(page.getByText(/This replaces attempt/)).toHaveCount(0);

  // The question follows the chosen angle; Cancel returns to the topic page.
  await angle.selectOption("Compare");
  await expect(page.getByText(authPrompts.Compare)).toBeVisible();
  await expect(page.getByText(authPrompts["Concept explanation"])).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page).toHaveURL(/#\/topic\/auth$/);
  await expect(page.getByRole("button", { name: "Attempt 1" })).toBeVisible();

  await page.getByRole("button", { name: "New attempt" }).click();
  await expect(angle).toHaveValue("Concept explanation");
  await angle.selectOption("Compare");
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "a2.wav", mimeType: "audio/wav", buffer: wav() });
  await page.getByRole("button", { name: "Save & review attempt 2" }).click();
  await expect(page).toHaveURL(/#\/topic\/auth\?attempt=2$/);
  await expect(page.getByRole("button", { name: "Attempt 2" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByText("Next attempt opens tomorrow")).toBeVisible();
  // Only the changed angle is sent; style and length carry over on the server.
  const first = fields(uploads[0]);
  expect(first.names.sort()).toEqual(["file", "prompt_kind"]);
  expect(first.value("prompt_kind")).toBe("Compare");

  // An unchanged angle is never sent, so a retired question type carries over untouched.
  const retired = attempt({
    prompt_kind: "Build a solution",
    prompt: authTopic.prompt,
  });
  state.current = thread({ attempts: [retired], recording: open });
  await page.goto("/#/topic/auth/new");
  await expect(angle).toHaveValue("");
  await expect(angle.locator("option:checked")).toHaveText(
    "Same question as last time",
  );
  await expect(page.getByText(authTopic.prompt)).toBeVisible();
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "a2.wav", mimeType: "audio/wav", buffer: wav() });
  await page.getByRole("button", { name: "Save & review attempt 2" }).click();
  await expect(page).toHaveURL(/#\/topic\/auth\?attempt=2$/);
  expect(fields(uploads[1]).names).toEqual(["file"]);

  // A too-short latest attempt is replaced, and the screen says so before recording.
  const skipped = pass("skipped");
  state.current = thread({
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
    recording: {
      can_record: true,
      reason: null,
      replace_number: 1,
      next_number: 1,
    },
    latest_checklist: [],
  });
  await page.goto("/#/topic/auth/new");
  await expect(page.getByText("This replaces attempt 1")).toBeVisible();
  await expect(page.getByRole("region", { name: "For next time" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
});

test("new attempt disabled same day with reason", async ({ page }) => {
  const state = { current: thread() };
  await serve(page, state);
  await page.route("**/api/topics/auth/attempts", (route) =>
    route.fulfill({
      status: 409,
      json: { detail: "Next attempt opens tomorrow" },
    }),
  );
  await page.goto("/#/topic/auth");
  await expect(page.getByText("Next attempt opens tomorrow")).toBeVisible();
  await expect(page.getByRole("button", { name: "New attempt" })).toHaveCount(
    0,
  );
  // A direct link to the recorder shows the topic page and the reason instead.
  await page.goto("/#/topic/auth/new");
  await expect(page.getByText("Next attempt opens tomorrow")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Attempt 1" })).toBeVisible();
  // The URL drops /new, so a later press of the button is a real navigation.
  await expect(page).toHaveURL(/#\/topic\/auth$/);
  // The server refuses a recording that raced the calendar; the recording stays.
  state.current = thread({
    recording: {
      can_record: true,
      reason: null,
      replace_number: null,
      next_number: 2,
    },
  });
  await page.goto("about:blank");
  await page.goto("/#/topic/auth/new");
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "a2.wav", mimeType: "audio/wav", buffer: wav() });
  await page.getByRole("button", { name: "Save & review attempt 2" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Next attempt opens tomorrow",
  );
  await expect(page).toHaveURL(/#\/topic\/auth\/new$/);
  await expect(
    page.getByRole("button", { name: "Save & review attempt 2" }),
  ).toBeVisible();
});

test("today suggestions exclude practised unless include practised", async ({
  page,
}) => {
  const asked: boolean[] = [];
  let allPractised = false;
  await mockLists(page, {
    history: [
      historyRow(authTopic, {
        session_id: SESSION_ID,
        attempt_count: 2,
        last_attempt_at: "2026-11-17T09:00:00+00:00",
        can_record: false,
      }),
      historyRow(caching, { last_attempt_at: "2026-10-28T09:00:00+00:00" }),
      historyRow(hashMaps, { last_attempt_at: "2026-11-04T09:00:00+00:00" }),
    ],
    ready: [
      readyRow(caching, {
        last_attempt_at: "2026-10-28T09:00:00+00:00",
        review_due: "2026-10-30",
        due: true,
      }),
      readyRow(hashMaps, {
        last_attempt_at: "2026-11-04T09:00:00+00:00",
        review_due: "2026-12-01",
        due: false,
      }),
    ],
    recommend: (include) => {
      asked.push(include);
      if (include)
        return {
          topic: caching,
          practised: true,
          reason: "Due for a memory check",
        };
      return allPractised
        ? null
        : {
            topic: rag,
            practised: false,
            reason: "A fresh perspective for your next practice",
          };
    },
  });
  await serve(page, { current: thread() });
  await page.route("**/api/topics/caching/thread", (route) =>
    route.fulfill({
      json: thread({
        topic: caching,
        attempts: [attempt({ session_id: "thread-caching" })],
        messages: [],
        session_id: "thread-caching",
      }),
    }),
  );
  await page.goto("/#/today");
  const ready = page.getByRole("region", { name: "Ready for another attempt" });
  await expect(ready.getByRole("listitem")).toHaveCount(2);
  await expect(ready.getByRole("listitem").first()).toContainText("Caching");
  await expect(ready.getByRole("listitem").first()).toContainText("due");
  await expect(ready.getByRole("listitem").last()).toContainText("Hash maps");
  await expect(ready.getByRole("listitem").last()).not.toContainText("due");
  const resume = page.getByRole("region", {
    name: "Pick up where you left off",
  });
  await expect(resume).toContainText(authTopic.title);
  await expect(page.getByText("Second attempts")).toHaveCount(0);
  await expect(page.getByText("In progress", { exact: true })).toHaveCount(0);

  const suggested = page.getByRole("region", { name: "Suggested topics" });
  const pill = suggested.getByRole("button", { name: "Include practised" });
  await expect(pill).toHaveAttribute("aria-pressed", "false");
  await expect(suggested.getByText(rag.title)).toBeVisible();
  await expect(
    suggested.getByRole("button", { name: /Begin your practice/ }),
  ).toBeVisible();
  expect(asked.length).toBeGreaterThan(0);
  expect(asked.every((include) => !include)).toBe(true);
  await pill.click();
  await expect(pill).toHaveAttribute("aria-pressed", "true");
  await expect(suggested.getByText("Caching")).toBeVisible();
  expect(asked.at(-1)).toBe(true);
  await suggested.getByRole("button", { name: /Open topic/ }).click();
  await expect(page).toHaveURL(/#\/topic\/caching$/);

  await page.goto("/#/today");
  await resume.getByRole("button").click();
  await expect(page).toHaveURL(/#\/topic\/auth$/);
  await page.goto("/#/today");
  await ready.getByRole("button", { name: /Caching/ }).click();
  await expect(page).toHaveURL(/#\/topic\/caching$/);

  // Every unpractised topic is done: a calm empty state, not an error.
  allPractised = true;
  await page.goto("/#/today");
  await page.reload();
  await expect(
    suggested.getByText(
      "You’ve practised every topic here — include practised to see them all",
    ),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await pill.click();
  await expect(suggested.getByText("Caching")).toBeVisible();
});

test("history lists topics only", async ({ page }) => {
  const listRequests: string[] = [];
  page.on("request", (r) => {
    const path = new URL(r.url()).pathname;
    if (["/api/sessions", "/api/reviews", "/api/attempt2"].includes(path))
      listRequests.push(path);
  });
  await mockLists(page, {
    history: [
      historyRow(authTopic, {
        session_id: SESSION_ID,
        attempt_count: 2,
        last_attempt_at: "2026-11-17T09:00:00+00:00",
        next_attempt_after: "2026-11-18",
        can_record: false,
        coverage: {
          attempt: 2,
          correct: 3,
          total: 4,
          wpm: 141,
          pitch_range_semitones: 3.1,
          filler_count: 1,
        },
      }),
      historyRow(caching, {
        last_attempt_at: "2026-10-28T09:00:00+00:00",
        coverage: {
          attempt: 1,
          correct: null,
          total: 4,
          wpm: null,
          pitch_range_semitones: null,
          filler_count: null,
        },
      }),
    ],
  });
  await serve(page, { current: thread() });
  await page.goto("/#/history");
  const rows = page.locator("table.history-table tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText(authTopic.title);
  await expect(rows.first()).toContainText("2 attempts");
  await expect(rows.first()).toContainText("3/4");
  await expect(rows.first()).toContainText("141");
  await expect(rows.first()).toContainText("Next attempt opens tomorrow");
  await expect(rows.last()).toContainText("Caching");
  await expect(rows.last()).toContainText("1 attempt");
  await expect(rows.last()).toContainText("New attempt open");
  await expect(page.getByText("Complete", { exact: true })).toHaveCount(0);
  await expect(page.getByText("In progress", { exact: true })).toHaveCount(0);
  await rows
    .first()
    .getByRole("button", { name: /Authentication/ })
    .click();
  await expect(page).toHaveURL(/#\/topic\/auth$/);
  await expect(page.getByRole("button", { name: "Attempt 1" })).toBeVisible();
  expect(listRequests).toEqual([]);
});

test("old session link redirects to topic", async ({ page }) => {
  // GET /api/sessions/{id} keeps its old shape, dead stage fields included; only topic_id is read.
  await page.route("**/api/sessions/old-session", (route) =>
    route.fulfill({
      json: {
        id: "old-session",
        topic_id: "auth",
        created_at: "2026-10-27T12:00:00Z",
        duration: 120,
        style: "Conversational",
        prompt_kind: "Concept explanation",
        stage: "record2",
        completed_at: null,
        recall: null,
        review_due: null,
        attempt2_after: "2026-10-28",
        topic: authTopic,
        prompt: authTopic.prompt,
        attempts: [],
        messages: [],
      },
    }),
  );
  await serve(page, { current: thread() });
  await page.goto("/#/today");
  await page.evaluate(() => (location.hash = "#/session/old-session"));
  await expect(page).toHaveURL(/#\/topic\/auth$/);
  await expect(page.getByRole("button", { name: "Attempt 1" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toHaveCount(0);
  // The redirect replaced the old link, so Back returns to Today.
  await page.goBack();
  await expect(page).toHaveURL(/#\/today$/);
});

test("ready list shows three topics until show all", async ({ page }) => {
  const titles = [
    "Authentication vs. authorization",
    "Neural networks",
    "Caching",
    "REST APIs",
    "Hash maps",
    "React hooks",
    "Transformers and attention",
    "Securing LLM applications",
    "Build a task tracker",
  ];
  const ready = titles.map((title, i) =>
    readyRow(topic(`t${i}`, title), {
      due: i < 2,
      review_due: i < 2 ? "2026-10-30" : null,
      last_attempt_at: `2026-11-0${i + 1}T09:00:00+00:00`,
    }),
  );
  await mockLists(page, {
    ready,
    recommend: () => ({
      topic: rag,
      practised: false,
      reason: "A fresh perspective for your next practice",
    }),
  });
  await page.goto("/#/today");
  const list = page.getByRole("region", { name: "Ready for another attempt" });
  const rows = list.getByRole("listitem");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("due");
  await expect(rows.nth(1)).toContainText("due");
  await expect(rows.nth(2)).toContainText("Caching");
  // The suggestion stays in view with the list collapsed.
  await expect(
    page.getByRole("region", { name: "Suggested topics" }).getByText(rag.title),
  ).toBeInViewport();
  await list.getByRole("button", { name: "Show all (9)" }).click();
  await expect(rows).toHaveCount(9);
  await expect(rows.last()).toContainText("Build a task tracker");
  await list.getByRole("button", { name: "Show fewer" }).click();
  await expect(rows).toHaveCount(3);
});

test("first attempt remembers speaking time and style, not the question type", async ({
  page,
}) => {
  await mockLists(page);
  await serve(page, { current: emptyThread() });
  await page.goto("/#/topic/auth");
  const time = page.getByRole("combobox", { name: "Speaking time" });
  const style = page.getByRole("combobox", { name: "Delivery intention" });
  const kind = page.getByRole("combobox", { name: "Question type" });
  await expect(time).toHaveValue("120");
  await expect(style).toHaveValue("Conversational");
  await time.selectOption("180");
  await style.selectOption("Animated storyteller");
  await kind.selectOption("Compare");
  await page.reload();
  await expect(time).toHaveValue("180");
  await expect(style).toHaveValue("Animated storyteller");
  await expect(kind).toHaveValue("Concept explanation");
  await expect(page.locator(".timer")).toHaveText("3:00");
});

test("first attempt still works when storage is unavailable", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new DOMException(
          "Storage blocked for this test",
          "SecurityError",
        );
      },
    });
  });
  await mockLists(page);
  await serve(page, { current: emptyThread() });
  await page.goto("/#/topic/auth");
  const time = page.getByRole("combobox", { name: "Speaking time" });
  await expect(time).toHaveValue("120");
  await time.selectOption("240");
  await expect(page.locator(".timer")).toHaveText("4:00");
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
