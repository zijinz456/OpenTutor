import { beforeEach, describe, expect, it } from "vitest";
import {
  loadStoredSpaceLayout,
  parseSpaceLayout,
  saveStoredSpaceLayout,
} from "./layout-storage";

describe("layout-storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns null for malformed layouts", () => {
    expect(parseSpaceLayout(null)).toBeNull();
    expect(parseSpaceLayout({})).toBeNull();
    expect(parseSpaceLayout({ blocks: "broken" })).toBeNull();
  });

  it("filters invalid blocks and repairs duplicate ids", () => {
    const layout = parseSpaceLayout({
      templateId: "quick_reviewer",
      columns: 4,
      mode: "exam_prep",
      blocks: [
        {
          id: "dup-id",
          type: "wrong_answers",
          position: 3,
          size: "medium",
          config: {},
          visible: true,
          source: "user",
        },
        {
          id: "dup-id",
          type: "quiz",
          position: 1,
          size: "gigantic",
          config: null,
          visible: "yes",
          source: "agent",
          agentMeta: { reason: "Needs retry", dismissible: false },
        },
        {
          id: "bad-type",
          type: "not_a_block",
          position: 0,
        },
      ],
    });

    expect(layout).not.toBeNull();
    expect(layout?.columns).toBe(2);
    expect(layout?.blocks).toHaveLength(2);
    expect(layout?.blocks[0].type).toBe("quiz");
    expect(layout?.blocks[0].size).toBe("medium");
    expect(layout?.blocks[0].id).not.toBe(layout?.blocks[1].id);
    expect(layout?.blocks[1].type).toBe("wrong_answers");
    expect(layout?.blocks[0].position).toBe(0);
    expect(layout?.blocks[1].position).toBe(1);
  });

  it("round-trips persisted layouts through local storage", () => {
    saveStoredSpaceLayout("course-1", {
      templateId: null,
      columns: 2,
      mode: "self_paced",
      blocks: [
        {
          id: "notes-1",
          type: "notes",
          position: 0,
          size: "large",
          config: {},
          visible: true,
          source: "template",
        },
      ],
    });

    expect(loadStoredSpaceLayout("course-1")).toEqual({
      templateId: null,
      columns: 2,
      mode: "self_paced",
      blocks: [
        {
          id: "notes-1",
          type: "notes",
          position: 0,
          size: "large",
          config: {},
          visible: true,
          source: "template",
          agentMeta: undefined,
        },
      ],
    });
  });
});
