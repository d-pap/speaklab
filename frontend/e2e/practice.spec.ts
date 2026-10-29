import { expect, test } from "@playwright/test";

test("model picker handles busy work, saved selection, refresh and unavailable services", async ({
  page,
}) => {
  let selected = "qwen3.5:9b-q4_K_M";
  let busy = true;
  let offline = false;
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: {
        status: "ok",
        ollama: true,
        whisper: true,
        model: selected,
        models: [selected],
        server_name: "Explicit PC test double",
        data_dir: "/test-data",
        ollama_url: "http://127.0.0.1:11434",
        whisper_url: "http://127.0.0.1:8080",
      },
    }),
  );
  await page.route("**/api/models", (route) =>
    offline
      ? route.fulfill({
          status: 503,
          json: { detail: "Ollama is unavailable in this test." },
        })
      : route.fulfill({
          json: {
            selected,
            models: [
              {
                name: "qwen3.5:9b-q4_K_M",
                parameters: "9B",
                quantization: "Q4_K_M",
                size_bytes: 6550000000,
                selectable: true,
                reason: null,
              },
              {
                name: "gemma4:e4b",
                parameters: "7.5B",
                quantization: "Q4_K_M",
                size_bytes: 6580000000,
                selectable: true,
                reason: null,
              },
              {
                name: "embedding:latest",
                parameters: "1B",
                size_bytes: 1000000000,
                selectable: false,
                reason: "Not a chat model",
              },
            ],
          },
        }),
  );
  await page.route("**/api/settings/model", (route) => {
    if (busy)
      return route.fulfill({
        status: 409,
        json: {
          detail:
            "Wait for recording analysis to finish before changing models.",
        },
      });
    selected = route.request().postDataJSON().model;
    return route.fulfill({ json: { selected } });
  });
  await page.goto("/#/settings");
  const picker = page.getByRole("combobox", {
    name: "Model for feedback & tutoring",
  });
  await expect(picker).toHaveValue(selected);
  await picker.selectOption("gemma4:e4b");
  await page.getByRole("button", { name: "Use model", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Wait for recording analysis",
  );
  expect(selected).toBe("qwen3.5:9b-q4_K_M");
  busy = false;
  await page.getByRole("button", { name: "Use model", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Model saved");
  await page.reload();
  await expect(picker).toHaveValue("gemma4:e4b");
  await expect(
    page.getByRole("button", { name: "Use model", exact: true }),
  ).toBeDisabled();
  offline = true;
  await page
    .getByRole("button", { name: "Refresh models", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Ollama is unavailable");
  offline = false;
  await page
    .getByRole("button", { name: "Refresh models", exact: true })
    .click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "test-results/model-picker-mobile.png",
    fullPage: true,
  });
});

// Synthetic audio is used only in tests; production analysis never substitutes test results.
function wav(): Buffer {
  const sr = 16000,
    seconds = 3,
    samples = sr * seconds;
  const b = Buffer.alloc(44 + samples * 2);
  b.write("RIFF");
  b.writeUInt32LE(b.length - 8, 4);
  b.write("WAVEfmt ", 8);
  b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20);
  b.writeUInt16LE(1, 22);
  b.writeUInt32LE(sr, 24);
  b.writeUInt32LE(sr * 2, 28);
  b.writeUInt16LE(2, 32);
  b.writeUInt16LE(16, 34);
  b.write("data", 36);
  b.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++)
    b.writeInt16LE(
      Math.round(Math.sin((2 * Math.PI * 220 * i) / sr) * 6000),
      44 + i * 2,
    );
  return b;
}

