"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

/**
 * Markdown renderer with Mermaid diagram + KaTeX math support.
 *
 * - KaTeX: inline ($...$) and block ($$...$$) math
 * - Mermaid: ```mermaid code blocks rendered as diagrams
 * - Standard markdown: headings, lists, tables, code blocks
 */

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "default" });
        if (ref.current && !cancelled) {
          const { svg } = await mermaid.render(`mermaid-${Date.now()}`, code);
          if (ref.current && !cancelled) {
            ref.current.innerHTML = svg;
          }
        }
      } catch {
        if (ref.current && !cancelled) {
          ref.current.textContent = code;
        }
      }
    })();
    return () => { cancelled = true; };
  }, [code]);

  return <div ref={ref} className="my-4 flex justify-center" />;
}

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={className}>
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        code({ className: codeClassName, children, ...props }) {
          const match = /language-(\w+)/.exec(codeClassName || "");
          const language = match?.[1];

          if (language === "mermaid") {
            return <MermaidBlock code={String(children).trim()} />;
          }

          // Regular code block
          if (language) {
            return (
              <pre className="bg-muted rounded-md p-3 my-2 overflow-x-auto text-sm">
                <code className={codeClassName} {...props}>
                  {children}
                </code>
              </pre>
            );
          }

          // Inline code
          return (
            <code className="bg-muted px-1 py-0.5 rounded text-sm" {...props}>
              {children}
            </code>
          );
        },
        table({ children }) {
          return (
            <div className="my-4 overflow-x-auto">
              <table className="w-full border-collapse border border-border text-sm">
                {children}
              </table>
            </div>
          );
        },
        th({ children }) {
          return (
            <th className="border border-border bg-muted px-3 py-2 text-left font-medium">
              {children}
            </th>
          );
        },
        td({ children }) {
          return (
            <td className="border border-border px-3 py-2">{children}</td>
          );
        },
      }}
    />
    </div>
  );
}
