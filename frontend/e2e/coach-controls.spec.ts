import { expect, test } from "@playwright/test";
import {
  attempt,
  donePasses,
  message,
  pass,
  serve,
  thread,
  type Json,
} from "./fixtures";

const oldModel = "qwen3.5:9b-q4_K_M";
const newModel = "gemma4:e4b";

test("inline model selection regenerates the review and exposes the saved version", async ({
  page,
}) => {
  const state = {
    current: thread({ messages: [message({ model: oldModel })] }),
  };
  await serve(page, state);
  const selections: Json[] = [];
  await page.route("**/api/settings/model", async (route) => {
    selections.push(route.request().postDataJSON());
    await route.fulfill({ json: { selected: newModel } });
  });
  let regenerations = 0;
  await page.route("**/api/attempts/attempt-1/rereview", async (route) => {
    regenerations++;
    state.current = thread({
      messages: [
        message({
          id: 4,
          model: newModel,
          content: "A newly generated review.",
          parts: [],
        }),
      ],
    });
    await route.fulfill({ json: { status: "pending" } });
  });
  await page.route("**/api/attempts/attempt-1/analysis-history", (route) =>
    route.fulfill({
      json: [
        {
          id: 1,
          created_at: "2026-11-17T18:00:00Z",
          attempt: {
            ...attempt(),
            review_message: "Original review with its observation.",
            review_parts: [
              { type: "text", text: "Original review with its observation." },
            ],
            analysis: { passes: { writer: { model: oldModel } } },
          },
        },
      ],
    }),
  );
  await page.goto("/#/topic/auth");
  const chat = page.getByRole("region", { name: "Coach chat" });
  const controls = chat.getByRole("group", { name: "Coach controls" });
  await expect(controls.getByLabel("Coach model", { exact: true })).toHaveValue(
    oldModel,
  );
  await controls
    .getByLabel("Coach model", { exact: true })
    .selectOption(newModel);
  await expect(controls.getByRole("status")).toContainText(newModel);
  expect(selections).toEqual([{ model: newModel }]);
  // Changing a model does not silently rewrite existing feedback.
  await expect(
    chat.getByText(`Review written by ${oldModel}`, { exact: true }),
  ).toBeVisible();
  expect(regenerations).toBe(0);
  await controls
    .getByRole("button", { name: "Regenerate review", exact: true })
    .click();
  await expect(chat.getByText("A newly generated review.")).toBeVisible();
  await expect(
    chat.getByText(`Review written by ${newModel}`, { exact: true }),
  ).toBeVisible();
  expect(regenerations).toBe(1);
  await controls.getByRole("button", { name: "View previous reviews" }).click();
  await controls.getByText(/Saved before re-review/).click();
  await expect(
    controls.getByText("Original review with its observation."),
  ).toBeVisible();
  await expect(
    controls.getByText(`Review written by ${oldModel}`, { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/coach-controls-desktop.png",
    fullPage: true,
  });
});

test("custom step models stay intact until an explicit inline selection", async ({
  page,
}) => {
  await serve(page, { current: thread() });
  await page.route("**/api/settings/passes", (route) =>
    route.fulfill({
      json: Object.fromEntries(
        ["technical", "communication", "writer", "chat", "memory"].map(
          (name) => [
            name,
            {
              model: name === "chat" ? newModel : oldModel,
              num_ctx: 8192,
              num_predict: 2048,
            },
          ],
        ),
      ),
    }),
  );
  let changes = 0;
  await page.route("**/api/settings/model", (route) => {
    changes++;
    return route.fulfill({ json: { selected: newModel } });
  });
  await page.goto("/#/topic/auth");
  const picker = page.getByLabel("Coach model", { exact: true });
  await expect(picker).toHaveValue("");
  await expect(
    picker.getByRole("option", { name: "Custom step models" }),
  ).toHaveCount(1);
  expect(changes).toBe(0);
  await picker.selectOption(newModel);
  await expect(picker).toHaveValue(newModel);
  expect(changes).toBe(1);
});

test("phone controls keep the previous model and review after refused requests", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await serve(page, {
    current: thread({ messages: [message({ model: oldModel })] }),
  });
  await page.route("**/api/settings/model", (route) =>
    route.fulfill({
      status: 409,
      json: {
        detail:
          "Wait for the coach to finish answering before changing models.",
      },
    }),
  );
  await page.route("**/api/attempts/attempt-1/rereview", (route) =>
    route.fulfill({
      status: 409,
      json: {
        detail:
          "Wait for the coach to finish answering before regenerating the review.",
      },
    }),
  );
  await page.goto("/#/topic/auth");
  const controls = page.getByRole("group", { name: "Coach controls" });
  const picker = controls.getByLabel("Coach model", { exact: true });
  await expect(picker).toHaveValue(oldModel);
  await picker.selectOption(newModel);
  await expect(controls.getByRole("alert")).toContainText(
    "before changing models",
  );
  await expect(picker).toHaveValue(oldModel);
  await controls
    .getByRole("button", { name: "Regenerate review", exact: true })
    .click();
  await expect(controls.getByRole("alert")).toContainText(
    "before regenerating the review",
  );
  await expect(
    page.getByText(`Review written by ${oldModel}`, { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/coach-controls-phone.png",
    fullPage: true,
  });
});

test("regeneration and model switching are disabled during review processing", async ({
  page,
}) => {
  await serve(page, {
    current: thread({
      attempts: [
        attempt(
          { status: "processing" },
          { passes: { ...donePasses(), writer: pass("running") } },
        ),
      ],
    }),
  });
  await page.goto("/#/topic/auth");
  await expect(page.getByLabel("Coach model", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Regenerate review", exact: true }),
  ).toBeDisabled();
});
