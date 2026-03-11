"use client";

import Image from "next/image";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/store/chat";
import { ActionCard } from "@/components/chat/action-card";
import { Badge } from "@/components/ui/badge";

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
  const images = message.images;
  const [expandedImage, setExpandedImage] = useState<string | null>(null);

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
          className={cn(
            "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm",
            isUser
              ? "bg-[var(--chat-user-bg,hsl(var(--primary)))] text-[var(--chat-user-fg,hsl(var(--primary-foreground)))] rounded-br-md"
              : "bg-[var(--chat-assistant-bg,hsl(var(--muted)))] text-[var(--chat-assistant-fg,hsl(var(--foreground)))] rounded-bl-md",
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
            <div className="whitespace-pre-wrap break-words">{message.content}</div>
          ) : !images?.length ? (
            <span className="text-xs italic opacity-60">...</span>
          ) : null}

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

