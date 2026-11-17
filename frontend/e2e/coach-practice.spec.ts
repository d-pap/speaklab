import { expect, test } from "@playwright/test";
import { serve, thread, reviewMessage, message, sse } from "./fixtures";

test("a learner can start a lesson, rehearse delivery and keep their own draft", async ({
  page,
}) => {
  const state = {
    current: thread({
      study_reference: {
        example: "Look up a count by key.",
        sources: [
          { title: "Hash tables", url: "https://opendatastructures.org/" },
        ],
      },
    }),
  };
  const sent: string[] = [];
  await serve(page, state);
  await page.route("**/api/sessions/review-ui/chat", (route) => {
    const { message: question, attempt_number } = route
      .request()
      .postDataJSON();
    expect(attempt_number).toBe(1);
    sent.push(question);
    const reply = message({
      id: 3,
      kind: "chat",
      content: "Try the lookup.",
      parts: [
        {
          type: "text",
          text: 'Try the lookup.\n```js\nconst example = "<img>";\n```',
        },
      ],
    });
    state.current = thread({
      messages: [
        reviewMessage,
        message({
          id: 2,
          role: "user",
          kind: "chat",
          content: question,
          parts: [],
        }),
        reply,
      ],
    });
    return route.fulfill({
      contentType: "text/event-stream",
      body: sse([{ done: true, message: reply }]),
    });
  });
  await page.goto("/#/topic/auth");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await chat.getByText("Worked example and sources").click();
  await expect(chat.getByRole("link", { name: "Hash tables" })).toHaveAttribute(
    "href",
    "https://opendatastructures.org/",
  );
  await chat.getByRole("button", { name: "Learn the concept" }).click();
  await expect(chat.locator("pre code")).toHaveText('const example = "<img>";');
  await expect(chat.locator("pre img")).toHaveCount(0);
  await chat.getByRole("button", { name: "Rehearse my delivery" }).click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[0]).toContain("explain back");
  expect(sent[1]).toContain("listen for");
  const composer = chat.getByPlaceholder(
    "Ask about your attempt or the topic…",
  );
  await composer.fill("My own question");
  await expect(
    chat.getByRole("button", { name: "Rehearse my delivery" }),
  ).toHaveCount(0);
  await expect(composer).toHaveValue("My own question");
});

test("phone rehearsal plays a temporary clip without uploading or creating an attempt", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") writes.push(r.url());
  });
  await serve(page, { current: thread() });
  await page.goto("/#/topic/auth");
  const recorder = page.locator(".rehearsal-recorder");
  await recorder.locator("summary").click();
  await recorder.getByRole("button", { name: "Start recording" }).click();
  await expect(recorder.getByText("Recording your explanation")).toBeVisible();
  await expect(recorder.locator(".timer")).not.toHaveText("1:00");
  await recorder.getByRole("button", { name: "Finish recording" }).click();
  await expect(recorder.locator("audio")).toHaveAttribute("src", /^blob:/);
  await expect(
    recorder.getByRole("link", { name: "Keep a copy" }),
  ).toHaveAttribute("download", /rehearsal/);
  await recorder.locator("summary").click();
  await expect(recorder.locator("audio")).toHaveCount(0);
  await recorder.locator("summary").click();
  await expect(
    recorder.getByRole("button", { name: "Start recording" }),
  ).toBeVisible();
  expect(writes).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
