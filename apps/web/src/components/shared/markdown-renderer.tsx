"use client";

import { useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { buildMermaidFallbackText, stabilizeMermaidCode } from "@/lib/markdown/mermaid";
import "katex/dist/katex.min.css";

type MermaidInstance = typeof import("mermaid")["default"];

let mermaidLoader: Promise<MermaidInstance> | null = null;

function getMermaid() {
  if (!mermaidLoader) {
    mermaidLoader = import("mermaid").then(({ default: mermaid }) => {
      mermaid.initialize({
        startOnLoad: false,
        theme: "default",
        suppressErrorRendering: true,
      });
      return mermaid;
    });
  }
  return mermaidLoader;
}

function createMermaidRenderId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `mermaid-${crypto.randomUUID()}`;
  }
  return `mermaid-${Math.random().toString(36).slice(2, 10)}`;
}

function MermaidBlock({ code }: { code: string }) {
  const renderIdRef = useRef<string | null>(null);
  const [svgMarkup, setSvgMarkup] = useState("");
  const [fallbackText, setFallbackText] = useState("");

  if (renderIdRef.current == null) {
    renderIdRef.current = createMermaidRenderId();
  }

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const mermaid = await getMermaid();
        const preparedCode = stabilizeMermaidCode(code);
        const renderId = renderIdRef.current ?? createMermaidRenderId();
        renderIdRef.current = renderId;
        const { svg } = await mermaid.render(renderId, preparedCode);
        if (!cancelled) {
          setSvgMarkup(DOMPurify.sanitize(svg));
          setFallbackText("");
        }
      } catch {
        if (!cancelled) {
          setSvgMarkup("");
          setFallbackText(buildMermaidFallbackText(code));
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code]);

  if (svgMarkup) {
    return (
      <div
        className="my-4 flex justify-center"
        dangerouslySetInnerHTML={{ __html: svgMarkup }}
      />
    );
  }

  if (fallbackText) {
    return (
      <div className="my-4">
        <div className="rounded-xl border border-border/60 bg-muted/20 p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            Diagram preview unavailable. Showing a text outline instead.
          </p>
          <pre className="whitespace-pre-wrap text-sm text-foreground">{fallbackText}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className="my-4">
      <div className="rounded-xl border border-border/40 bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
        Rendering diagram...
      </div>
    </div>
  );
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
    <div role="article" className={className}>
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
                <pre className="my-2 overflow-x-auto rounded-xl bg-muted/30 p-3.5 text-sm">
                  <code className={codeClassName} {...props}>
                    {children}
                  </code>
                </pre>
              );
            }

            return (
              <code className="rounded-md bg-muted/30 px-1 py-0.5 text-sm" {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="my-4 overflow-x-auto">
                <table className="w-full border-collapse border border-border/60 text-sm">
                  {children}
                </table>
              </div>
            );
          },
          th({ children }) {
            return (
              <th className="border border-border/60 bg-muted/30 px-3 py-2 text-left font-medium">
                {children}
              </th>
            );
          },
          td({ children }) {
            return <td className="border border-border/60 px-3 py-2">{children}</td>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
