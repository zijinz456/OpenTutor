"use client";

import { useEffect, useState } from "react";
import {
  getLearningProfile,
  type LearningProfile,
  type MemoryProfileItem,
  type Preference,
  type PreferenceSignal,
} from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { Badge } from "@/components/ui/badge";

interface ProfileViewProps {
  courseId: string;
}

function SectionList({
  title,
  items,
}: {
  title: string;
  items: string[];
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-sm font-medium mb-3">{title}</h3>
      {items.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {items.map((item) => (
            <Badge key={item} variant="outline" className="text-xs">
              {item}
            </Badge>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No signals yet.</p>
      )}
    </div>
  );
}

function PreferenceTable({ preferences }: { preferences: Preference[] }) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">Active Preferences</h3>
      </div>
      {preferences.length === 0 ? (
        <div className="px-4 py-6 text-xs text-muted-foreground">
          No saved preferences yet.
        </div>
      ) : (
        <div className="divide-y divide-border">
          {preferences.map((preference) => (
            <div key={preference.id} className="px-4 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{preference.dimension}</span>
                <Badge variant="outline">{preference.scope}</Badge>
                <Badge variant="secondary">{preference.source}</Badge>
              </div>
              <div className="mt-1 text-muted-foreground">{preference.value}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SignalList({ signals }: { signals: PreferenceSignal[] }) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">Recent Signals</h3>
      </div>
      {signals.length === 0 ? (
        <div className="px-4 py-6 text-xs text-muted-foreground">
          No recent preference signals yet.
        </div>
      ) : (
        <div className="divide-y divide-border">
          {signals.map((signal) => (
            <div key={signal.id} className="px-4 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{signal.dimension}</span>
                <Badge variant="outline">{signal.signal_type}</Badge>
              </div>
              <div className="mt-1 text-muted-foreground">{signal.value}</div>
              {signal.context?.evidence && (
                <p className="mt-2 text-xs text-muted-foreground whitespace-pre-wrap">
                  {signal.context.evidence}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MemoryList({ memories }: { memories: MemoryProfileItem[] }) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">Memories</h3>
      </div>
      {memories.length === 0 ? (
        <div className="px-4 py-6 text-xs text-muted-foreground">
          No conversation memories stored yet.
        </div>
      ) : (
        <div className="divide-y divide-border">
          {memories.map((memory) => (
            <div key={memory.id} className="px-4 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{memory.category || memory.memory_type}</span>
                <Badge variant="outline">importance {memory.importance}</Badge>
                <Badge variant="secondary">{memory.access_count} accesses</Badge>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-muted-foreground">
                {memory.summary}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ProfileView({ courseId }: ProfileViewProps) {
  const t = useT();
  const [profile, setProfile] = useState<LearningProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getLearningProfile(courseId);
        if (!cancelled) setProfile(data);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load learner profile");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="h-4 w-36 rounded bg-muted animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-sm text-muted-foreground">
        {t("general.error")}
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      <section className="grid gap-4 xl:grid-cols-2">
        <SectionList title="Strength Areas" items={profile.summary.strength_areas} />
        <SectionList title="Weak Areas" items={profile.summary.weak_areas} />
        <SectionList title="Recurring Errors" items={profile.summary.recurring_errors} />
        <SectionList title="Inferred Habits" items={profile.summary.inferred_habits} />
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <PreferenceTable preferences={profile.preferences} />
        <SignalList signals={profile.signals} />
      </div>

      <MemoryList memories={profile.memories} />
    </div>
  );
}
