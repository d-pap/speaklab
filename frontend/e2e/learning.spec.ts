import { expect, test } from "@playwright/test";

// Explicit UI fixtures: never used by the application or saved to practice data.
const session = {
  id: "learning-ui-test",
  topic_id: "hash-maps",
  topic: {
    id: "hash-maps",
    title: "Hash maps",
    category: "Data structures",
    difficulty: "beginner",
    prompt: "Explain a hash map.",
  },
  duration: 120,
  created_at: "2026-10-28T12:00:00Z",
  style: "Conversational",
  prompt_kind: "Concept explanation",
  prompt: "Explain a hash map.",
  stage: "learn",
  completed_at: null,
  attempts: [],
  messages: [],
};
const lesson = {
  estimated_minutes: 18,
  personalized: false,
  objectives: [
    "Explain how a hash function finds a bucket.",
    "Describe how collisions are handled.",
  ],
  sections: [
    {
      title: "Hash functions",
      minutes: 3,
      context: "A map associates keys with values.",
      body: "A hash function turns a key into a number. The map uses that number to select a bucket.",
      practice: "A cache can look up a user profile by ID.",
      question: "What is the hash function used for?",
    },
    {
      title: "Collisions",
      minutes: 4,
      context: "Different keys can select the same bucket.",
      body: "A collision occurs when two different keys select the same bucket. Chaining stores multiple entries in that bucket.",
      practice: "Compare the stored keys before returning a value.",
      question: "Why must the map compare keys after hashing?",
    },
  ],
  sources: [
    {
      title: "Hash map reference",
      url: "https://docs.python.org/3/tutorial/datastructures.html",
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/sessions/learning-ui-test", (route) =>
    route.fulfill({ json: session }),
  );
  await page.route("**/api/sessions/learning-ui-test/lesson", (route) =>
    route.fulfill({ json: lesson }),
  );
  await page.route("**/api/sessions/learning-ui-test/tutor", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "The local tutor is offline in this test." },
    }),
  );
});

test("focused lessons retain all content, drafts and position; tutor opens on demand with keyboard recovery", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/#/session/learning-ui-test");
  await expect(
    page.getByRole("heading", { name: "Hash functions", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(lesson.sections[0].context)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByLabel("Your explanation from memory")).toHaveCount(0);
  await page.getByText("In engineering practice", { exact: true }).click();
  await expect(page.getByText(lesson.sections[0].practice)).toBeVisible();
  await page
    .getByText("References", { exact: false })
    .filter({ has: page.locator("span") })
    .click();
  await expect(
    page.getByRole("link", { name: /Hash map reference/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Check your understanding" }).click();
  await expect(page.getByText(lesson.sections[0].body)).toHaveCount(0);
  await page
    .getByLabel("Your explanation from memory")
    .fill("It selects the bucket where an entry might be stored.");
  await page.getByRole("button", { name: "Next idea" }).click();
  await expect(
    page.getByRole("heading", { name: "Collisions", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("1/2 reviewed", { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Collisions", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await page.getByRole("button", { name: "Check your understanding" }).click();
  await expect(page.getByLabel("Your explanation from memory")).toHaveValue(
    "It selects the bucket where an entry might be stored.",
  );
  await page
    .getByRole("button", { name: "Ask the tutor to check this" })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("offline in this test");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Ask the tutor to check this" }),
  ).toBeFocused();
  await expect(page.getByLabel("Your explanation from memory")).toHaveValue(
    "It selects the bucket where an entry might be stored.",
  );
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Back to the explanation" }).click();
  await page.screenshot({
    path: "test-results/learning-focused-desktop.png",
    fullPage: true,
  });
});

test("learning reflows at 320px and the tutor and theme stay usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/#/session/learning-ui-test");
  await expect(
    page.getByRole("heading", { name: "Hash functions", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(320);
  await page.getByRole("button", { name: /Lesson outline/ }).click();
  await page
    .getByRole("navigation", { name: "Lesson sections" })
    .getByRole("button", { name: /Collisions/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Collisions", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Lesson outline/ }),
  ).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await page
    .getByRole("button", { name: "Ask your tutor", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByLabel("Ask your tutor", { exact: true })
    .fill("How does a bucket work?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.getByRole("alert")).toContainText("offline in this test");
  await page.screenshot({
    path: "test-results/tutor-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Close tutor" }).click();
  await page.getByRole("button", { name: "Settings & local models" }).click();
  await page.getByRole("button", { name: "Use dark mode" }).click();
  await page.goto("/#/session/learning-ui-test");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("heading", { name: "Hash functions", exact: true }),
  ).toBeVisible();
  const tinted = await page.locator("body *").evaluateAll((elements) =>
    elements
      .filter((el) => {
        const style = getComputedStyle(el);
        return [style.color, style.backgroundColor, style.borderTopColor].some(
          (value) => {
            const rgb = value.match(/^rgba?\((\d+), (\d+), (\d+)/);
            return rgb && (rgb[1] !== rgb[2] || rgb[2] !== rgb[3]);
          },
        );
      })
      .map((el) => el.className),
  );
  expect(tinted).toEqual([]);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(320);
  await page.screenshot({
    path: "test-results/learning-focused-mobile-dark.png",
    fullPage: true,
  });
});
