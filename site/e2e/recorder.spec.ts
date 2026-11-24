import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// One set of tests. Both builds have to pass all of it.
for (const build of ["Angular", "React"]) {
  test.describe(`the recorder in ${build}`, () => {
    const problems: string[] = [];

    const open = async (page: Page, path = "/") => {
      problems.length = 0;
      page.on("console", (message) => ["error", "warning"].includes(message.type()) && problems.push(message.text()));
      page.on("pageerror", (error) => problems.push(error.message));
      await page.addInitScript((name) => localStorage.setItem("recorder-build", name), build.toLowerCase());
      await page.goto(path);
      const recorder = page.locator(`recorder-${build.toLowerCase()} .rec`);
      await expect(recorder).toBeVisible();
      return recorder;
    };

    test.afterEach(() => expect(problems).toEqual([]));

    test("starts with the latest real run, complete", async ({ page }) => {
      const recorder = await open(page);
      await expect(page.getByRole("radio", { name: build })).toBeChecked();
      await expect(recorder.getByRole("button", { name: "All three clouds" })).toHaveAttribute("aria-pressed", "true");
      await expect(recorder.locator(".rec-tag")).toHaveText("Real run");
      await expect(recorder.locator(".rec-lane")).toHaveCount(3);
      await expect(recorder.locator(".rec-pen path:not(.rest)")).toHaveCount(33);
      await expect(recorder.getByRole("link", { name: "Open this run on GitHub" })).toHaveAttribute("href", /^https:\/\/github\.com\/oplf-svg\/cloud-labs\/actions\/runs\/\d+$/);
      await expect(page.locator("#measured")).toHaveText(/^\d+ KB compressed, ready in \d+ ms on your device$/);
    });

    test("plays, pauses and carries on", async ({ page }) => {
      const recorder = await open(page);
      const slider = recorder.getByRole("slider");
      await recorder.getByRole("button", { name: "Play" }).click();
      await expect.poll(async () => Number(await slider.inputValue())).toBeGreaterThan(20);
      await expect.poll(async () => Number(await slider.inputValue())).toBeLessThan(900);
      await recorder.getByRole("button", { name: "Pause" }).click();
      await expect(recorder.getByRole("button", { name: "Carry on" })).toBeVisible();
      const paused = Number(await slider.inputValue());
      await page.waitForTimeout(400);
      expect(Number(await slider.inputValue())).toBe(paused);
      await recorder.getByRole("button", { name: "Carry on" }).click();
      await expect.poll(async () => Number(await slider.inputValue())).toBeGreaterThan(paused + 10);
    });

    test("shows the failed check of the first run", async ({ page }) => {
      const recorder = await open(page);
      await recorder.getByRole("button", { name: "The first try" }).click();
      await expect(recorder.locator(".rec-lane")).toHaveCount(2);
      await expect(recorder.locator(".rec-pen path.k-wrong")).toHaveCount(1);
      const back = recorder.getByRole("button", { name: "Previous mark" });
      const readout = recorder.locator(".rec-readout");
      for (let n = 20; n > 0; n--) {
        await back.click();
        await expect(recorder.getByRole("slider")).toHaveAttribute("aria-valuetext", new RegExp(`^${n} of 21,`));
        if ((await readout.textContent())?.includes("read the state of webhook-platform")) break;
      }
      await expect(readout).toContainText("read the state of webhook-platform");
      await expect(readout).toContainText("Let in, but it should be refused");
      await expect(recorder.locator(".rec-pen path.k-wrong.now")).toHaveCount(1);
    });

    test("marks the example as one, with and without the checks", async ({ page }) => {
      const recorder = await open(page);
      await recorder.getByRole("button", { name: "A bad day" }).click();
      await expect(recorder.locator(".rec-tag")).toHaveText("Example");
      await expect(recorder.getByRole("link")).toHaveCount(0);
      await expect(recorder.locator(".rec-lane")).toHaveCount(6);
      await expect(recorder.locator(".rec-pen path:not(.rest)")).toHaveCount(10);
      await recorder.getByRole("button", { name: "Without the checks" }).click();
      await expect(recorder.locator(".rec-pen path:not(.rest)")).toHaveCount(1);
      await expect(recorder.locator(".rec-readout")).toContainText("Nobody knows when it started");
      await recorder.getByRole("button", { name: "With the checks" }).click();
      await expect(recorder.locator(".rec-pen path:not(.rest)")).toHaveCount(10);
    });

    test("shows that many small steps are one attack", async ({ page }) => {
      const recorder = await open(page);
      await recorder.getByRole("button", { name: "Agents attack together" }).click();
      await expect(recorder.locator(".rec-tag")).toHaveText("Example");
      await expect(recorder.locator(".rec-lane")).toHaveCount(7);
      await recorder.getByRole("button", { name: "Without the checks" }).click();
      await expect(recorder.locator(".rec-pen path:not(.rest)")).toHaveCount(2);
      await expect(recorder.locator(".rec-readout")).toContainText("Each request looked harmless");
    });

    test("reads a mark that is pointed at, and goes to one that is clicked", async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      const recorder = await open(page);
      await recorder.getByRole("button", { name: "The first try" }).click();
      const aws = recorder.locator(".rec-pen").first();
      await aws.scrollIntoViewIfNeeded();
      await expect(recorder.locator(".rec-pen path.k-wrong")).toHaveCount(1);
      const red = (await recorder.locator(".rec-pen path.k-wrong").boundingBox())!;
      const readout = recorder.locator(".rec-readout");
      const slider = recorder.getByRole("slider");
      await page.mouse.move(red.x + red.width / 2, red.y + red.height / 2);
      await expect(readout).toContainText("read the state of webhook-platform");
      await expect(slider).toHaveValue("1000");
      await page.mouse.move(0, 0);
      await expect(readout).toContainText("write its own state");
      await page.mouse.click(red.x + red.width / 2, red.y + red.height / 2);
      await expect(slider).not.toHaveValue("1000");
      await page.mouse.move(0, 0);
      await expect(readout).toContainText("Let in, but it should be refused");
    });

    test("works with the keyboard alone and says where it is", async ({ page }) => {
      const recorder = await open(page);
      const slider = recorder.getByRole("slider", { name: "Position in the recording" });
      await slider.focus();
      await page.keyboard.press("Home");
      await expect(slider).toHaveAttribute("aria-valuetext", "Nothing has been recorded yet.");
      await expect(recorder.getByRole("button", { name: "Play" })).toBeVisible();
      await recorder.getByRole("button", { name: "Next mark" }).focus();
      await page.keyboard.press("Enter");
      await page.keyboard.press("Space");
      await expect(slider).toHaveAttribute("aria-valuetext", /^2 of 33, \+\d+\.\d s, /);
      await expect(recorder.locator(".rec-readout")).toHaveAttribute("aria-live", "polite");
      await slider.focus();
      await page.keyboard.press("End");
      await expect(slider).toHaveAttribute("aria-valuetext", /^33 of 33/);
    });

    test("jumps instead of sliding for readers who want less motion", async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      const recorder = await open(page);
      expect(await recorder.locator(".rec-pen").first().evaluate((pen) => getComputedStyle(pen).animationName)).toBe("none");
      const seen = new Set<string>();
      await recorder.getByRole("button", { name: "Play" }).click();
      const slider = recorder.getByRole("slider");
      const end = Date.now() + 2500;
      while (Date.now() < end) seen.add(await slider.inputValue());
      // Sliding would show many more places than there are marks in that time.
      expect(seen.size).toBeLessThan(12);
    });

    for (const [path, play, title] of [["/es/", "Reproducir", "Las tres nubes"], ["/fr/", "Lecture", "Les trois clouds"]] as const) {
      test(`speaks the language of ${path}`, async ({ page }) => {
        const recorder = await open(page, path);
        await expect(recorder.getByRole("button", { name: play })).toBeVisible();
        await expect(recorder.getByRole("button", { name: title })).toHaveAttribute("aria-pressed", "true");
      });
    }

    for (const scheme of ["light", "dark"] as const) {
      test(`has no accessibility problems that axe can find, ${scheme}`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
        const recorder = await open(page);
        for (const name of ["All three clouds", "The first try", "A bad day", "Agents attack together"]) {
          await recorder.getByRole("button", { name }).click();
          const { violations } = await new AxeBuilder({ page }).include(`recorder-${build.toLowerCase()}`).analyze();
          expect(violations.map((violation) => `${name}: ${violation.id} ${violation.nodes[0]?.html}`)).toEqual([]);
        }
      });
    }

    test("fits a narrow phone", async ({ page }) => {
      await page.setViewportSize({ width: 320, height: 700 });
      const recorder = await open(page);
      for (const name of ["All three clouds", "The first try", "A bad day", "Agents attack together"]) {
        await recorder.getByRole("button", { name }).click();
        expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBe(0);
      }
    });
  });
}

