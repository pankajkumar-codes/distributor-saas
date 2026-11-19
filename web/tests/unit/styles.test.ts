import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// A missing closing brace silently puts every rule after it inside the previous @media block, so those rules
// work on a phone and vanish on a desktop (the skip link was visible on desktop for this reason).
describe("styles.css", () => {
  it("has balanced braces", () => {
    const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""');
    let depth = 0;
    for (const ch of css) {
      if (ch === "{") depth++;
      if (ch === "}") depth--;
      expect(depth).toBeGreaterThanOrEqual(0);
    }
    expect(depth).toBe(0);
  });
});
