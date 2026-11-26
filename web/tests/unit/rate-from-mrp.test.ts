import { describe, expect, it } from "vitest";

import { mrpProblem, rateFromMrp } from "../../src/screens/products/saleRate";

describe("the rate an MRP implies (D-106)", () => {
  it("is MRP / (1 + GST%), half up to the paisa, in whole-number arithmetic", () => {
    expect(rateFromMrp("100", "18", true)).toBe("84.75"); // Pankaj's example: 84.7457...
    expect(rateFromMrp("413", "18", true)).toBe("350.00");
    expect(rateFromMrp("105", "5", true)).toBe("100.00");
    expect(rateFromMrp("100", "0.25", true)).toBe("99.75");
    expect(rateFromMrp("126.79", "5", true)).toBe("120.75");
    expect(rateFromMrp("0.01", "18", true)).toBe("0.01");
    expect(rateFromMrp("123456789012.99", "28", true)).toBe("96450616416.40");
  });

  it("is the MRP itself outside GST, and nothing when it can't be read yet", () => {
    expect(rateFromMrp("62.5", null, false)).toBe("62.50");
    expect(rateFromMrp("100", null, true)).toBeNull();
    expect(rateFromMrp("", "18", true)).toBeNull();
    expect(rateFromMrp("10.", "18", true)).toBe("8.47");
    expect(rateFromMrp("1.234", "18", true)).toBeNull();
    expect(rateFromMrp("-5", "18", true)).toBeNull();
  });

  it("the MRP is required on save", () => {
    expect(mrpProblem("", true)).toBe("Enter the MRP, the price per unit with GST included.");
    expect(mrpProblem("", false)).toBeUndefined();
  });
});