test("complete offline core loop with real API, audio processing, persistence, and review", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Today’s practice" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/home-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Begin your practice" }).click();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("CURATED REFERENCES")).toHaveCount(0);
  const sessionUrl = page.url();
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "test.wav", mimeType: "audio/wav", buffer: wav() });
  await expect(
    page.getByRole("button", { name: "Save & explore feedback" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Save & explore feedback" }).click();
  await expect(
    page.getByRole("heading", { name: "Your first explanation" }),
  ).toBeVisible();
  await expect(
    page.getByText("Your recording is safe. Some analysis is unavailable."),
  ).toBeVisible({ timeout: 20000 });
  await expect(
    page.getByRole("heading", { name: "Technical understanding" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Communication & voice" }),
  ).toBeVisible();
  await page
    .getByText("Transcript", { exact: false })
    .filter({ has: page.locator("span") })
    .first()
    .click();
  await page.getByRole("button", { name: "Enter transcript manually" }).click();
  await page
    .getByLabel("Correct or enter what you said")
    .fill(
      "Um, here is my explanation from memory. I want to understand the mechanism better.",
    );
  await page.getByRole("button", { name: "Save & reanalyze" }).click();
  await page.getByRole("button", { name: "Build your understanding" }).click();
  await expect(
    page.getByRole("heading", { name: "Core idea", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/learning-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Ask your tutor" }).click();
  await page
    .getByLabel("Ask your tutor")
    .fill("Can you explain the mechanism?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByRole("alert")).toContainText("local model");
  await page.getByRole("button", { name: "Close tutor" }).click();
  await page.getByRole("button", { name: "Next idea" }).click();
  await page.getByRole("button", { name: "Check your understanding" }).click();
  await page
    .getByLabel("Your explanation from memory")
    .fill("A short reflection on this concept.");
  await page
    .getByRole("button", { name: "Record your second explanation" })
    .click();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("CURATED REFERENCES")).toHaveCount(0);
  await page.locator("input[type=file]").setInputFiles({
    name: "second.wav",
    mimeType: "audio/wav",
    buffer: wav(),
  });
  await page.getByRole("button", { name: "Save & compare attempts" }).click();
  await expect(
    page.getByRole("heading", { name: "Before & after" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Finish & schedule review" }),
  ).toBeEnabled({ timeout: 20000 });
  await page.getByRole("button", { name: "Finish & schedule review" }).click();
  await expect(
    page.getByText("Your next memory check is scheduled"),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/comparison-desktop.png",
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByText("Your next memory check is scheduled"),
  ).toBeVisible();
  expect(page.url()).toBe(sessionUrl);
  const audio = page.locator("audio").first();
  expect(
    await audio.evaluate((el: HTMLAudioElement) => el.readyState),
  ).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Practice history" }).click();
  await expect(
    page.getByRole("heading", { name: "Your review queue" }),
  ).toBeVisible();
  await expect(
    page.getByText("Complete", { exact: true }).first(),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("real browser recorder supports pause, resume, stop, and local playback", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Begin your practice" }).click();
  await page
    .getByRole("button", { name: "Start recording", exact: true })
    .click();
  await expect(page.getByText("Recording your explanation")).toBeVisible();
  await expect(page.locator(".timer")).not.toHaveText("2:00");
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(page.getByText("Paused · take a breath")).toBeVisible();
  const paused = await page.locator(".timer").innerText();
  await page.waitForTimeout(1200);
  expect(await page.locator(".timer").innerText()).toBe(paused);
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await expect(page.getByText("Recording your explanation")).toBeVisible();
  await page.getByRole("button", { name: "Finish recording" }).click();
  await expect(
    page.getByRole("button", { name: "Record again" }),
  ).toBeVisible();
  await expect(page.locator("audio")).toHaveAttribute("src", /^blob:/);
  await expect(
    page.getByRole("button", { name: "Save & explore feedback" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/recorder-desktop.png",
    fullPage: true,
  });
});

test("microphone denial gives a useful recovery path", async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException("Denied for test", "NotAllowedError");
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Begin your practice" }).click();
  await page
    .getByRole("button", { name: "Start recording", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Microphone access was denied",
  );
  await expect(page.getByText("Import audio")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeEnabled();
});

test("unsaved audio survives a canceled browser navigation", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Begin your practice" }).click();
  await page.locator("input[type=file]").setInputFiles({
    name: "unsaved.wav",
    mimeType: "audio/wav",
    buffer: wav(),
  });
  const sessionUrl = page.url();
  page.once("dialog", (dialog) => void dialog.dismiss());
  await page.goBack();
  await expect(page).toHaveURL(sessionUrl);
  await expect(
    page.getByRole("button", { name: "Save & explore feedback" }),
  ).toBeVisible();
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Begin your practice" }),
  ).toBeVisible();
});

test("mobile layout, filters, settings, and theme remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Begin your practice" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "test-results/home-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Topic library" }).click();
  await page
    .getByRole("combobox", { name: "Topic category" })
    .selectOption("AI and machine learning");
  await page
    .getByRole("combobox", { name: "Topic difficulty" })
    .selectOption("advanced");
  await expect(
    page.getByRole("button", { name: /Backpropagation/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Settings & local models" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await page.getByRole("button", { name: "Use dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});

test("new review exposes factual corrections, contextual fillers, vocabulary and measured pauses", async ({
  page,
}) => {
  const attempt = {
    id: "speech-fixture",
    session_id: "insights-fixture",
    number: 1,
    created_at: "2026-10-27T12:00:00Z",
    duration: 3,
    transcript: "Um, login gives everyone access.",
    transcript_source: "whisper",
    transcription_version: 2,
    segments: [{ start: 0, end: 1, text: "Um, login gives everyone access." }],
    status: "ready",
    errors: {},
    audio_url: "/test-audio.wav",
    acoustics: {
      analysis_version: 2,
      wpm: 100,
      filler_count: 1,
      fillers: { um: 1 },
      fillers_per_minute: 20,
      filler_candidates: { like: 1 },
      filler_events: [
        {
          term: "um",
          text: "Um",
          kind: "hesitation",
          start: 0.2,
          timing: "estimated-word",
          char_start: 0,
          char_end: 2,
        },
      ],
      pauses: [{ start: 1.2, duration: 0.6 }],
      pause_count: 1,
      pause_seconds: 0.6,
      vocal_foundations: [
        {
          foundation: "Pitch & melody",
          observation: "Measured spread: 2 semitones.",
          practice: "Try emphasizing a different word.",
          start: 1,
          basis: "Test fixture",
        },
      ],
      readability: {
        available: false,
        words: 5,
        sentences: 1,
        reason: "Needs at least 100 words.",
        limitation: "Experimental text readability.",
        method: "Test fixture",
        basis: "Original unchanged.",
        repeated_words: [],
      },
    },
    assessment: {
      summary: "Explicit model test double.",
      model: "test-double",
      rubric: "Test rubric",
      communication: [],
      next_steps: ["Explain permission checks."],
      concepts: [
        {
          concept_id: "permissions",
          status: "incorrect",
          evidence: "login gives everyone access",
          feedback: "Login does not grant blanket permission.",
        },
      ],
      insights: {
        version: 2,
        note: "Selected claims, not exhaustive.",
        sources: [],
        claims: [
          {
            evidence: "login gives everyone access",
            verdict: "incorrect",
            explanation: "Identity and permission are different.",
            correction: "Check each protected resource.",
            references: [
              {
                id: "permissions",
                text: "Authorization checks resource permissions.",
              },
            ],
          },
        ],
        vocabulary: [
          {
            evidence: "login gives everyone access",
            original: "access",
            alternative: "permission to read",
            meaning: "Specifies the operation.",
            reason: "More precise.",
            practice: "Check permission to read this document.",
          },
        ],
      },
    },
  };
  await page.route("**/api/sessions/insights-fixture", (route) =>
    route.fulfill({
      json: {
        id: "insights-fixture",
        topic_id: "auth",
        topic: { id: "auth", title: "Authentication vs. authorization" },
        duration: 120,
        created_at: "2026-10-27T12:00:00Z",
        style: "Conversational",
        prompt_kind: "Concept explanation",
        prompt: "Explain the difference.",
        stage: "feedback",
        completed_at: null,
        attempts: [attempt],
        messages: [],
      },
    }),
  );
  await page.route("**/test-audio.wav", (route) =>
    route.fulfill({ body: wav(), contentType: "audio/wav" }),
  );
  await page.goto("/#/session/insights-fixture");
  await expect(
    page.getByRole("heading", { name: "Was my explanation accurate?" }),
  ).toBeVisible();
  await expect(page.getByText("Check each protected resource.")).toBeVisible();
  await page
    .getByText("Vocabulary & further analysis", { exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Build your vocabulary" }),
  ).toBeVisible();
  await page
    .getByText("Vocal foundations & recording details", { exact: true })
    .click();
  await page
    .getByText("Filler words, possible fillers & repetitions", { exact: true })
    .click();
  await expect(
    page.getByText(/Excluded from the hesitation total/),
  ).toBeVisible();
  await page
    .getByText("Annotated transcript & measured pauses", { exact: true })
    .click();
  await expect(page.getByText("[pause: 0.6s]", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "0:01 · Hear pause" }).click();
  await expect
    .poll(() =>
      page
        .getByLabel("Review attempt 1 by timestamp")
        .evaluate((a: HTMLAudioElement) => a.currentTime),
    )
    .toBeGreaterThan(0.8);
  await page
    .getByText("Vocal foundations · five ways to practice", { exact: true })
    .click();
  await expect(page.getByText("Measured spread: 2 semitones.")).toBeVisible();
  await page
    .getByText("Optional reading-level estimate · experimental", {
      exact: true,
    })
    .click();
  await expect(page.getByText("Needs at least 100 words.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: "test-results/insights-mobile.png",
    fullPage: true,
  });
});
