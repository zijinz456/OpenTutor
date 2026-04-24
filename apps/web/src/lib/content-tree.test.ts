import { describe, expect, it } from "vitest";
import type { ContentNode } from "./api/courses";
import {
  buildFocusTerms,
  collectContentNodes,
  findFirstContentNode,
  findNodeById,
  findPathToNode,
} from "./content-tree";

function makeNode(
  id: string,
  title: string,
  content: string,
  children: ContentNode[] = [],
): ContentNode {
  return {
    id,
    title,
    type: "section",
    content,
    level: 0,
    order_index: 0,
    source_type: "test",
    children,
  };
}

const tree: ContentNode[] = [
  makeNode("chapter-1", "Chapter 1", "", [
    makeNode("node-a", "Binary Search", "How binary search works"),
    makeNode("node-b", "Two Pointers", "", [
      makeNode("node-c", "Sliding Window", "Window technique notes"),
    ]),
  ]),
];

describe("content-tree helpers", () => {
  it("finds the first node with content", () => {
    expect(findFirstContentNode(tree)?.id).toBe("node-a");
  });

  it("finds nodes by id", () => {
    expect(findNodeById(tree, "node-c")?.title).toBe("Sliding Window");
    expect(findNodeById(tree, "missing")).toBeNull();
  });

  it("collects content nodes in traversal order", () => {
    expect(collectContentNodes(tree).map((node) => node.id)).toEqual(["node-a", "node-c"]);
  });

  it("builds the path to a nested node", () => {
    expect(findPathToNode(tree, "node-c").map((node) => node.id)).toEqual([
      "chapter-1",
      "node-b",
      "node-c",
    ]);
  });

  it("builds deduplicated focus terms from titles", () => {
    expect(buildFocusTerms(tree[0].children![1]).slice(0, 4)).toEqual([
      "two",
      "pointers",
      "sliding",
      "window",
    ]);
  });
});
