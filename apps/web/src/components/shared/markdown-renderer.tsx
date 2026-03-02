"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "default" });
        if (!ref.current || cancelled) return;
        const { svg } = await mermaid.render(`mermaid-${Date.now()}`, code);
        if (ref.current && !cancelled) {
          ref.current.innerHTML = svg;
        }
      } catch {
        if (ref.current && !cancelled) {
          ref.current.textContent = code;
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code]);

  return <div ref={ref} className="my-4 flex justify-center" />;
}

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export function MarkdownRenderer({
  content,
  className,
}: MarkdownRendererProps) {
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

            if (language) {
              return (
                <pre className="my-2 overflow-x-auto rounded-md bg-muted p-3 text-sm">
                  <code className={codeClassName} {...props}>
                    {children}
                  </code>
                </pre>
              );
            }

            return (
              <code className="rounded bg-muted px-1 py-0.5 text-sm" {...props}>
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
            return <td className="border border-border px-3 py-2">{children}</td>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
