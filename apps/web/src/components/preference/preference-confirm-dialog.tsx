"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { setPreference } from "@/lib/api";

/**
 * Preference Confirmation Dialog -- shown after a learning session.
 *
 * When the Compiler (openakita pattern) detects a preference change,
 * this dialog asks the user to confirm scope:
 * - "Long-term habit" -> scope=global
 * - "Just this course" -> scope=course
 * - "Don't change" -> dismiss
 *
 * Phase 0-C: Simple dialog.
 * Phase 1: Animated toast-style confirmation with undo.
 */

interface PreferenceChange {
  dimension: string;
  value: string;
  oldValue?: string;
}

interface PreferenceConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  changes: PreferenceChange[];
  courseId?: string;
}

const DIMENSION_LABELS: Record<string, string> = {
  note_format: "Note Format",
  detail_level: "Detail Level",
  language: "Language",
  explanation_style: "Explanation Style",
  visual_preference: "Visual Preference",
  layout_preset: "Layout Preset",
};

const VALUE_LABELS: Record<string, string> = {
  bullet_point: "Bullet Points",
  table: "Table",
  mind_map: "Mind Map",
  step_by_step: "Step by Step",
  summary: "Summary",
  concise: "Concise",
  balanced: "Balanced",
  detailed: "Detailed",
  formal: "Formal",
  conversational: "Conversational",
  socratic: "Socratic",
  example_heavy: "Example Heavy",
};

export function PreferenceConfirmDialog({
  open,
  onOpenChange,
  changes,
  courseId,
}: PreferenceConfirmDialogProps) {
  const [saving, setSaving] = useState(false);

  const handleConfirm = async (scope: "global" | "course") => {
    setSaving(true);
    try {
      for (const change of changes) {
        await setPreference(
          change.dimension,
          change.value,
          scope,
          scope === "course" ? courseId : undefined,
          "behavior"
        );
      }
    } finally {
      setSaving(false);
      onOpenChange(false);
    }
  };

  if (changes.length === 0) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Preference Update Detected</DialogTitle>
          <DialogDescription>
            Based on your learning session, we noticed some preference changes.
            How would you like to apply them?
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-4">
          {changes.map((change, i) => (
            <div
              key={i}
              className="flex items-center justify-between p-3 rounded-lg bg-muted"
            >
              <div>
                <p className="text-sm font-medium">
                  {DIMENSION_LABELS[change.dimension] || change.dimension}
                </p>
                <p className="text-xs text-muted-foreground">
                  {change.oldValue && (
                    <span>
                      {VALUE_LABELS[change.oldValue] || change.oldValue} {"\u2192"}{" "}
                    </span>
                  )}
                  <span className="font-medium text-foreground">
                    {VALUE_LABELS[change.value] || change.value}
                  </span>
                </p>
              </div>
              <span className="text-green-500" aria-hidden="true">{"\u2713"}</span>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-2">
          <Button
            onClick={() => handleConfirm("global")}
            disabled={saving}
            className="w-full"
          >
            Apply as Long-term Habit
          </Button>
          {courseId && (
            <Button
              variant="outline"
              onClick={() => handleConfirm("course")}
              disabled={saving}
              className="w-full"
            >
              Just for This Course
            </Button>
          )}
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={saving}
            className="w-full"
          >
            <span className="mr-1">x</span>
            Don&apos;t Change
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
