import { describe, expect, it } from "vitest";

import { apiOrigin } from "./origin";

describe("apiOrigin", () => {
  it("is the page's own origin when nothing is configured", () => {
    expect(apiOrigin(undefined, "http://localhost:5173")).toBe("http://localhost:5173");
    expect(apiOrigin("", "http://localhost:5173")).toBe("http://localhost:5173");
    expect(apiOrigin("  ", "http://localhost:5173")).toBe("http://localhost:5173");
  });

  it("uses the configured API origin without a trailing slash", () => {
    expect(apiOrigin("https://api.example.in/", "https://example.in")).toBe("https://api.example.in");
    expect(apiOrigin("https://api.example.in", "https://example.in")).toBe("https://api.example.in");
  });
});
