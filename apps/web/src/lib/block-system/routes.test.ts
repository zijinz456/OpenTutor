import { describe, it, expect } from "vitest";
import { blockRouteHref } from "./routes";

describe("blockRouteHref", () => {
  it("maps block types to their canonical routes", () => {
    expect(blockRouteHref("wrong_answers", "c1")).toBe("/course/c1/practice?tab=mistakes");
    expect(blockRouteHref("knowledge_graph", "c1")).toBe("/course/c1/profile?tab=graph");
    expect(blockRouteHref("review", "c1")).toBe("/course/c1/review");
    expect(blockRouteHref("notes", "c1")).toBe("/course/c1/notes");
  });

  it("returns null for blocks without a dedicated route", () => {
    expect(blockRouteHref("chapter_list", "c1")).toBeNull();
    expect(blockRouteHref("summary", "c1")).toBeNull();
    expect(blockRouteHref("agent_insight", "c1")).toBeNull();
  });
});
