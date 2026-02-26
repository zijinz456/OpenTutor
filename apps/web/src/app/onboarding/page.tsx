"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ArrowRight, ArrowLeft, Brain, Image as ImageIcon } from "lucide-react";
import { setPreference } from "@/lib/api";
import { toast } from "sonner";

const STEPS = [
  {
    title: "What language do you prefer?",
    subtitle: "Choose the primary language for Agent's responses and generated notes.",
    dimension: "language",
    options: [
      { value: "en", label: "English", description: "All content in English" },
      { value: "zh", label: "\u4e2d\u6587 (Chinese)", description: "\u4f7f\u7528\u4e2d\u6587\u56de\u7b54\u548c\u751f\u6210\u7b14\u8bb0" },
      { value: "auto", label: "Bilingual / Mixed", description: "Use the same language as the source material" },
    ],
  },
  {
    title: "How do you prefer to learn?",
    subtitle: "Choose a learning style that suits you best. This helps Agent adapt its teaching approach.",
    dimension: "learning_mode",
    options: [
      { value: "concept_first", label: "Concept First", description: "Understand theory before practice. Best for building deep understanding." },
      { value: "practice_first", label: "Practice First", description: "Jump into exercises, learn by doing. Review theory as needed." },
      { value: "balanced", label: "Balanced Mix", description: "Alternate between concepts and practice for a well-rounded experience." },
    ],
  },
  {
    title: "How detailed should notes be?",
    subtitle: "Choose the level of detail for generated notes and explanations.",
    dimension: "detail_level",
    options: [
      { value: "concise", label: "Concise", description: "Key points only. Bullet points and short summaries." },
      { value: "balanced", label: "Moderate", description: "Balanced depth with explanations where needed." },
      { value: "detailed", label: "Detailed", description: "In-depth explanations with examples and analogies." },
    ],
  },
  {
    title: "Choose your workspace layout",
    subtitle: "Pick a default layout for your learning workspace. You can change this anytime.",
    dimension: "layout_preset",
    type: "layout" as const,
    options: [
      { value: "balanced", label: "Split + Chat", description: "PDF & Notes side by side with chat panel" },
      { value: "notesFocused", label: "Focus Mode", description: "Full-width single panel, distraction-free" },
      { value: "chatFocused", label: "Triple Panel", description: "PDF, Notes, and Chat all visible" },
    ],
  },
  {
    title: "Got a note style you love?",
    subtitle: "Upload or paste an example of notes you like. Agent will learn your formatting preferences. You can skip this step.",
    dimension: "example_style",
    type: "upload" as const,
    options: [],
  },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [exampleText, setExampleText] = useState("");
  const [saving, setSaving] = useState(false);

  const step = STEPS[currentStep];

  const handleSelect = (value: string) => {
    setSelections((s) => ({ ...s, [step.dimension]: value }));
  };

  const handleNext = () => {
    if (currentStep < STEPS.length - 1) {
      setCurrentStep((s) => s + 1);
    } else {
      handleFinish();
    }
  };

  const handleBack = () => {
    if (currentStep > 0) setCurrentStep((s) => s - 1);
  };

  const handleFinish = async () => {
    setSaving(true);
    try {
      for (const [dimension, value] of Object.entries(selections)) {
        await setPreference(dimension, value, "global", undefined, "onboarding");
      }
      localStorage.setItem("opentutor_onboarded", "true");
      toast.success("Preferences saved! Your experience is now personalized.");
      router.push("/");
    } catch {
      toast.error("Failed to save preferences");
    } finally {
      setSaving(false);
    }
  };

  const selected = selections[step.dimension];

  return (
    <div className="h-screen flex bg-[#1E1B4B]">
      {/* Left Sidebar */}
      <aside className="w-[280px] p-6 flex flex-col gap-5 shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 bg-indigo-600 rounded-md flex items-center justify-center">
            <Brain className="w-[18px] h-[18px] text-white" />
          </div>
          <span className="text-white font-bold text-lg" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
            OpenTutor
          </span>
        </div>

        <nav className="flex flex-col gap-1">
          {STEPS.map((s, idx) => {
            const isDone = idx < currentStep;
            const isCurrent = idx === currentStep;
            const canClick = idx <= currentStep;

            return (
              <button
                key={idx}
                onClick={() => canClick && setCurrentStep(idx)}
                className={`flex items-center gap-2.5 h-10 px-3 rounded-md transition-colors ${
                  isCurrent ? "bg-white/15" : isDone ? "bg-white/10" : ""
                } ${canClick ? "cursor-pointer" : "cursor-default"}`}
              >
                <div
                  className={`w-[22px] h-[22px] rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${
                    isDone
                      ? "bg-green-500"
                      : isCurrent
                      ? "bg-white text-[#1E1B4B]"
                      : "border border-[#6B6990] text-[#8886A8]"
                  }`}
                >
                  {isDone ? <Check className="w-3 h-3 text-white" /> : idx + 1}
                </div>
                <span
                  className={`text-[13px] ${
                    isDone
                      ? "text-[#A5A3C2] font-medium"
                      : isCurrent
                      ? "text-white font-semibold"
                      : "text-[#8886A8]"
                  }`}
                >
                  {s.dimension === "language" && "Language"}
                  {s.dimension === "learning_mode" && "Learning Mode"}
                  {s.dimension === "detail_level" && "Output Format"}
                  {s.dimension === "layout_preset" && "Layout Template"}
                  {s.dimension === "example_style" && "I Have Examples"}
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1 bg-white rounded-tl-xl p-16 flex flex-col justify-center gap-8 overflow-y-auto">
        <div className="max-w-[560px] flex flex-col gap-8 animate-in fade-in slide-in-from-bottom-3 duration-300" key={currentStep}>
          <div>
            <h1 className="text-[28px] font-bold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              {step.title}
            </h1>
            <p className="text-[15px] text-gray-500 mt-2 max-w-[500px]">{step.subtitle}</p>
          </div>

          {/* Option Cards (for steps 1-4) */}
          {step.type !== "upload" && step.type !== "layout" && (
            <div className="flex flex-col gap-3">
              {step.options.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => handleSelect(opt.value)}
                  className={`flex items-center gap-3 p-4 px-5 rounded-[10px] text-left transition-all ${
                    selected === opt.value
                      ? "border-2 border-indigo-600"
                      : "border border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div
                    className={`w-5 h-5 rounded-full shrink-0 flex items-center justify-center ${
                      selected === opt.value ? "bg-indigo-600" : "border-2 border-gray-200"
                    }`}
                  >
                    {selected === opt.value && <div className="w-2 h-2 rounded-full bg-white" />}
                  </div>
                  <div className="flex flex-col gap-1 flex-1">
                    <span className="font-semibold text-[15px] text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                      {opt.label}
                    </span>
                    <span className="text-[13px] text-gray-500">{opt.description}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* Layout Cards (step 4) */}
          {step.type === "layout" && (
            <div className="flex gap-4">
              {step.options.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => handleSelect(opt.value)}
                  className={`flex-1 p-5 rounded-[10px] flex flex-col gap-3 text-left transition-all ${
                    selected === opt.value
                      ? "border-2 border-indigo-600"
                      : "border border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="w-full h-20 bg-white border border-gray-200 rounded-md flex overflow-hidden">
                    {opt.value === "balanced" && (
                      <>
                        <div className="w-[10%] bg-[#1E1B4B]" />
                        <div className="flex-1 border-r border-gray-200" />
                        <div className="w-[35%]" />
                      </>
                    )}
                    {opt.value === "notesFocused" && (
                      <>
                        <div className="w-[10%] bg-[#1E1B4B]" />
                        <div className="flex-1" />
                      </>
                    )}
                    {opt.value === "chatFocused" && (
                      <>
                        <div className="w-[10%] bg-[#1E1B4B]" />
                        <div className="flex-1 border-r border-gray-200" />
                        <div className="flex-1 border-r border-gray-200" />
                        <div className="flex-1" />
                      </>
                    )}
                  </div>
                  <span className="font-semibold text-sm text-gray-900 text-center w-full" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                    {opt.label}
                  </span>
                  <span className="text-xs text-gray-400 text-center w-full">{opt.description}</span>
                </button>
              ))}
            </div>
          )}

          {/* Upload/Example (step 5) */}
          {step.type === "upload" && (
            <div className="flex flex-col gap-4">
              <div className="w-full min-h-[140px] border-2 border-dashed border-gray-200 rounded-[10px] bg-gray-50 flex flex-col items-center justify-center gap-2.5 cursor-pointer hover:border-indigo-600 hover:bg-indigo-50 transition-colors">
                <ImageIcon className="w-8 h-8 text-gray-400" />
                <span className="text-sm text-gray-500">Drop a screenshot or image of notes you like</span>
                <span className="text-xs text-gray-400">PNG, JPG, or PDF</span>
              </div>
              <span className="text-[13px] text-gray-400 text-center">&mdash; or paste text below &mdash;</span>
              <textarea
                className="w-full h-[100px] p-3 border border-gray-200 rounded-lg bg-white resize-none text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
                placeholder="Paste an example of notes or formatting you prefer..."
                value={exampleText}
                onChange={(e) => setExampleText(e.target.value)}
              />
            </div>
          )}

          {/* Navigation Buttons */}
          <div className="flex justify-between">
            {currentStep > 0 ? (
              <button
                onClick={handleBack}
                className="h-11 px-6 border border-gray-200 rounded-lg flex items-center gap-1.5 text-gray-500 font-medium text-sm hover:border-gray-300 transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Back
              </button>
            ) : (
              <div />
            )}
            <div className="flex gap-3">
              {step.type === "upload" && (
                <button
                  onClick={() => { localStorage.setItem("opentutor_onboarded", "true"); router.push("/"); }}
                  className="h-11 px-6 border border-gray-200 rounded-lg text-gray-500 font-medium text-sm hover:border-gray-300 transition-colors"
                >
                  Skip
                </button>
              )}
              <button
                onClick={handleNext}
                disabled={step.type !== "upload" && !selected}
                className="h-11 px-7 bg-indigo-600 text-white rounded-lg flex items-center gap-2 font-semibold text-sm hover:bg-indigo-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {currentStep === STEPS.length - 1
                  ? saving
                    ? "Saving..."
                    : "Finish Setup"
                  : "Continue"}
                {currentStep === STEPS.length - 1 ? (
                  <Check className="w-3.5 h-3.5" />
                ) : (
                  <ArrowRight className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
