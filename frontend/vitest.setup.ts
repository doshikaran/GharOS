import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Explicit cleanup: this project does not enable Vitest's `globals` mode,
// so @testing-library/react's automatic afterEach-based cleanup (which
// relies on detecting a global `afterEach`) never registers on its own.
afterEach(() => {
  cleanup();
});
