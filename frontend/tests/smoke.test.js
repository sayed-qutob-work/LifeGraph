import { describe, it, expect } from "vitest";
import fc from "fast-check";

describe("smoke test", () => {
  it("vitest runs", () => {
    expect(true).toBe(true);
  });

  it("fast-check runs", () => {
    fc.assert(
      fc.property(fc.integer(), (n) => {
        return typeof n === "number";
      })
    );
  });
});
