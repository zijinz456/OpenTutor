import { describe, it, expect } from "vitest";
import { activeTabFromPathname } from "./chat-input-utils";

describe("activeTabFromPathname", () => {
  it("derives the active tab from the course route", () => {
    expect(activeTabFromPathname("/course/abc/practice")).toBe("practice");
    expect(activeTabFromPathname("/course/abc/notes")).toBe("notes");
    expect(activeTabFromPathname("/course/abc/plan")).toBe("plan");
    expect(activeTabFromPathname("/course/abc/review")).toBe("review");
    expect(activeTabFromPathname("/course/abc/unit/n1")).toBe("unit");
    expect(activeTabFromPathname("/course/abc/profile")).toBe("analytics");
  });

  it("falls back to workspace", () => {
    expect(activeTabFromPathname("/course/abc")).toBe("workspace");
    expect(activeTabFromPathname("/")).toBe("workspace");
    expect(activeTabFromPathname(null)).toBe("workspace");
  });
});
