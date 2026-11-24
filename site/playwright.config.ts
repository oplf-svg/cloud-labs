import { defineConfig } from "@playwright/test";

// The tests use the Chrome that is already on this computer, and the site as it would be published.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: true,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:4330", channel: "chrome" },
  webServer: { command: "npm run preview -w pages -- --port 4330 --ignore-lock", url: "http://localhost:4330", reuseExistingServer: false },
});
