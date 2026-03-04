import type { OnboardingOption } from "./types";

interface OptionStepProps {
  options: OnboardingOption[];
  selected: string | undefined;
  onSelect: (value: string) => void;
}

export function OptionStep({ options, selected, onSelect }: OptionStepProps) {
  return (
    <div className="flex flex-col gap-3">
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          onClick={() => onSelect(option.value)}
          className={`flex items-center gap-3 p-4 px-5 rounded-[10px] text-left transition-all ${
            selected === option.value
              ? "border-2 border-brand"
              : "border border-border hover:border-muted-foreground/30"
          }`}
        >
          <div
            className={`w-5 h-5 rounded-full shrink-0 flex items-center justify-center ${
              selected === option.value ? "bg-brand" : "border-2 border-border"
            }`}
          >
            {selected === option.value && <div className="w-2 h-2 rounded-full bg-brand-foreground" />}
          </div>
          <div className="flex flex-col gap-1 flex-1">
            <span className="font-semibold text-[15px] text-foreground">
              {option.label}
            </span>
            <span className="text-[13px] text-muted-foreground">{option.description}</span>
          </div>
        </button>
      ))}
    </div>
  );
}
