"use client";

import { useT } from "@/lib/i18n-context";

interface QuizOptionsProps {
  optionKeys: string[];
  options: Record<string, string>;
  selectedOption: string | null;
  result: { correct_answer?: string | null; is_correct: boolean } | null;
  submitting: boolean;
  onOptionClick: (key: string) => void;
}

export function QuizOptions({
  optionKeys,
  options,
  selectedOption,
  result,
  submitting,
  onOptionClick,
}: QuizOptionsProps) {
  const t = useT();
  const optionStyle = (key: string) => {
    if (!result) {
      return key === selectedOption
        ? "border-primary bg-primary/10"
        : "border-border hover:border-primary/50";
    }
    if (key === result.correct_answer) return "border-green-500 bg-green-500/10";
    if (key === selectedOption && !result.is_correct) {
      return "border-destructive bg-destructive/10";
    }
    return "border-border opacity-60";
  };

  return (
    <div className="space-y-3" role="radiogroup" aria-label={t("quiz.answerOptions")} aria-describedby="quiz-question-text">
      {optionKeys.map((key) => (
        <button
          key={key}
          role="radio"
          aria-checked={selectedOption === key}
          data-testid={`quiz-option-${key}`}
          disabled={!!result || submitting}
          onClick={() => void onOptionClick(key)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              if (!result && !submitting) void onOptionClick(key);
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
