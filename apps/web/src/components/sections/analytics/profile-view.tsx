"use client";

import { useEffect, useState } from "react";
import { getLearningProfile, type LearningProfile } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { Badge } from "@/components/ui/badge";

interface ProfileViewProps {
  courseId: string;
}

export function ProfileView({ courseId }: ProfileViewProps) {
  const t = useT();
  const [profile, setProfile] = useState<LearningProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const data = await getLearningProfile(courseId);
        if (!cancelled) {
          setProfile(data);
        }
      } catch {
        if (!cancelled) {
          setProfile(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (loading) {
    return (
      <div className="flex-1 p-8">
        <div className="h-4 w-40 animate-pulse rounded bg-muted" />
      </div>
    );
  }

  if (!profile || profile.preferences.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <h3 className="text-sm font-medium mb-1">{t("course.profile")}</h3>
        <p className="text-xs text-muted-foreground max-w-xs">
          No learner profile signals yet. Keep chatting and studying to build one.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <h3 className="mb-3 text-sm font-medium">{t("course.profile")}</h3>
      <div className="flex flex-wrap gap-2">
        {profile.preferences.map((preference) => (
          <Badge key={preference.id} variant="secondary" className="max-w-full">
            {preference.dimension}: {String(preference.value)}
          </Badge>
        ))}
      </div>
    </div>
  );
}
