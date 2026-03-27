const MERMAID_FENCE_RE = /```mermaid[^\n]*\n([\s\S]*?)```/gi;

function normalizeLineEndings(value: string): string {
  return value.replace(/\r\n?/g, "\n");
}

function sanitizeMindmapLabel(rawLabel: string): string {
  let label = rawLabel.trim();
  label = label.replace(/^[-*+]\s+/, "");
  label = label.replace(/^:+\s*/, "");
  label = label.replace(/`([^`]*)`/g, "$1");
  label = label.replace(/["'`{}[\]<>]/g, " ");
  label = label.replace(/[()]/g, " ");
  label = label.replace(/[:;,]/g, " ");
  label = label.replace(/\s+/g, " ").trim();
  return label;
}

function sanitizeMindmapRoot(line: string): string {
  const match = /^root\(\((.*)\)\)$/.exec(line.trim());
  if (!match) return "root((Topic))";
  const label = sanitizeMindmapLabel(match[1]) || "Topic";
  return `root((${label}))`;
}

function stabilizeMindmapCode(code: string): string {
  const lines = normalizeLineEndings(code)
    .split("\n")
    .map((line) => line.replace(/\s+$/, ""));
  const headerIndex = lines.findIndex((line) => line.trim().toLowerCase() === "mindmap");
  if (headerIndex === -1) return code.trim();

  const stabilized: string[] = ["mindmap"];
  let sawRoot = false;

  for (const originalLine of lines.slice(headerIndex + 1)) {
    const trimmed = originalLine.trim();
    if (!trimmed || trimmed.startsWith("%%")) continue;

    const indent = (originalLine.match(/^\s*/) || [""])[0].replace(/\t/g, "  ");
    if (trimmed.startsWith("root(")) {
      stabilized.push(`${indent || "  "}${sanitizeMindmapRoot(trimmed)}`);
      sawRoot = true;
      continue;
    }

    const label = sanitizeMindmapLabel(trimmed);
    if (!label) continue;
    stabilized.push(`${indent}${label}`);
  }

  if (!sawRoot) {
    stabilized.splice(1, 0, "  root((Topic))");
  }

  return stabilized.join("\n").trim();
}

function extractMindmapRootLabel(line: string): string {
  const match = /^root\(\((.*)\)\)$/.exec(line.trim());
  return sanitizeMindmapLabel(match?.[1] ?? line) || "Topic";
}

function buildMindmapOutline(code: string): string {
  const stabilized = stabilizeMindmapCode(code);
  const lines = stabilized.split("\n").slice(1);
  const bodyLines = lines.filter((line) => line.trim());
  if (bodyLines.length === 0) return stabilized;

  const positiveIndents = bodyLines
    .map((line) => (line.match(/^\s*/) || [""])[0].length)
    .filter((indent) => indent > 0);
  const baseIndent = positiveIndents.length > 0 ? Math.min(...positiveIndents) : 0;

  const outline: string[] = [];
  for (const line of bodyLines) {
    const indent = (line.match(/^\s*/) || [""])[0].length;
    const trimmed = line.trim();
    if (trimmed.startsWith("root(")) {
      outline.push(extractMindmapRootLabel(trimmed));
      continue;
    }

    const label = sanitizeMindmapLabel(trimmed);
    if (!label) continue;

    const depth = Math.max(0, Math.floor((indent - baseIndent) / 2));
    outline.push(`${"  ".repeat(depth)}- ${label}`);
  }

  return outline.join("\n");
}

export function stabilizeMermaidCode(code: string): string {
  const normalized = normalizeLineEndings(code).trim();
  const [header] = normalized.split("\n").map((line) => line.trim()).filter(Boolean);
  if (!header) return normalized;

  if (header.toLowerCase() === "mindmap") {
    return stabilizeMindmapCode(normalized);
  }

  return normalized;
}

export function stabilizeMarkdownMermaidBlocks(markdown: string): string {
  return normalizeLineEndings(markdown).replace(MERMAID_FENCE_RE, (_match, code: string) => {
    const stabilized = stabilizeMermaidCode(code);
    return `\`\`\`mermaid\n${stabilized}\n\`\`\``;
  });
}

export function buildMermaidFallbackText(code: string): string {
  const normalized = stabilizeMermaidCode(code);
  if (normalized.startsWith("mindmap\n")) {
    return buildMindmapOutline(normalized);
  }
  return normalized;
}

