"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { setPreference } from "@/lib/api";
import { toast } from "sonner";

/**
 * Preference Onboarding Wizard — 5 steps.
 *
 * Step 1: Note format preference
 * Step 2: Detail level
 * Step 3: Language
 * Step 4: Layout template
 * Step 5: Optional examples / skip
 *
 * Reference: react-step-wizard pattern, Spotify onboarding card grid.
 * Reference: spaceforge settings pattern.
 */

interface OnboardingWizardProps {
  open: boolean;
  onComplete: () => void;
}

interface StepOption {
  value: string;
  label: string;
  description: string;
}

const STEPS = [
  {
    title: "How do you prefer your notes?",
    dimension: "note_format",
    options: [
      { value: "bullet_point", label: "Bullet Points", description: "Hierarchical bullet points with key terms bolded" },
      { value: "table", label: "Tables", description: "Structured comparisons and organized data" },
      { value: "mind_map", label: "Mind Maps", description: "Visual diagrams showing concept relationships" },
      { value: "step_by_step", label: "Step by Step", description: "Numbered processes with flowcharts" },
      { value: "summary", label: "Concise Summary", description: "Brief overview with key takeaways" },
    ] as StepOption[],
  },
  {
    title: "How detailed should explanations be?",
    dimension: "detail_level",
    options: [
      { value: "concise", label: "Concise", description: "Just the essentials, no fluff" },
      { value: "balanced", label: "Balanced", description: "Balanced detail with examples" },
      { value: "detailed", label: "Detailed", description: "Thorough explanations with examples and context" },
    ] as StepOption[],
  },
  {
    title: "What language do you prefer?",
    dimension: "language",
    options: [
      { value: "en", label: "English", description: "Responses in English" },
      { value: "zh", label: "Chinese", description: "Responses in Chinese" },
      { value: "auto", label: "Match Input", description: "Reply in the same language you use" },
    ] as StepOption[],
  },
  {
    title: "Choose your default layout",
    dimension: "layout_preset",
    options: [
      { value: "balanced", label: "Balanced", description: "Equal space for notes, quiz, and chat" },
      { value: "notesFocused", label: "Notes First", description: "Larger notes panel for reading" },
      { value: "chatFocused", label: "Chat First", description: "Larger chat panel for Q&A" },
    ] as StepOption[],
  },
  {
    title: "How should AI explain things?",
    dimension: "explanation_style",
    options: [
      { value: "step_by_step", label: "Step by Step", description: "Walk through each step logically" },
      { value: "example_heavy", label: "Example Heavy", description: "Use many concrete examples" },
      { value: "socratic", label: "Socratic", description: "Guide with questions and prompts" },
      { value: "formal", label: "Formal/Academic", description: "Precise academic language" },
    ] as StepOption[],
  },
];

export function OnboardingWizard({ open, onComplete }: OnboardingWizardProps) {
  const [step, setStep] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const currentStep = STEPS[step];

  const handleSelect = (value: string) => {
    setSelections((s) => ({ ...s, [currentStep.dimension]: value }));
  };

  const handleNext = async () => {
    if (step < STEPS.length - 1) {
      setStep((s) => s + 1);
    } else {
      // Save all preferences
      setSaving(true);
      try {
        for (const [dimension, value] of Object.entries(selections)) {
          await setPreference(dimension, value, "global", undefined, "onboarding");
        }
        toast.success("Preferences saved! Your experience is now personalized.");
        onComplete();
      } catch {
        toast.error("Failed to save preferences");
      } finally {
        setSaving(false);
      }
    }
  };

  const handleSkip = () => {
    onComplete();
  };

  const selected = selections[currentStep.dimension];

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent className="max-w-lg" onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle className="text-base">
            <span className="text-muted-foreground text-sm mr-2">
              Step {step + 1}/{STEPS.length}
            </span>
            {currentStep.title}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-2 py-2">
          {currentStep.options.map((option) => (
            <Card
              key={option.value}
              className={`cursor-pointer transition-all ${
                selected === option.value
                  ? "border-primary ring-1 ring-primary"
                  : "hover:border-primary/50"
              }`}
              onClick={() => handleSelect(option.value)}
            >
              <CardContent className="py-3 px-4">
                <div className="font-medium text-sm">{option.label}</div>
                <div className="text-xs text-muted-foreground">{option.description}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="flex justify-between pt-2">
          <Button variant="ghost" size="sm" onClick={handleSkip}>
            Skip for now
          </Button>
          <div className="flex gap-2">
            {step > 0 && (
              <Button variant="outline" size="sm" onClick={() => setStep((s) => s - 1)}>
                Back
              </Button>
            )}
            <Button size="sm" onClick={handleNext} disabled={!selected || saving}>
              {step === STEPS.length - 1 ? (saving ? "Saving..." : "Finish") : "Next"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
