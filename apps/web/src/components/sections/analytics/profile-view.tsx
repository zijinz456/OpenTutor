"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getLearningProfile,
  dismissPreference,
  restorePreference,
  dismissMemory,
  restoreMemory,
  type LearningProfile,
  type Preference,
  type MemoryProfileItem,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

interface ProfileViewProps {
  courseId: string;
}

export function ProfileView({ courseId }: ProfileViewProps) {
  const t = useT();
  const [profile, setProfile] = useState<LearningProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [showDismissed, setShowDismissed] = useState(false);

  const fetchProfile = useCallback(async () => {
    try {
      const data = await getLearningProfile(courseId);
      setProfile(data);
    } catch {
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    void fetchProfile();
  }, [fetchProfile]);

  const handleDismissPreference = useCallback(
    async (pref: Preference) => {
      try {
        await dismissPreference(pref.id);
        toast.success(`Dismissed: ${pref.dimension}`);
        await fetchProfile();
      } catch {
        toast.error("Failed to dismiss preference");
      }
    },
    [fetchProfile],
  );

  const handleRestorePreference = useCallback(
    async (pref: Preference) => {
      try {
        await restorePreference(pref.id);
        toast.success(`Restored: ${pref.dimension}`);
        await fetchProfile();
      } catch {
        toast.error("Failed to restore preference");
      }
    },
    [fetchProfile],
  );

  const handleDismissMemory = useCallback(
    async (mem: MemoryProfileItem) => {
      try {
        await dismissMemory(mem.id);
        toast.success("Memory dismissed");
        await fetchProfile();
      } catch {
        toast.error("Failed to dismiss memory");
      }
    },
    [fetchProfile],
  );

  const handleRestoreMemory = useCallback(
    async (mem: MemoryProfileItem) => {
      try {
        await restoreMemory(mem.id);
        toast.success("Memory restored");
        await fetchProfile();
      } catch {
        toast.error("Failed to restore memory");
      }
    },
    [fetchProfile],
  );

  if (loading) {
    return (
      <div className="flex-1 p-8">
        <div className="h-4 w-40 animate-pulse rounded bg-muted" />
      </div>
    );
  }

  if (!profile || (profile.preferences.length === 0 && profile.memories.length === 0)) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <h3 className="text-sm font-medium mb-1">{t("course.profile")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          No learner profile signals yet. Keep chatting and studying to build one.
        </p>
      </div>
    );
  }

  const hasDismissed =
    profile.dismissed_preferences.length > 0 || profile.dismissed_memories.length > 0;

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {/* Active preferences */}
      <div>
        <h3 className="mb-2 text-sm font-medium">{t("course.profile")}</h3>
        <div className="flex flex-wrap gap-2">
          {profile.preferences.map((pref) => (
            <Badge
              key={pref.id}
              variant="secondary"
              className="group max-w-full gap-1 pr-1"
            >
              <span className="truncate">
                {pref.dimension}: {String(pref.value)}
              </span>
              <button
                type="button"
                className="ml-1 hidden rounded-full p-0.5 text-muted-foreground hover:bg-destructive/20 hover:text-destructive group-hover:inline-flex"
                onClick={() => void handleDismissPreference(pref)}
                title="Dismiss this preference"
              >
                ✕
              </button>
            </Badge>
          ))}
        </div>
      </div>

      {/* Active memories */}
      {profile.memories.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Memories
          </h4>
          <div className="space-y-1.5">
            {profile.memories.map((mem) => (
              <div
                key={mem.id}
                className="group flex items-start gap-2 rounded-md border px-3 py-2 text-xs"
              >
                <span className="flex-1">{mem.summary}</span>
                <button
                  type="button"
                  className="hidden shrink-0 rounded p-0.5 text-muted-foreground hover:bg-destructive/20 hover:text-destructive group-hover:inline-flex"
                  onClick={() => void handleDismissMemory(mem)}
                  title="Dismiss this memory"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      {profile.summary && (
        <div className="space-y-2">
          {profile.summary.strength_areas.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Strengths
              </h4>
              <div className="flex flex-wrap gap-1">
                {profile.summary.strength_areas.map((s) => (
                  <Badge key={s} variant="outline" className="text-xs text-green-600">
                    {s}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          {profile.summary.weak_areas.length > 0 && (
            <div>
              <h4 className="mb-1 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Areas to Improve
              </h4>
              <div className="flex flex-wrap gap-1">
                {profile.summary.weak_areas.map((w) => (
                  <Badge key={w} variant="outline" className="text-xs text-orange-600">
                    {w}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Dismissed items (toggle) */}
      {hasDismissed && (
        <div>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground"
            onClick={() => setShowDismissed((v) => !v)}
          >
            {showDismissed ? "Hide" : "Show"} dismissed ({profile.dismissed_preferences.length + profile.dismissed_memories.length})
          </Button>
          {showDismissed && (
            <div className="mt-2 space-y-2 rounded-md border border-dashed p-3">
              {profile.dismissed_preferences.map((pref) => (
                <div
                  key={pref.id}
                  className="flex items-center gap-2 text-xs text-muted-foreground"
                >
                  <span className="flex-1 line-through">
                    {pref.dimension}: {String(pref.value)}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto p-1 text-xs"
                    onClick={() => void handleRestorePreference(pref)}
                  >
                    Restore
                  </Button>
                </div>
              ))}
              {profile.dismissed_memories.map((mem) => (
                <div
                  key={mem.id}
                  className="flex items-center gap-2 text-xs text-muted-foreground"
                >
                  <span className="flex-1 line-through">{mem.summary}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-auto p-1 text-xs"
                    onClick={() => void handleRestoreMemory(mem)}
                  >
                    Restore
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
