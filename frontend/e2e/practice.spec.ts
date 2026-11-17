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
  await page.route("**/api/settings/passes", (route) => {
    const names = ["technical", "communication", "writer", "chat", "memory"];
    return route.fulfill({
      json:
        route.request().method() === "PUT"
          ? route.request().postDataJSON().passes
          : Object.fromEntries(
              names.map((n) => [
                n,
                { model: selected, num_ctx: 8192, num_predict: 2048 },
              ]),
            ),
    });
  });
  await page.goto("/#/settings");
  const picker = page.getByRole("combobox", {
    name: "Model for feedback & coaching",
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

// Runs against the real backend on the e2e ports, so the thread GET and the upload are checked
// with the shapes the server actually returns. Each run practises one unpractised topic.
test("picking a new topic records attempt 1 and lands on the topic page", async ({
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
  const suggested = page.getByRole("region", { name: "Suggested topics" });
  const title = await suggested.getByRole("heading", { level: 2 }).innerText();
  await suggested.getByRole("button", { name: /Begin your practice/ }).click();
  await expect(page).toHaveURL(/#\/topic\/[a-z0-9-]+$/);
  const topicId = /#\/topic\/([a-z0-9-]+)$/.exec(page.url())![1];
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByText("CURATED REFERENCES")).toHaveCount(0);
  // Picking a topic creates nothing: the real thread is still empty.
  const before = await (
    await page.request.get(`/api/topics/${topicId}/thread`)
  ).json();
  expect(before.session_id).toBeNull();
  expect(before.attempts).toEqual([]);
  expect(before.recording).toEqual({
    can_record: true,
    reason: null,
    replace_number: null,
    next_number: 1,
  });
  await page
    .getByRole("combobox", { name: "Delivery intention" })
    .selectOption("Thoughtful teacher");
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "test.wav", mimeType: "audio/wav", buffer: wav() });
  // The upload goes through to the real server; the route only reads the form it sends.
  let body = "";
  await page.route(`**/api/topics/${topicId}/attempts`, (route) => {
    body = route.request().postDataBuffer()?.toString("latin1") ?? "";
    return route.continue();
  });
  const uploaded = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      r.url().endsWith(`/api/topics/${topicId}/attempts`),
  );
  await page.getByRole("button", { name: "Save & explore feedback" }).click();
  const response = await uploaded;
  expect(response.status()).toBe(201);
  const names = [...body.matchAll(/; name="([^"]+)"/g)].map((m) => m[1]);
  // The question type was left alone, so it is not sent; style and length are.
  expect(names.sort()).toEqual(["duration", "file", "style"]);
  const saved = await response.json();
  expect(saved).toMatchObject({
    number: 1,
    prompt_kind: "Concept explanation",
    style: "Thoughtful teacher",
    target_duration: 120,
  });
  await expect(page).toHaveURL(new RegExp(`#/topic/${topicId}\\?attempt=1$`));
  await expect(page.getByRole("button", { name: "Attempt 1" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // Whisper is unreachable in this test, so the recording is kept and no review is written.
  await expect(
    page.getByText("Your recording is safe. Some analysis is unavailable."),
  ).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("tab", { name: "Transcript" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.getByRole("button", { name: "Enter transcript manually" }).click();
  await page
    .getByLabel("Correct or enter what you said")
    .fill(
      "Um, here is my explanation from memory. I want to understand the mechanism better and explain it to a friend.",
    );
  await page.getByRole("button", { name: "Save & review again" }).click();
  const transcript = page.getByRole("tabpanel", { name: "Transcript" });
  await expect(transcript.locator("mark.filler").first()).toHaveText(/um/i, {
    timeout: 20000,
  });
  // A manual transcript has no line times.
  await expect(transcript.locator(".ts")).toHaveCount(0);
  // The local model is unreachable: the failed passes say so and offer a retry.
  await expect(page.getByRole("button", { name: "Retry" }).first()).toBeVisible(
    { timeout: 20000 },
  );
  await page.screenshot({
    path: "test-results/review-offline-desktop.png",
    fullPage: true,
  });
  // The server decides when the next attempt opens.
  await expect(page.getByText("Next attempt opens tomorrow")).toBeVisible();
  await expect(page.getByRole("button", { name: "New attempt" })).toHaveCount(
    0,
  );
  const after = await (
    await page.request.get(`/api/topics/${topicId}/thread`)
  ).json();
  expect(after.attempts.map((a: { number: number }) => a.number)).toEqual([1]);
  expect(after.recording).toMatchObject({
    can_record: false,
    reason: "Next attempt opens tomorrow",
    next_number: 2,
  });
  await page.reload();
  await expect(page).toHaveURL(new RegExp(`#/topic/${topicId}\\?attempt=1$`));
  await expect(
    page
      .getByRole("tabpanel", { name: "Transcript" })
      .locator("mark.filler")
      .first(),
  ).toHaveText(/um/i);
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Pick up where you left off" }),
  ).toContainText(title);
  // The topic just recorded is practised now, so it is no longer suggested.
  const nextSuggestion = suggested.getByRole("heading", { level: 2 });
  await expect(nextSuggestion).toBeVisible();
  await expect(nextSuggestion).not.toHaveText(title);
  await page
    .getByRole("button", { name: "Practice history", exact: true })
    .click();
  const row = page
    .locator("table.history-table tbody tr")
    .filter({ hasText: title });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("1 attempt");
  await expect(row).toContainText("Next attempt opens tomorrow");
  await row.getByRole("button", { name: title }).click();
  await expect(page).toHaveURL(new RegExp(`#/topic/${topicId}$`));
  await expect(page.getByRole("button", { name: "Attempt 1" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("real browser recorder supports pause, resume, stop, and local playback", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Begin your practice/ }).click();
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
  await page.getByRole("button", { name: /Begin your practice/ }).click();
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
  await page.getByRole("button", { name: /Begin your practice/ }).click();
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
    page.getByRole("button", { name: /Begin your practice/ }),
  ).toBeVisible();
});

test("mobile layout, filters, settings, and theme remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: /Begin your practice/ }),
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
  // Practised topics join the library once included.
  await page.getByRole("button", { name: "Include practised" }).click();
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
