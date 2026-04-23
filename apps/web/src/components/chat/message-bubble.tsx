"use client";

import Image from "next/image";
import { Fragment, useState } from "react";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/store/chat";
import type { ChatCitationChunk } from "@/lib/api/chat";
import { ActionCard } from "@/components/chat/action-card";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/** Shorten a citation snippet for the tooltip body. */
function truncateSnippet(text: string, max = 100): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max).trimEnd()}...`;
}

/**
 * Render a string containing inline `[N]` citation markers as a mix of plain
 * text segments and interactive citation pills. Invalid/out-of-range indices
 * are rendered as plain text (same as before) — we trust the backend to drop
 * them but stay defensive.
 */
function renderAnswerWithCitations(
  answer: string,
  chunks: ChatCitationChunk[],
): React.ReactNode[] {
  const pattern = /\[(\d+)\]/g;
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let pillKey = 0;

  // biome-ignore lint: iterative regex match is the idiomatic form here.
  while ((match = pattern.exec(answer)) !== null) {
    const [raw, numStr] = match;
    const num = Number.parseInt(numStr, 10);
    const chunk = chunks[num - 1];

    if (match.index > lastIndex) {
      nodes.push(answer.slice(lastIndex, match.index));
    }

    if (chunk) {
      nodes.push(
        <TooltipProvider key={`pill-${pillKey++}`} delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                data-testid={`citation-pill-${num}`}
                aria-label={`Citation ${num}: ${chunk.source_file}`}
                className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-sm bg-emerald-500/20 px-1 align-baseline text-[10px] font-semibold text-emerald-800 hover:bg-emerald-500/30 dark:text-emerald-200"
              >
                {num}
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-xs">
              <div className="text-[11px] font-medium">{chunk.source_file}</div>
              <div className="mt-0.5 text-[10px] opacity-80">
                {truncateSnippet(chunk.snippet)}
              </div>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>,
      );
    } else {
      // Out-of-range index — keep the literal `[N]` so the user sees nothing
      // went missing from the text. Logged server-side as
      // `guardrails_invalid_citation`.
      nodes.push(raw);
    }

    lastIndex = match.index + raw.length;
  }

  if (lastIndex < answer.length) {
    nodes.push(answer.slice(lastIndex));
  }

  return nodes;
}

interface MessageBubbleProps {
  message: ChatMessage;
}

/**
 * Single message bubble.
 *
 * - User messages: right-aligned, chat-user colours.
 * - Assistant messages: left-aligned, chat-assistant colours with
 *   whitespace-pre-wrap (markdown renderer to be added later).
 * - Shows ActionCard components when metadata.actions is present.
 * - Displays attached images for user messages.
 * - Shows audio playback controls for voice responses.
 */
export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const actions = message.metadata?.actions;
  const verifier = message.metadata?.verifier;
  const diagnostics = message.metadata?.verifier_diagnostics;
  const contentRefs = message.metadata?.provenance?.content_refs ?? [];
  const evidenceGroups = message.metadata?.provenance?.content_evidence_groups ?? [];
  const guardrails = message.metadata?.guardrails ?? null;
  const images = message.images;
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

  // Phase 7 derived flags. `isRefusal` short-circuits citation rendering;
  // low confidence dims the bubble per critic concern #2 (strictly < 3 so the
  // common "3 = mixed" case is not dimmed).
  const isRefusal = Boolean(guardrails?.refusal_reason);
  const citationChunks = guardrails?.citation_chunks ?? [];
  const hasCitations = !isUser && !isRefusal && citationChunks.length > 0;
  const isLowConfidence =
    !isUser &&
    !isRefusal &&
    typeof guardrails?.confidence === "number" &&
    guardrails.confidence < 3;
  const strictActive = !isUser && guardrails?.strict_mode === true;

  const requestCoverage = typeof diagnostics?.request_coverage === "number"
    ? `${Math.round(diagnostics.request_coverage * 100)}%`
    : null;
  const evidenceCoverage = typeof diagnostics?.evidence_coverage === "number"
    ? `${Math.round(diagnostics.evidence_coverage * 100)}%`
    : null;

  return (
    <>
      <div
        role="article"
        aria-label={isUser ? "Your message" : "Assistant message"}
        className={cn("flex mb-2", isUser ? "justify-end" : "justify-start")}
        data-testid={isUser ? "chat-message-user" : "chat-message-assistant"}
        data-role={message.role}
      >
        <div
          data-guardrails-refusal={isRefusal ? "true" : undefined}
          data-guardrails-low-confidence={isLowConfidence ? "true" : undefined}
          style={isLowConfidence ? { opacity: 0.7 } : undefined}
          className={cn(
            "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm",
            isUser
              ? "bg-[var(--chat-user-bg,hsl(var(--primary)))] text-[var(--chat-user-fg,hsl(var(--primary-foreground)))] rounded-br-md"
              : "bg-[var(--chat-assistant-bg,hsl(var(--muted)))] text-[var(--chat-assistant-fg,hsl(var(--foreground)))] rounded-bl-md",
            isRefusal && "border border-destructive/60",
          )}
        >
          {/* Attached images (user messages) */}
          {isUser && images && images.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {images.map((img, i) => (
                <button
                  key={`${img.filename ?? "img"}-${i}`}
                  type="button"
                  aria-label={`Expand ${img.filename ?? `image ${i + 1}`}`}
                  className="rounded-md overflow-hidden border border-white/20 hover:opacity-80 transition-opacity"
                  onClick={() =>
                    setExpandedImage(`data:${img.media_type};base64,${img.data}`)
                  }
                >
                  <Image
                    src={`data:${img.media_type};base64,${img.data}`}
                    alt={img.filename ?? `Image ${i + 1}`}
                    width={80}
                    height={80}
                    unoptimized
                    className="h-20 w-20 object-cover"
                  />
                </button>
              ))}
            </div>
          )}

          {/* Message content */}
          {message.content && message.content !== "(image)" ? (
            <div className="whitespace-pre-wrap break-words">
              {hasCitations
                ? renderAnswerWithCitations(message.content, citationChunks).map(
                    (node, idx) => <Fragment key={idx}>{node}</Fragment>,
                  )
                : message.content}
            </div>
          ) : !images?.length ? (
            <span className="text-xs italic opacity-60">...</span>
          ) : null}

          {/* Phase 7 guardrails badges — refusal, low-confidence, strict pill. */}
          {!isUser && guardrails && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {isRefusal ? (
                <Badge
                  variant="destructive"
                  className="text-[10px]"
                  data-testid="guardrails-refusal-badge"
                >
                  Refused: no retrieval match
                </Badge>
              ) : null}
              {isLowConfidence ? (
                <Badge
                  variant="outline"
                  className="text-[10px]"
                  data-testid="guardrails-uncertain-badge"
                >
                  uncertain ({guardrails.confidence}/5)
                </Badge>
              ) : null}
              {strictActive && !isRefusal ? (
                <Badge
                  variant="outline"
                  className="border-emerald-500/50 text-[10px] text-emerald-700 dark:text-emerald-300"
                  data-testid="guardrails-strict-badge"
                >
                  Strict · {citationChunks.length} citation
                  {citationChunks.length === 1 ? "" : "s"}
                </Badge>
              ) : null}
            </div>
          )}

          {/* Action cards from metadata */}
          {!isUser && actions && actions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {actions.map((action, i) => (
                <ActionCard
                  key={`${action.action}-${i}`}
                  action={{
                    type: action.action,
                    label: action.value ?? action.action,
                    payload: action.extra ? { extra: action.extra } : undefined,
                  }}
                />
              ))}
            </div>
          )}

          {!isUser && (verifier || evidenceGroups.length > 0 || contentRefs.length > 0) && (
            <details
              className="mt-2 rounded-md bg-black/5 px-2 py-2 dark:bg-white/5"
              open={verifier?.status === "failed"}
            >
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 text-[11px] font-medium opacity-80">
                <span>Why this answer</span>
                {verifier ? (
                  <Badge variant="outline" className="text-[10px]">
                    {verifier.status}
                  </Badge>
                ) : null}
                {requestCoverage ? <Badge variant="outline" className="text-[10px]">Request {requestCoverage}</Badge> : null}
                {evidenceCoverage ? <Badge variant="outline" className="text-[10px]">Evidence {evidenceCoverage}</Badge> : null}
                {evidenceGroups.length > 0 ? (
                  <Badge variant="outline" className="text-[10px]">
                    {evidenceGroups.length} evidence group{evidenceGroups.length > 1 ? "s" : ""}
                  </Badge>
                ) : null}
              </summary>

              <div className="mt-2 space-y-2">
                {verifier && (
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[10px] opacity-75">{verifier.code}</span>
                    </div>
                    <p className="text-[11px] opacity-75">{verifier.message}</p>
                    {diagnostics?.request_overlap_terms?.length ? (
                      <p className="text-[10px] opacity-70">
                        Covered request terms: {diagnostics.request_overlap_terms.slice(0, 5).join(", ")}
                      </p>
                    ) : null}
                    {diagnostics?.evidence_overlap_terms?.length ? (
                      <p className="text-[10px] opacity-70">
                        Used evidence: {diagnostics.evidence_overlap_terms.slice(0, 5).join(", ")}
                      </p>
                    ) : null}
                  </div>
                )}

                {evidenceGroups.length > 0 ? (
                  <div className="space-y-1">
                    <p className="text-[10px] font-medium uppercase tracking-wide opacity-60">Merged evidence</p>
                    {evidenceGroups.map((group, index) => (
                      <div key={`${group.label ?? "group"}-${index}`} className="rounded border border-black/10 px-2 py-1.5 text-[11px] dark:border-white/10">
                        {group.label ? <p className="font-medium">{group.label}</p> : null}
                        {group.summary ? <p className="mt-0.5 opacity-80">{group.summary}</p> : null}
                        {group.titles?.length ? (
                          <p className="mt-1 text-[10px] opacity-70">
                            Sections: {group.titles.slice(0, 3).join(" · ")}
                          </p>
                        ) : null}
                        <div className="mt-1 flex flex-wrap gap-1">
                          {typeof group.section_count === "number" && group.section_count > 0 ? (
                            <Badge variant="outline" className="text-[10px]">
                              {group.section_count} linked hits
                            </Badge>
                          ) : null}
                          {group.matched_facets?.slice(0, 2).map((facet) => (
                            <Badge key={facet} variant="outline" className="text-[10px]">{facet}</Badge>
                          ))}
                          {(!group.matched_facets || group.matched_facets.length === 0) && group.matched_terms?.slice(0, 3).map((term) => (
                            <Badge key={term} variant="outline" className="text-[10px]">{term}</Badge>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : contentRefs.length > 0 ? (
                  <div className="space-y-1">
                    <p className="text-[10px] font-medium uppercase tracking-wide opacity-60">Evidence</p>
                    {contentRefs.slice(0, 2).map((ref, index) => (
                      <div key={`${ref.title ?? "evidence"}-${index}`} className="rounded border border-black/10 px-2 py-1.5 text-[11px] dark:border-white/10">
                        {ref.title ? <p className="font-medium">{ref.title}</p> : null}
                        {ref.evidence_summary ? (
                          <p className="mt-0.5 opacity-80">{ref.evidence_summary}</p>
                        ) : ref.preview ? (
                          <p className="mt-0.5 opacity-80">{ref.preview}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </details>
          )}
        </div>
      </div>

      {/* Expanded image overlay */}
      {expandedImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 cursor-pointer"
          onClick={() => setExpandedImage(null)}
          onKeyDown={(e) => { if (e.key === "Escape") setExpandedImage(null); }}
          role="dialog"
          aria-label="Expanded image view. Click or press Escape to close."
          aria-modal="true"
        >
          <Image
            src={expandedImage}
            alt="Expanded view"
            width={1440}
            height={1080}
            unoptimized
            className="max-h-[85vh] max-w-[90vw] rounded-lg object-contain"
          />
        </div>
      )}
    </>
  );
}

