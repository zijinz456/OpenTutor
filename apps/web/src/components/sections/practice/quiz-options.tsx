"use client";

import { useT } from "@/lib/i18n-context";

export function parseChoiceAnswer(answer: string | null | undefined): string[] {
  return answer ? answer.split(/[,/;|]/).map((key) => key.trim().toLowerCase()).filter(Boolean) : [];
}

interface QuizOptionsProps {
  optionKeys: string[];
  options: Record<string, string>;
  selectedOption: string | null;
  multiple?: boolean;
  selectedOptions?: string[];
  disabled?: boolean;
  result: { correct_answer?: string | null; is_correct: boolean } | null;
  submitting: boolean;
  onOptionClick: (key: string) => void;
}

export function QuizOptions({
  optionKeys,
  options,
  selectedOption,
  multiple = false,
  selectedOptions = [],
  disabled = false,
  result,
  submitting,
  onOptionClick,
}: QuizOptionsProps) {
  const t = useT();
  const selected = multiple ? selectedOptions.map((key) => key.toLowerCase()) : [selectedOption];
  const isSelected = (key: string) => selected.includes(multiple ? key.toLowerCase() : key);
  const correct = multiple ? parseChoiceAnswer(result?.correct_answer) : [result?.correct_answer];
  const locked = disabled || !!result || submitting;
  const optionStyle = (key: string) => {
    if (!result) {
      return isSelected(key)
        ? "border-primary bg-primary/10"
        : "border-border hover:border-primary/50";
    }
    if (correct.includes(multiple ? key.toLowerCase() : key)) return "border-green-500 bg-green-500/10";
    if (isSelected(key) && !result.is_correct) {
      return "border-destructive bg-destructive/10";
    }
    return "border-border opacity-60";
  };

  return (
    <div className="space-y-3" role={multiple ? "group" : "radiogroup"} aria-label={t("quiz.answerOptions")} aria-describedby="quiz-question-text">
      {optionKeys.map((key) => (
        <button
          key={key}
          type="button"
          role={multiple ? "checkbox" : "radio"}
          aria-checked={isSelected(key)}
          data-testid={`quiz-option-${key}`}
          disabled={locked}
          onClick={() => void onOptionClick(key)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              if (!locked) void onOptionClick(key);
            }
            if (e.key === "ArrowDown" || e.key === "ArrowRight") {
              e.preventDefault();
              const idx = optionKeys.indexOf(key);
              const next = optionKeys[(idx + 1) % optionKeys.length];
              const nextEl = document.querySelector(`[data-testid="quiz-option-${next}"]`) as HTMLElement;
              nextEl?.focus();
            }
            if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
              e.preventDefault();
              const idx = optionKeys.indexOf(key);
              const prev = optionKeys[(idx - 1 + optionKeys.length) % optionKeys.length];
              const prevEl = document.querySelector(`[data-testid="quiz-option-${prev}"]`) as HTMLElement;
              prevEl?.focus();
            }
          }}
          className={`w-full text-left rounded-xl border px-3.5 py-3 text-sm min-h-[44px] transition-colors ${optionStyle(key)} disabled:cursor-default`}
        >
          <span className="font-medium mr-2">{key.toUpperCase()}.</span>
          {options[key]}
        </button>
      ))}
    </div>
  );
}
