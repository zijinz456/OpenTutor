import { describe, expect, it } from "vitest";
import {
  buildMermaidFallbackText,
  stabilizeMarkdownMermaidBlocks,
  stabilizeMermaidCode,
} from "./mermaid";

describe("stabilizeMermaidCode", () => {
  it("simplifies risky mindmap labels into safer plain text", () => {
    const input = [
      "mindmap",
      "  root((Python Data Types))",
      "    Basic Types",
      "      int (integer)",
      "        : Immutable",
      "        : Example: 42",
      "      dict",
      "        : Example: {\"a\": 1}",
    ].join("\n");

    const result = stabilizeMermaidCode(input);

    expect(result).toContain("root((Python Data Types))");
    expect(result).toContain("      int integer");
    expect(result).toContain("        Immutable");
    expect(result).toContain("        Example 42");
    expect(result).toContain("        Example a 1");
    expect(result).not.toContain(": Immutable");
    expect(result).not.toContain("{\"a\": 1}");
  });

  it("leaves non-mindmap diagrams untouched", () => {
    const input = "graph TD\n  A[Start] --> B[Finish]";
    expect(stabilizeMermaidCode(input)).toBe(input);
  });
});

describe("stabilizeMarkdownMermaidBlocks", () => {
  it("rewrites mermaid fences but preserves the surrounding markdown", () => {
    const markdown = [
      "# Title",
      "",
      "```mermaid",
      "mindmap",
      "  root((Topic))",
      "    Child",
      "      : Example: {\"a\": 1}",
      "```",
      "",
      "```python",
      "print('ok')",
      "```",
    ].join("\n");

    const result = stabilizeMarkdownMermaidBlocks(markdown);

    expect(result).toContain("# Title");
    expect(result).toContain("```mermaid\nmindmap");
    expect(result).toContain("Example a 1");
    expect(result).toContain("```python\nprint('ok')\n```");
  });
});

describe("buildMermaidFallbackText", () => {
  it("turns a mindmap into a readable outline", () => {
    const input = [
      "mindmap",
      "  root((Python Data Types))",
      "    Basic Types",
      "      int (integer)",
      "        : Immutable",
    ].join("\n");

    expect(buildMermaidFallbackText(input)).toBe(
      [
        "Python Data Types",
        "  - Basic Types",
        "    - int integer",
        "      - Immutable",
      ].join("\n"),
    );
  });
});

