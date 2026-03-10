import { describe, it, expect } from "vitest";

describe("smoke test", () => {
  it("verifies the test infrastructure works", () => {
    expect(1 + 1).toBe(2);
  });

  it("resolves the @/ path alias", async () => {
    const { t } = await import("@/test-utils");
    // en.json should have this key
    expect(t("nav.dashboard")).toBe("Home");
  });
});
