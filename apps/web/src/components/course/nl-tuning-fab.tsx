"use client";

import { useState, useRef, useEffect } from "react";
import { Wand2, X, HelpCircle } from "lucide-react";
import { setPreference } from "@/lib/api";
import { toast } from "sonner";

interface NLTuningFABProps {
  courseId: string;
}

const CLARIFY_OPTIONS = [
  { label: "Notes panel: change formatting style", dimension: "note_format" },
  { label: "AI responses: adjust tone and detail", dimension: "explanation_style" },
  { label: "Layout: rearrange workspace panels", dimension: "layout_preset" },
];

export function NLTuningFAB({ courseId }: NLTuningFABProps) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [showClarify, setShowClarify] = useState(false);
  const [lastInput, setLastInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  const handleSubmit = () => {
    if (!input.trim()) return;
    setLastInput(input.trim());
    setInput("");
    setShowClarify(true);
  };

  const handleClarify = async (option: typeof CLARIFY_OPTIONS[number]) => {
    try {
      await setPreference(option.dimension, lastInput, "course", courseId, "nl_tuning");
      toast.success(`Applied: ${option.label}`);
    } catch {
      toast.error("Failed to apply preference");
    }
    setShowClarify(false);
    setOpen(false);
  };

  return (
    <>
      {/* FAB Button */}
      <button
        onClick={() => setOpen(!open)}
        className="absolute bottom-[52px] right-6 w-12 h-12 bg-indigo-600 rounded-full flex items-center justify-center text-white shadow-lg shadow-indigo-600/30 hover:scale-[1.08] hover:shadow-xl hover:shadow-indigo-600/40 transition-all z-10"
        title="Fine-tune Agent"
      >
        <Wand2 className="w-[22px] h-[22px]" />
      </button>

      {/* Popup */}
      {open && (
        <div className="absolute bottom-[108px] right-6 w-[380px] bg-white border border-gray-200 rounded-xl shadow-xl z-10 flex flex-col overflow-hidden animate-in fade-in slide-in-from-bottom-3 duration-200">
          {/* Header */}
          <div className="px-4 py-3.5 bg-gray-50 border-b flex items-center gap-2">
            <Wand2 className="w-4 h-4 text-indigo-600" />
            <span className="font-semibold text-[13px] text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              Fine-tune Agent
            </span>
            <div className="flex-1" />
            <button onClick={() => { setOpen(false); setShowClarify(false); }} className="text-gray-400 hover:text-gray-900">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Body */}
          <div className="p-4 flex flex-col gap-3">
            {!showClarify ? (
              <>
                <input
                  ref={inputRef}
                  className="w-full h-10 px-4 border border-gray-200 rounded-lg bg-white text-[13px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
                  placeholder='e.g. "simplify notes", "change format"...'
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                />
                <span className="text-[11px] text-gray-400">
                  Type a request to adjust layout, note format, or AI style
                </span>
              </>
            ) : (
              <>
                <div className="flex items-center gap-1.5 mb-1">
                  <HelpCircle className="w-3.5 h-3.5 text-indigo-600" />
                  <span className="text-[13px] font-semibold text-gray-900">What do you mean?</span>
                </div>
                <span className="text-xs text-gray-500 mb-1">
                  Your request &ldquo;{lastInput}&rdquo; could mean:
                </span>
                {CLARIFY_OPTIONS.map((opt) => (
                  <button
                    key={opt.dimension}
                    onClick={() => handleClarify(opt)}
                    className="flex items-center gap-2 p-2.5 px-3.5 border border-gray-200 rounded-lg text-[13px] text-gray-900 hover:border-indigo-600 hover:bg-indigo-50 transition-colors text-left"
                  >
                    <div className="w-2 h-2 rounded-full border-2 border-gray-200 shrink-0 group-hover:border-indigo-600 group-hover:bg-indigo-600" />
                    {opt.label}
                  </button>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
