// Static build of the public landing page, served from Cloudflare Pages on the apex domain.
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://closetcompute.online",
  integrations: [react()],
  vite: { plugins: [tailwindcss()] },
});
