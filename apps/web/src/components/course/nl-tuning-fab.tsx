"use client";

import { useState, useRef, useEffect } from "react";
import { parseNLPreference, setPreference } from "@/lib/api";
import { toast } from "sonner";

interface NLTuningFABProps {
  courseId: string;
}

interface SubOption {
  value: string;
  label: string;
}

interface ClarifyOption {
  label: string;
  dimension: string;
  subOptions: SubOption[];
}

const CLARIFY_OPTIONS: ClarifyOption[] = [
  {
    label: "Notes panel: change formatting style",
    dimension: "note_format",
    subOptions: [
      { value: "bullet_point", label: "Bullet Points" },
      { value: "table", label: "Table" },
      { value: "mind_map", label: "Mind Map" },
      { value: "step_by_step", label: "Step-by-Step" },
      { value: "summary", label: "Summary" },
    ],
  },
  {
    label: "AI responses: adjust detail level",
    dimension: "detail_level",
    subOptions: [
      { value: "concise", label: "Concise" },
      { value: "balanced", label: "Balanced" },
      { value: "detailed", label: "Detailed" },
    ],
  },
  {
    label: "AI responses: adjust tone and style",
    dimension: "explanation_style",
    subOptions: [
      { value: "formal", label: "Formal" },
      { value: "conversational", label: "Conversational" },
      { value: "socratic", label: "Socratic" },
      { value: "example_heavy", label: "Example-Heavy" },
    ],
  },
];

type ViewState = "input" | "parsing" | "clarify" | "sub_options";

export function NLTuningFAB({ courseId }: NLTuningFABProps) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [view, setView] = useState<ViewState>("input");
  const [lastInput, setLastInput] = useState("");
  const [selectedDimension, setSelectedDimension] = useState<ClarifyOption | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  const handleClose = () => {
    setOpen(false);
    setView("input");
    setSelectedDimension(null);
  };

  const handleSubmit = async () => {
    if (!input.trim()) return;
    const text = input.trim();
    setLastInput(text);
    setInput("");
    setView("parsing");

    try {
      const result = await parseNLPreference(text);
      if (result.dimension && result.value) {
        await setPreference(result.dimension, result.value, "course", courseId, "nl_tuning");
        toast.success(`Applied: ${result.label ?? `${result.dimension} → ${result.value}`}`);
        handleClose();
        return;
      }
    } catch {
      // LLM unavailable — fall through to manual clarification
    }

    setView("clarify");
  };

  const handleClarifySelect = (option: ClarifyOption) => {
    setSelectedDimension(option);
    setView("sub_options");
  };

  const handleSubOptionSelect = async (subOption: SubOption) => {
    if (!selectedDimension) return;
    try {
      await setPreference(selectedDimension.dimension, subOption.value, "course", courseId, "nl_tuning");
      toast.success(`Set ${selectedDimension.dimension} to "${subOption.label}"`);
    } catch {
      toast.error("Failed to apply preference");
    }
    handleClose();
  };

  const handleBackToClarify = () => {
    setSelectedDimension(null);
    setView("clarify");
  };

  return (
    <>
      {/* FAB Button */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="absolute bottom-[112px] right-6 w-12 h-12 bg-brand rounded-full flex items-center justify-center text-brand-foreground shadow-lg hover:scale-[1.08] hover:shadow-xl transition-all z-10 text-xs font-bold"
        title="Fine-tune Agent"
      >
        Tune
      </button>

      {/* Popup */}
      {open && (
        <div className="absolute bottom-[168px] right-6 w-[380px] bg-card border border-border rounded-xl shadow-xl z-10 flex flex-col overflow-hidden animate-in fade-in slide-in-from-bottom-3 duration-200">
          {/* Header */}
          <div className="px-4 py-3.5 bg-muted border-b border-border flex items-center gap-2">
            <span className="font-semibold text-[13px] text-foreground">
              Fine-tune Agent
            </span>
            <div className="flex-1" />
            <button type="button" onClick={handleClose} className="text-muted-foreground hover:text-foreground text-xs">
              x
            </button>
          </div>

          {/* Body */}
          <div className="p-4 flex flex-col gap-3">
            {view === "input" && (
              <>
                <input
                  ref={inputRef}
                  className="w-full h-10 px-4 border border-border rounded-lg bg-background text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand"
                  placeholder='e.g. "simplify notes", "use more examples"...'
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void handleSubmit()}
                />
                <span className="text-[11px] text-muted-foreground">
                  Describe what you want to change -- AI will parse your intent
                </span>
              </>
            )}

            {view === "parsing" && (
              <div className="flex items-center justify-center gap-2 py-4">
                <span className="text-[13px] text-muted-foreground animate-pulse">Understanding your request...</span>
              </div>
            )}

            {view === "clarify" && (
              <>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-[13px] font-semibold text-foreground">What would you like to adjust?</span>
                </div>
                <span className="text-xs text-muted-foreground mb-1">
                  Your request &ldquo;{lastInput}&rdquo; could apply to:
                </span>
                {CLARIFY_OPTIONS.map((opt) => (
                  <button
                    type="button"
                    key={opt.dimension}
                    onClick={() => handleClarifySelect(opt)}
                    className="flex items-center gap-2 p-2.5 px-3.5 border border-border rounded-lg text-[13px] text-foreground hover:border-brand hover:bg-brand-muted transition-colors text-left"
                  >
                    <div className="w-2 h-2 rounded-full border-2 border-border shrink-0" />
                    {opt.label}
                  </button>
                ))}
              </>
            )}

            {view === "sub_options" && selectedDimension && (
              <>
                <button
                  type="button"
                  onClick={handleBackToClarify}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors self-start mb-1"
                >
                  &larr; Back
                </button>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-[13px] font-semibold text-foreground">
                    Choose a value for {selectedDimension.dimension.replace(/_/g, " ")}
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {selectedDimension.subOptions.map((sub) => (
                    <button
                      type="button"
                      key={sub.value}
                      onClick={() => handleSubOptionSelect(sub)}
                      className="px-3.5 py-2 border border-border rounded-lg text-[13px] text-foreground hover:border-brand hover:bg-brand-muted transition-colors"
                    >
                      {sub.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
