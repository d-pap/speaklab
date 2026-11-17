import { expect, test, type Page } from "@playwright/test";

// Explicit test measurements and synthetic audio; never used in production analysis.
function silentWav(seconds: number) {
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

const metrics = {
  analysis_version: 2,
  wpm: 150,
  filler_count: 0,
  rate_track: [
    { time: 0, value: 120 },
    { time: 30, value: 160 },
    { time: 60, value: 140 },
    { time: 90, value: 210 },
    { time: 120, value: 900 },
  ],
  delivery_windows: [
    { start: 0, end: 15, loudness_range_db: 2, pitch_range_semitones: 1 },
    { start: 15, end: 30, loudness_range_db: 8, pitch_range_semitones: 6 },
    {
      start: 30,
      end: 45,
      loudness_range_db: null,
      pitch_range_semitones: null,
    },
    { start: 45, end: 60, loudness_range_db: 4, pitch_range_semitones: 3 },
    { start: 120, end: 125, loudness_range_db: 99, pitch_range_semitones: 99 },
  ],
  pauses: [
    { start: 30, duration: 0.5 },
    { start: 75, duration: 2 },
  ],
  pause_count: 2,
  pause_seconds: 2.5,
};
// Range-aware audio, so playback markers can seek.
async function serveRangedAudio(page: Page, seconds: number) {
  const recording = silentWav(seconds);
  await page.route("**/vocal-test.wav", (route) => {
    const range = route
      .request()
      .headers()
      ["range"]?.match(/^bytes=(\d+)-(\d*)$/);
    if (!range)
      return route.fulfill({
        contentType: "audio/wav",
        headers: { "accept-ranges": "bytes" },
        body: recording,
      });
    const start = Number(range[1]);
    const end = range[2]
      ? Math.min(Number(range[2]), recording.length - 1)
      : recording.length - 1;
    return route.fulfill({
      status: 206,
      contentType: "audio/wav",
      headers: {
        "accept-ranges": "bytes",
        "content-range": `bytes ${start}-${end}/${recording.length}`,
      },
      body: recording.subarray(start, end + 1),
    });
  });
}
async function openMeasurements(page: Page) {
  await page.getByRole("tab", { name: "Measurements" }).click();
  const details = page.locator("details.measurements");
  if (!(await details.evaluate((d: HTMLDetailsElement) => d.open)))
    await page
      .getByText("Voice measurements (pace, pitch, volume, pauses)", {
        exact: true,
      })
      .click();
}
const makeSession = (acoustics: object, transcriptSource = "whisper") => ({
  id: "vocal-test",
  topic_id: "auth",
  topic: { id: "auth", title: "Authentication vs. authorization" },
  created_at: "2026-10-28T12:00:00Z",
  duration: 180,
  style: "Conversational",
  prompt_kind: "Concept explanation",
  prompt: "Explain the difference.",
  stage: "review1",
  completed_at: null,
  messages: [],
  attempts: [
    {
      id: "vocal-attempt",
      number: 1,
      duration: 125,
      created_at: "2026-10-28T12:00:00Z",
      transcript: "An explanation for the UI test.",
      transcript_source: transcriptSource,
      transcription_version: 2,
      status: "ready",
      errors: {},
      assessment: null,
      acoustics,
      segments: [],
      audio_url: "/vocal-test.wav",
    },
  ],
});

test("vocal foundations show temporal contrast, exclude short trailing fragments, and play marked passages", async ({
  page,
}) => {
  await page.route("**/api/sessions/vocal-test", (route) =>
    route.fulfill({ json: makeSession(metrics) }),
  );
  await serveRangedAudio(page, 125);
  await page.goto("/#/session/vocal-test");
  await openMeasurements(page);
  const view = page.getByRole("region", {
    name: "Vocal variation for attempt 1",
  });
  await expect(view.getByText("120–210", { exact: true })).toBeVisible();
  await expect(view.getByText(/across 4 full 30-second windows/)).toBeVisible();
  await view.getByRole("button", { name: /Fastest window/ }).click();
  await expect
    .poll(() =>
      view.locator("audio").evaluate((a: HTMLAudioElement) => a.currentTime),
    )
    .toBeGreaterThan(89);
  await view.getByRole("button", { name: "Volume", exact: true }).click();
  await expect(view.getByText("2.0–8.0 dB", { exact: true })).toBeVisible();
  await expect(
    view.getByText(/across 3 usable 15-second windows/),
  ).toBeVisible();
  await view.getByRole("button", { name: /Most varied window/ }).click();
  await expect
    .poll(() =>
      view.locator("audio").evaluate((a: HTMLAudioElement) => a.currentTime),
    )
    .toBeGreaterThan(14);
  await view
    .getByRole("button", { name: "Pitch & melody", exact: true })
    .click();
  await expect(view.getByText("1.0–6.0 st", { exact: true })).toBeVisible();
  await view.getByRole("button", { name: "Pauses", exact: true }).click();
  await expect(
    view.getByText("2 internal pauses", { exact: true }),
  ).toBeVisible();
  await expect(view.getByText(/2.5 seconds total/)).toBeVisible();
  await view.getByRole("button", { name: /Longest internal pause/ }).click();
  await expect
    .poll(() =>
      view.locator("audio").evaluate((a: HTMLAudioElement) => a.currentTime),
    )
    .toBeGreaterThan(74);
  await view.getByRole("button", { name: "Tonality", exact: true }).click();
  await expect(view.getByText(/no emotion or tonality score/)).toBeVisible();
  await view.getByRole("button", { name: "Rate", exact: true }).click();
  await page.screenshot({
    path: "test-results/vocal-variation-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 320, height: 900 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(320);
  // Under 900px the tabs live in a sheet; the open tab and details are kept.
  await page.getByRole("button", { name: "Transcript & review" }).click();
  await view
    .getByRole("button", { name: "Pitch & melody", exact: true })
    .click();
  await expect(
    view.getByRole("button", { name: /Widest pitch spread/ }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/vocal-variation-mobile.png",
    fullPage: true,
  });
});

test("unaligned transcripts and missing pitch never produce a fabricated variation grade", async ({
  page,
}) => {
  await page.route("**/api/sessions/vocal-test", (route) =>
    route.fulfill({
      json: makeSession(
        {
          wpm: 145,
          rate_track: [],
          pause_count: 0,
          pauses: [],
          delivery_windows: [
            {
              start: 0,
              end: 15,
              loudness_range_db: null,
              pitch_range_semitones: null,
            },
          ],
        },
        "manual",
      ),
    }),
  );
  await page.route("**/vocal-test.wav", (route) =>
    route.fulfill({ contentType: "audio/wav", body: silentWav(1) }),
  );
  await page.goto("/#/session/vocal-test");
  await openMeasurements(page);
  const view = page.getByRole("region", {
    name: "Vocal variation for attempt 1",
  });
  await expect(
    view.getByText(/manually edited transcript has no aligned/),
  ).toBeVisible();
  await expect(
    view.getByRole("button", { name: /Fastest window/ }),
  ).toHaveCount(0);
  await view
    .getByRole("button", { name: "Pitch & melody", exact: true })
    .click();
  await expect(
    view.getByText(/Missing pitch estimates are not evidence/),
  ).toBeVisible();
  await view.getByRole("button", { name: "Pauses", exact: true }).click();
  await expect(
    view.getByText(/does not establish uninterrupted speech/),
  ).toBeVisible();
});

test("measurements keep filler detail, vocal foundations and reading level, collapsed", async ({
  page,
}) => {
  await page.route("**/api/sessions/vocal-test", (route) =>
    route.fulfill({
      json: makeSession({
        ...metrics,
        filler_count: 1,
        fillers: { um: 1 },
        fillers_per_minute: 20,
        filler_candidates: { like: 1 },
        filler_events: [
          {
            term: "um",
            text: "Um",
            kind: "hesitation",
            start: 2.2,
            timing: "estimated-word",
            char_start: 0,
            char_end: 2,
          },
        ],
        repetitions: [{ text: "the token", char_start: 5, char_end: 14 }],
        vocal_foundations: [
          {
            foundation: "Pitch & melody",
            observation: "Measured spread: 2 semitones.",
            practice: "Try emphasizing a different word.",
            start: 3,
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
      }),
    }),
  );
  await serveRangedAudio(page, 10);
  await page.goto("/#/session/vocal-test");
  await page.getByRole("tab", { name: "Measurements" }).click();
  // Everything starts collapsed.
  await expect(page.getByText("Measured spread: 2 semitones.")).toBeHidden();
  await expect(
    page.getByText(/Excluded from the hesitation total/),
  ).toBeHidden();
  await expect(page.getByText("Needs at least 100 words.")).toBeHidden();
  await page
    .getByText("Filler words, possible fillers & repetitions", { exact: true })
    .click();
  await expect(
    page.getByText(/Excluded from the hesitation total/),
  ).toBeVisible();
  await expect(page.getByText(/Repeated phrases: “the token”/)).toBeVisible();
  await page.getByRole("button", { name: "0:02 · Hear “Um”" }).click();
  await expect
    .poll(() =>
      page
        .getByLabel("Listen to filler words in attempt 1")
        .evaluate((a: HTMLAudioElement) => a.currentTime),
    )
    .toBeGreaterThan(1.8);
  await page
    .getByText("Vocal foundations · five ways to practice", { exact: true })
    .click();
  await expect(page.getByText("Measured spread: 2 semitones.")).toBeVisible();
  await expect(
    page.getByText("Try emphasizing a different word."),
  ).toBeVisible();
  await page.getByRole("button", { name: "0:03 · Listen here" }).click();
  await expect
    .poll(() =>
      page
        .getByLabel("Listen to vocal foundations in attempt 1")
        .evaluate((a: HTMLAudioElement) => a.currentTime),
    )
    .toBeGreaterThan(2.6);
  await page
    .getByText("Optional reading-level estimate · experimental", {
      exact: true,
    })
    .click();
  await expect(page.getByText("Needs at least 100 words.")).toBeVisible();
});