test("makes the same elements in both builds", async ({ page }) => {
  const shapes: string[][] = [];
  for (const build of ["angular", "react"]) {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.getByRole("radio", { name: new RegExp(build, "i") }).check();
    const recorder = page.locator(`recorder-${build} .rec`);
    await expect(recorder).toBeVisible();
    await recorder.getByRole("button", { name: "A bad day" }).click();
    await expect(recorder.locator(".rec-tag")).toHaveText("Example");
    shapes.push(
      await recorder.evaluate((rec) =>
        [rec, ...rec.querySelectorAll("*")].map((element) => `${element.tagName.toLowerCase()} ${[...element.classList].toSorted().join(".")} ${[...element.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent!.trim()).join("")} ${element.getAttribute("d") ?? ""}`),
      ),
    );
  }
  expect(shapes[0]).toEqual(shapes[1]);
});

test("switches builds and remembers the choice", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("recorder-angular .rec")).toBeVisible();
  await page.getByRole("radio", { name: "React" }).check();
  await expect(page.locator("recorder-react .rec")).toBeVisible();
  await expect(page.locator("recorder-angular")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("recorder-react .rec")).toBeVisible();
  await expect(page.getByRole("radio", { name: "React" })).toBeChecked();
});

test("still has everything when the recorder cannot load", async ({ page }) => {
  await page.route("**/builds/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#stage")).toHaveText("The recorder couldn't load. The list below has everything in it.");
  await page.locator("summary").first().click();
  await expect(page.locator("details[open] tbody tr")).toHaveCount(33);
});
