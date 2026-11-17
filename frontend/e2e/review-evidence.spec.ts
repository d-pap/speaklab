import { expect, test } from "@playwright/test";
import { attempt, message, serve, thread, timedLines } from "./fixtures";

const points = [
  {
    kind: "problem",
    line_id: "L2",
    observation: "The decision needs a reason.",
    rewrite: "I’d test how quickly people can find a task.",
  },
  {
    kind: "strength",
    line_id: "L3",
    observation: "The question makes the trade-off concrete.",
    rewrite: "",
  },
];
const timing = [
  { label: "Setup", start: 0, end: 40, seconds: 40, percent: 34.5 },
  { label: "Design choices", start: 40, end: 116, seconds: 76, percent: 65.5 },
];
const communication = { sections: [], points, gaps: [], focus: [] };
function written(text: string) {
  return message({ content: text, parts: [{ type: "text", text }] });
}

test("unmarked review prose still shows measured timings and two linked moments", async ({
  page,
}) => {
  await serve(page, {
    current: thread({
      attempts: [attempt({}, { timing, communication })],
      messages: [written("Start with the decision.")],
    }),
  });
  await page.goto("/#/topic/auth");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await expect(chat.getByText("Start with the decision.")).toBeVisible();
  const chart = chat.getByRole("figure", { name: "Time spent per section" });
  await expect(chart.locator(".timing-row")).toHaveCount(2);
  await expect(chart.getByText("76s · 65.5%")).toBeVisible();
  expect(
    await chart
      .locator(".timing-track > div")
      .last()
      .evaluate((el) => (el as HTMLElement).style.width),
  ).toBe("65.5%");
  const cards = chat.getByRole("article");
  await expect(cards).toHaveCount(2);
  await expect(cards.first().locator("blockquote")).toHaveText(
    timedLines[1].text,
  );
  await expect(cards.first()).toContainText(points[0].rewrite);
  await expect(cards.last().getByText("Try saying")).toHaveCount(0);
  await cards.first().getByRole("button", { name: "0:40" }).click();
  await expect(page.locator('[data-line="L2"]')).toHaveClass(/highlight/);
});

test("a phone review interleaves evidence with writer headings and retains the full text", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const text =
    "### Three priorities\nOpen with the decision.\n\n3. **Where the time went**\nThe setup delayed the trade-off.\n\n**In the moment:**\nYour example made the cost clear.\n\n### A strong answer\nI would start with the customer.\n\n### Next time\nName the decision first.";
  await serve(page, {
    current: thread({
      attempts: [attempt({}, { timing, communication })],
      messages: [written(text)],
    }),
  });
  await page.goto("/#/topic/auth");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await expect(
    chat.getByRole("heading", { name: "Where the time went" }),
  ).toHaveCount(1);
  await expect(chat.getByRole("heading", { name: "Moments" })).toHaveCount(1);
  await expect(chat.getByText("Name the decision first.")).toBeVisible();
  await expect(chat.getByText("I would start with the customer.")).toBeHidden();
  await chat.getByText("A strong answer", { exact: true }).click();
  await expect(
    chat.getByText("I would start with the customer."),
  ).toBeVisible();
  await chat.getByText("Coach’s commentary", { exact: true }).last().click();
  await expect(
    chat.getByText("Your example made the cost clear."),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await chat
    .locator(".section-timing")
    .evaluate((el) => el.scrollIntoView({ block: "center" }));
  await chat
    .locator(".section-timing")
    .screenshot({ path: "test-results/coach-review-chart.png" });
  await chat
    .getByRole("article")
    .first()
    .evaluate((el) => el.scrollIntoView({ block: "center" }));
  await chat
    .getByRole("article")
    .first()
    .screenshot({ path: "test-results/coach-review-moment.png" });
  await chat.getByRole("button", { name: "1:24" }).click();
  await expect(
    page
      .getByRole("tabpanel", { name: "Transcript" })
      .locator('[data-line="L3"]'),
  ).toHaveClass(/highlight/);
});

test("an edited transcript uses line buttons and drops unresolved observations", async ({
  page,
}) => {
  const lines = timedLines.map((line) => ({ ...line, start: null, end: null }));
  await serve(page, {
    current: thread({
      attempts: [
        attempt(
          { lines },
          {
            communication: {
              ...communication,
              points: [...points, { ...points[0], line_id: "L99" }],
            },
          },
        ),
      ],
      messages: [written("Review.")],
    }),
  });
  await page.goto("/#/topic/auth");
  const chat = page.getByRole("region", { name: "Coach chat" });
  await expect(chat.getByRole("article")).toHaveCount(2);
  await expect(chat.getByRole("figure")).toHaveCount(0);
  await chat.getByRole("button", { name: "line 2" }).click();
  await expect(page.locator('[data-line="L2"]')).toHaveClass(/highlight/);
});
