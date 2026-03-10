"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { WrongAnswer } from "@/lib/api";

interface DiagnosticDraft {
  problemId: string;
  question: string;
  options: Record<string, string> | null;
  selectedAnswer?: string;
  diagnosis?: string;
  pending?: boolean;
}

interface WrongAnswerCardProps {
  item: WrongAnswer;
  index: number;
  draft?: DiagnosticDraft;
  markingId: string | null;
  derivingId: string | null;
  aiActionsEnabled: boolean;
  onMarkMastered: (item: WrongAnswer) => void;
  onDerive: (wrongAnswerId: string) => void;
  onDiagnosticAnswer: (wrongAnswerId: string, answer: string) => void;
}

export function WrongAnswerCard({
  item,
  index,
  draft,
  markingId,
  derivingId,
  aiActionsEnabled,
  onMarkMastered,
  onDerive,
  onDiagnosticAnswer,
}: WrongAnswerCardProps) {
  const optionKeys = Object.keys(draft?.options ?? {}).sort();

  return (
    <div className="rounded-2xl card-shadow bg-card p-4 space-y-2" data-testid={`wrong-answer-${item.id}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium">
            {index + 1}. {item.question ?? "Untitled question"}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="outline">{item.question_type ?? "unknown"}</Badge>
            {item.error_category ? <Badge variant="secondary">{item.error_category}</Badge> : null}
            {item.diagnosis ? (
              <Badge variant="secondary">{item.diagnosis.replaceAll("_", " ")}</Badge>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            size="sm"
            variant="ghost"
            aria-label="Mark as mastered"
            onClick={() => void onMarkMastered(item)}
            disabled={markingId === item.id || !item.correct_answer}
          >
            {markingId === item.id ? "..." : "\u2713"}
          </Button>
          <Button
            data-testid={`derive-${item.id}`}
            size="sm"
            variant="outline"
            aria-label="Derive diagnostic question"
            onClick={() => void onDerive(item.id)}
            disabled={!aiActionsEnabled || derivingId === item.id}
          >
            {derivingId === item.id ? "..." : "Derive"}
          </Button>
        </div>
      </div>

      {draft ? (
        <div className="rounded-xl bg-muted/30 p-3.5 space-y-2" data-testid={`diagnostic-${item.id}`}>
          <p className="text-sm font-medium">{draft.question}</p>
          {optionKeys.map((key) => (
            <button
              key={key}
              type="button"
              data-testid={`diagnostic-${item.id}-${key}`}
              className="w-full rounded-xl border px-3.5 py-2.5 text-left text-sm hover:border-primary/50"
              onClick={() => void onDiagnosticAnswer(item.id, key)}
              disabled={!aiActionsEnabled || draft.pending}
            >
              <span className="mr-2 font-medium">{key}.</span>
              {draft.options?.[key]}
            </button>
          ))}
          {draft.diagnosis ? (
            <p className="text-xs text-muted-foreground" data-testid={`diagnosis-${item.id}`}>
              {draft.diagnosis.replaceAll("_", " ")}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
