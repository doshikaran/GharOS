import { afterEach, describe, expect, it, vi } from "vitest";
import { getApiBaseUrl } from "./api-base-url";

describe("getApiBaseUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("falls back to the local dev API address when NEXT_PUBLIC_API_BASE_URL is unset", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    expect(getApiBaseUrl()).toBe("http://localhost:8000");
  });

  it("reads NEXT_PUBLIC_API_BASE_URL when set", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://gharos-api-971309809251.asia-south1.run.app");
    expect(getApiBaseUrl()).toBe("https://gharos-api-971309809251.asia-south1.run.app");
  });

  it("strips a trailing slash so callers can safely concatenate a path", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://example.run.app/");
    expect(getApiBaseUrl()).toBe("https://example.run.app");
  });

  it("ignores a whitespace-only value and falls back to the default", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "   ");
    expect(getApiBaseUrl()).toBe("http://localhost:8000");
  });
});
