import { defineConfig } from "astro/config";

export default defineConfig({
  trailingSlash: "always",
  devToolbar: { enabled: false },
  // Only the site's own scripts and styles may run, even if someone manages to put other ones into a page.
  security: { csp: { directives: ["default-src 'none'", "img-src 'self' data:", "font-src 'self'", "connect-src 'self'", "base-uri 'none'", "form-action 'none'"] } },
  vite: { server: { fs: { allow: [".."] } } },
});
