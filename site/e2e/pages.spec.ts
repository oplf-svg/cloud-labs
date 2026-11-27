import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const PATHS = ["/", "/proof/", "/notes/", "/notes/the-check-that-proved-nothing/", "/how/"];
const PREFIXES = { en: "", es: "/es", fr: "/fr" };

for (const [lang, prefix] of Object.entries(PREFIXES)) {
  for (const path of PATHS) {
    test(`${prefix}${path}`, async ({ page }) => {
      const problems: string[] = [];
      page.on("console", (message) => ["error", "warning"].includes(message.type()) && problems.push(message.text()));
      page.on("pageerror", (error) => problems.push(error.message));
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(prefix + path);
      await expect(page.locator("html")).toHaveAttribute("lang", lang);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(page.locator(`link[rel=alternate]`)).toHaveCount(3);
      for (const scheme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme: scheme });
        const { violations } = await new AxeBuilder({ page }).analyze();
        expect(violations.map((violation) => `${scheme}: ${violation.id} ${violation.nodes.map((node) => node.html).slice(0, 2)}`)).toEqual([]);
      }
      for (const width of [320, 768, 1440]) {
        await page.setViewportSize({ width, height: 800 });
        expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), `${width}`).toBe(0);
      }
      expect(problems).toEqual([]);
    });
  }
}

test("every link inside the site leads somewhere", async ({ page, request }) => {
  const seen = new Set<string>();
  const waiting = ["/", "/es/", "/fr/"];
  for (let path = waiting.shift(); path; path = waiting.shift()) {
    if (seen.has(path)) continue;
    seen.add(path);
    expect((await request.get(path)).status(), path).toBe(200);
    await page.goto(path);
    for (const href of await page.locator("a[href^='/']").evaluateAll((links) => links.map((link) => new URL((link as HTMLAnchorElement).href).pathname))) waiting.push(href);
  }
  expect(seen.size).toBe(21);
});

test("serves the licences of what others wrote beside the builds", async ({ request }) => {
  const served = await request.get("/builds/third-party.txt");
  expect(served.status()).toBe(200);
  expect(served.headers()["content-type"]).toMatch(/^text\/plain/);
  const text = await served.text();
  for (const name of ["react", "react-dom", "@angular/core", "rxjs", "@fontsource-variable/atkinson-hyperlegible-next"]) expect(text).toMatch(new RegExp(`^${name} \\d+\\.\\d+\\.\\d+$`, "m"));
  for (const build of ["react", "angular"]) expect((await (await request.get(`/builds/${build}/main.js`)).text()).split("\n")[0]).toBe("/*! Licences of what others wrote: /builds/third-party.txt */");
});

test("shows the claims behind one door", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /^Security/ }).click();
  await expect(page).toHaveURL(/\/proof\/\?for=security$/);
  await expect(page.getByRole("button", { name: "Security" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("[data-doors]:visible")).toHaveCount(10);
  for (const claim of await page.locator("[data-doors]:visible").all()) expect(await claim.getAttribute("data-doors")).toContain("security");
  await page.getByRole("button", { name: "AI", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Proven", exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Everyone" }).click();
  await expect(page.locator("[data-doors]:visible")).toHaveCount(26);
  await expect(page).toHaveURL(/\/proof\/$/);
});

test("opens with the first real run, and says what its red mark was", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".trace path:not(.rest)")).toHaveCount(21);
  await expect(page.locator(".trace .k-wrong")).toHaveCount(1);
  for (const prefix of Object.values(PREFIXES)) {
    await page.goto(`${prefix}/`);
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 800 });
      const [link, box] = await Promise.all([page.locator(".flag a").boundingBox(), page.locator(".flags").boundingBox()]);
      expect(link!.y + link!.height, `${prefix} ${width}`).toBeLessThanOrEqual(box!.y + box!.height);
      expect(link!.x, `${prefix} ${width}`).toBeGreaterThanOrEqual(0);
    }
  }
  await page.goto("/");
  await page.getByRole("link", { name: "A real run: what was its red mark?" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("The check that proved nothing");
});

test("keeps the failed run on the list", async ({ page }) => {
  await page.goto("/proof/");
  await expect(page.locator("#runs summary")).toHaveCount(5);
  const first = page.locator("#runs details").first();
  await expect(first.locator("summary")).toContainText("21 checks, 1 wrong answer");
  await first.locator("summary").click();
  await expect(first.locator("tr", { hasText: "read the state of webhook-platform" })).toContainText("Let in, but it should be refused");
});

test("works without scripts", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("http://localhost:4330/proof/");
  await expect(page.locator("[data-doors]:visible")).toHaveCount(26);
  await expect(page.locator("#doors")).toBeHidden();
  await page.goto("http://localhost:4330/");
  await expect(page.locator("noscript p")).toHaveText(/^The recorder needs JavaScript/);
  await expect(page.locator("noscript p")).toBeVisible();
  await expect(page.locator("#builds")).toBeHidden();
  await context.close();
});

test("loads nothing from anywhere else, and sets no cookies", async ({ page, context }) => {
  const elsewhere: string[] = [];
  page.on("request", (request) => new URL(request.url()).host !== "localhost:4330" && !request.url().startsWith("data:") && elsewhere.push(request.url()));
  for (const path of PATHS) await page.goto(path, { waitUntil: "networkidle" });
  expect(elsewhere).toEqual([]);
  expect(await context.cookies()).toEqual([]);
});

for (const prefix of Object.values(PREFIXES)) {
  test(`says nothing to machines that a person cannot see, ${prefix}/`, async ({ page, request }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1280, height: 900 });
    for (const path of PATHS) {
      const html = await (await request.get(prefix + path)).text();
      expect(html, "comments").not.toContain("<!--");
      expect(html, "invisible or reordering characters").not.toMatch(/[\u00AD\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF\u{E0000}-\u{E0FFF}]/u);
      await page.goto(prefix + path);
      if (path === "/") await expect(page.locator(".rec")).toBeVisible();
      const unseen = await page.evaluate(() => {
        const found: string[] = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const text = node.textContent!.trim();
          const element = node.parentElement!;
          // A person can open a list, and the link that skips the menu appears as soon as it is reached.
          if (!text || element.closest("script, noscript, details:not([open]) > :not(summary), .skip")) continue;
          const box = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          const visible = element.checkVisibility({ opacityProperty: true, visibilityProperty: true }) && box.width > 1 && box.height > 1 && box.right > 0 && box.left < innerWidth;
          if (!visible || parseFloat(style.fontSize) < 12) found.push(text);
        }
        return found;
      });
      expect(unseen).toEqual([]);
      const labels = await page.locator("[aria-label], [title], [alt]").evaluateAll((all) => all.map((one) => `${one.getAttribute("aria-label") ?? ""}${one.getAttribute("title") ?? ""}${one.getAttribute("alt") ?? ""}`));
      for (const label of labels) expect(label.length, label).toBeLessThan(80);
    }
  });
}

test("refuses scripts that are not the site's own", async ({ page }) => {
  await page.goto("/");
  const blocked = page.waitForEvent("console", (message) => message.text().includes("Content Security Policy"));
  await page.evaluate(() => {
    const script = document.createElement("script");
    script.textContent = "document.title = 'taken over'";
    document.body.append(script);
  });
  await blocked;
  await expect(page).not.toHaveTitle("taken over");
});

test("says so when a page does not exist", async ({ page }) => {
  const response = await page.goto("/nowhere/");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This page isn't here");
});
