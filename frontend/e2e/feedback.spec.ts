import { expect, test } from "@playwright/test";
import { message, serve, thread, type Json } from "./fixtures";

test("review and learning feedback saves details, survives reopening, and can be removed", async ({
  page,
}) => {
  let feedback: Json | null = null;
  const bodies: Json[] = [];
  const learning = message({
    id: 3,
    kind: "chat",
    content: "Here is an explanation.",
    parts: [],
  });
  const state = {
    current: thread({
      messages: [
        message(),
        message({
          id: 2,
          role: "user",
          kind: "chat",
          content: "Explain it",
          parts: [],
        }),
        learning,
      ],
    }),
  };
  await serve(page, state);
  await page.route("**/api/messages/1/feedback", async (route) => {
    const body = route.request().postDataJSON();
    bodies.push(body);
    feedback =
      body.rating === null
        ? null
        : { ...body, id: 1, updated_at: "2026-11-17T18:00:00Z" };
    state.current = thread({ messages: [message({ feedback }), learning] });
    await route.fulfill({ json: { feedback } });
  });
  await page.goto("/#/topic/auth");
  const groups = page.getByRole("group", {
    name: "Feedback on coach response",
  });
  await expect(groups).toHaveCount(2); // no controls on learner messages
  const review = groups.first();
  await review
    .getByRole("button", { name: "Not helpful", exact: true })
    .click();
  await expect(
    review.getByRole("button", { name: "Not helpful", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await review.getByLabel("What stood out?").selectOption("missed_insight");
  await review
    .getByLabel("Tell the coach what worked")
    .fill("Notice how I repeat the definition.");
  await review
    .getByLabel("What would a better response say?")
    .fill("Explain what that repetition suggests and how to improve it.");
  await review.getByRole("button", { name: "Save details" }).click();
  await expect(review.getByRole("status")).toHaveText("Feedback saved locally");
  expect(bodies.at(-1)).toEqual({
    rating: -1,
    reason: "missed_insight",
    comment: "Notice how I repeat the definition.",
    preferred_response:
      "Explain what that repetition suggests and how to improve it.",
  });
  await page.reload();
  await review.getByRole("button", { name: "Add or edit details" }).click();
  await expect(review.getByLabel("Tell the coach what worked")).toHaveValue(
    "Notice how I repeat the definition.",
  );
  await page.screenshot({
    path: "test-results/feedback-desktop.png",
    fullPage: true,
  });
  await review.getByRole("button", { name: "Helpful", exact: true }).click();
  await expect(
    review.getByRole("button", { name: "Helpful", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await review.getByRole("button", { name: "Helpful", exact: true }).click();
  await expect(review.getByRole("status")).toHaveText("Feedback removed");
  expect(bodies.at(-1)?.rating).toBeNull();
  await expect(
    groups.last().getByRole("button", { name: "Helpful", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
});

test("phone feedback handles failed saves and keeps the detail draft", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await serve(page, { current: thread() });
  let calls = 0;
  await page.route("**/api/messages/1/feedback", async (route) => {
    calls++;
    const body = route.request().postDataJSON();
    if (calls === 2)
      return route.fulfill({
        status: 503,
        json: { detail: "Could not save. Try again." },
      });
    return route.fulfill({
      json: {
        feedback: { ...body, id: 1, updated_at: "2026-11-17T18:00:00Z" },
      },
    });
  });
  await page.goto("/#/topic/auth");
  const feedback = page.getByRole("group", {
    name: "Feedback on coach response",
  });
  await feedback
    .getByRole("button", { name: "Not helpful", exact: true })
    .click();
  const comment = feedback.getByLabel("Tell the coach what worked");
  await comment.fill("The diagnosis wasn't grounded in my transcript.");
  await feedback.getByRole("button", { name: "Save details" }).click();
  await expect(feedback.getByText("Could not save. Try again.")).toBeVisible();
  await expect(comment).toHaveValue(
    "The diagnosis wasn't grounded in my transcript.",
  );
  await page.screenshot({
    path: "test-results/feedback-phone.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await feedback.getByRole("button", { name: "Save details" }).click();
  await expect(feedback.getByRole("status")).toHaveText(
    "Feedback saved locally",
  );
});
