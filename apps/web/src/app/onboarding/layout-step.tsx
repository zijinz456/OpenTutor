import type { OnboardingOption } from "./types";

interface LayoutStepProps {
  options: OnboardingOption[];
  selected: string | undefined;
  onSelect: (value: string) => void;
}

function LayoutPreview({ value }: { value: string }) {
  if (value === "balanced") {
    return (
      <>
        <div className="w-[10%] bg-sidebar" />
        <div className="flex-1 border-r border-border" />
        <div className="w-[35%]" />
      </>
    );
  }

  if (value === "notesFocused") {
    return (
      <>
        <div className="w-[10%] bg-sidebar" />
        <div className="flex-1" />
      </>
    );
  }

  // chatFocused
  return (
    <>
      <div className="w-[10%] bg-sidebar" />
      <div className="flex-1 border-r border-border" />
      <div className="flex-1 border-r border-border" />
      <div className="flex-1" />
    </>
  );
}

export function LayoutStep({ options, selected, onSelect }: LayoutStepProps) {
  return (
    <div className="flex gap-4">
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          onClick={() => onSelect(option.value)}
          className={`flex-1 p-5 rounded-[10px] flex flex-col gap-3 text-left transition-all ${
            selected === option.value
              ? "border-2 border-brand"
              : "border border-border hover:border-muted-foreground/30"
          }`}
        >
          <div className="w-full h-20 bg-background border border-border rounded-md flex overflow-hidden">
            <LayoutPreview value={option.value} />
          </div>
          <span className="font-semibold text-sm text-foreground text-center w-full">
            {option.label}
          </span>
          <span className="text-xs text-muted-foreground text-center w-full">{option.description}</span>
        </button>
      ))}
    </div>
  );
}
