/** Vitest config: plain Node environment; Workers bindings are mocked in tests. */
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
    environment: "node",
  },
});
