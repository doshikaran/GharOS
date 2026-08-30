import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: true,
    // ~120 jsdom test files. Vitest's default fan-out is one worker per
    // logical CPU (8 here), each carrying its own jsdom + React +
    // testing-library — on an 8 GB machine that pushes into swap, and the
    // resulting multi-second stalls both blow test timeouts and stretch
    // the gap between a test finishing and its still-pending `fetch`/SSE
    // `.then` firing (which then throws as a post-teardown passive-effect
    // error). Capping the pool keeps total memory in budget; the suite is
    // somewhat slower wall-clock but deterministic, which Gate 15 needs.
    // Raise this if you have plenty of RAM.
    maxWorkers: 3,
    // Generous ceiling so a trivial `render()` that briefly loses the CPU
    // to another worker is not counted as a hang (a genuinely stuck test
    // still fails, just later). Same rationale as the wall-clock ceiling
    // in `lib/graph-simulation.test.ts`.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
