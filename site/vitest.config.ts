import { defineConfig } from "vitest/config";

export default defineConfig({ test: { include: ["packages/core/test/**/*.test.ts", "scripts/**/*.test.mjs", "pages/test/**/*.test.ts", "deploy/**/*.test.mjs"] } });
