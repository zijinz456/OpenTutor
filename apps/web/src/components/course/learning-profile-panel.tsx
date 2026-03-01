"use client";

import { useCallback, useEffect, useState } from "react";
import { BrainCircuit, Pencil, RotateCcw, ShieldBan, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  dismissMemoryItem,
  dismissPreferenceItem,
  dismissPreferenceSignal,
  getLearningProfile,
  restoreMemoryItem,
  restorePreferenceItem,
  restorePreferenceSignal,
  type LearningProfile,
  type MemoryProfileItem,
  type Preference,
  type PreferenceSignal,
  updateMemoryItem,
  updatePreferenceItem,
} from "@/lib/api";

interface LearningProfilePanelProps {
  courseId: string;
}

function formatTime(value?: string | null) {
  if (!value) return "Unknown";
  return new Date(value).toLocaleString();
}

function formatLabel(value: string | null | undefined) {
  if (!value) return "unknown";
  return value.replaceAll("_", " ");
}

function SummaryList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
      <div className="mt-2 space-y-1.5">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing surfaced yet.</p>
        ) : (
          items.map((item, index) => (
            <p key={`${title}-${index}`} className="text-sm text-foreground/90">
              {item}
            </p>
          ))
        )}
      </div>
    </div>
  );
}

export function LearningProfilePanel({ courseId }: LearningProfilePanelProps) {
  const [profile, setProfile] = useState<LearningProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [editingPreferenceId, setEditingPreferenceId] = useState<string | null>(null);
  const [editingPreferenceValue, setEditingPreferenceValue] = useState("");
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editingMemorySummary, setEditingMemorySummary] = useState("");
  const [editingMemoryCategory, setEditingMemoryCategory] = useState("");

  const loadProfile = useCallback(async () => {
    setLoading(true);
    try {
      setProfile(await getLearningProfile(courseId));
    } catch (error) {
      toast.error((error as Error).message || "Failed to load learning profile");
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  const dismissWithReason = async (
    key: string,
    action: (reason?: string) => Promise<unknown>,
    successMessage: string,
  ) => {
    const reason = window.prompt("Dismiss reason (optional)")?.trim() || undefined;
    setBusyKey(key);
    try {
      await action(reason);
      toast.success(successMessage);
      await loadProfile();
    } catch (error) {
      toast.error((error as Error).message || "Update failed");
    } finally {
      setBusyKey(null);
    }
  };

  const restoreItem = async (key: string, action: () => Promise<unknown>, successMessage: string) => {
    setBusyKey(key);
    try {
      await action();
      toast.success(successMessage);
      await loadProfile();
    } catch (error) {
      toast.error((error as Error).message || "Restore failed");
    } finally {
      setBusyKey(null);
    }
  };

  const savePreference = async (preference: Preference) => {
    setBusyKey(`pref-save:${preference.id}`);
    try {
      await updatePreferenceItem(preference.id, { value: editingPreferenceValue.trim() });
      setEditingPreferenceId(null);
      setEditingPreferenceValue("");
      toast.success("Preference updated");
      await loadProfile();
    } catch (error) {
      toast.error((error as Error).message || "Failed to update preference");
    } finally {
      setBusyKey(null);
    }
  };

  const saveMemory = async (memory: MemoryProfileItem) => {
    setBusyKey(`memory-save:${memory.id}`);
    try {
      await updateMemoryItem(memory.id, {
        summary: editingMemorySummary.trim(),
        category: editingMemoryCategory.trim() || null,
      });
      setEditingMemoryId(null);
      setEditingMemorySummary("");
      setEditingMemoryCategory("");
      toast.success("Memory updated");
      await loadProfile();
    } catch (error) {
      toast.error((error as Error).message || "Failed to update memory");
    } finally {
      setBusyKey(null);
    }
  };

  const beginPreferenceEdit = (preference: Preference) => {
    setEditingPreferenceId(preference.id);
    setEditingPreferenceValue(preference.value);
  };

  const beginMemoryEdit = (memory: MemoryProfileItem) => {
    setEditingMemoryId(memory.id);
    setEditingMemorySummary(memory.summary);
    setEditingMemoryCategory(memory.category || "");
  };

  if (loading && !profile) {
    return <div className="flex-1 p-4 text-sm text-muted-foreground">Loading learning profile…</div>;
  }

  if (!profile) {
    return <div className="flex-1 p-4 text-sm text-muted-foreground">Learning profile unavailable.</div>;
  }

  return (
    <div className="flex-1 space-y-4 overflow-auto p-4" data-testid="learning-profile-panel">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <BrainCircuit className="h-4 w-4 text-primary" />
            Learning Profile
          </CardTitle>
          <CardDescription>
            Inspect what the agent thinks it knows about your habits, weak spots, and preferred explanations.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <SummaryList title="Strength Areas" items={profile.summary.strength_areas} />
          <SummaryList title="Weak Areas" items={profile.summary.weak_areas} />
          <SummaryList title="Recurring Errors" items={profile.summary.recurring_errors} />
          <SummaryList title="Inferred Habits" items={profile.summary.inferred_habits} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Sparkles className="h-4 w-4 text-primary" />
            Active Preferences
          </CardTitle>
          <CardDescription>These preferences currently influence prompts and workspace behavior.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {profile.preferences.length === 0 && <p className="text-sm text-muted-foreground">No active preferences yet.</p>}
          {profile.preferences.map((preference) => (
            <div key={preference.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{formatLabel(preference.dimension)}</p>
                  {editingPreferenceId === preference.id ? (
                    <Input
                      value={editingPreferenceValue}
                      onChange={(event) => setEditingPreferenceValue(event.target.value)}
                      className="mt-2 h-8"
                    />
                  ) : (
                    <p className="mt-1 text-sm text-muted-foreground">{preference.value}</p>
                  )}
                </div>
                <Badge variant="outline">{formatLabel(preference.scope)}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{formatLabel(preference.source)}</Badge>
                <Badge variant="outline">{Math.round(preference.confidence * 100)}%</Badge>
                <Badge variant="outline">{formatTime(preference.updated_at)}</Badge>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {editingPreferenceId === preference.id ? (
                  <>
                    <Button
                      size="sm"
                      onClick={() => void savePreference(preference)}
                      disabled={busyKey === `pref-save:${preference.id}` || !editingPreferenceValue.trim()}
                    >
                      Save
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingPreferenceId(null)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => beginPreferenceEdit(preference)}>
                    <Pencil className="mr-1 h-4 w-4" />
                    Edit
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void dismissWithReason(
                      `pref-dismiss:${preference.id}`,
                      (reason) => dismissPreferenceItem(preference.id, reason),
                      "Preference dismissed",
                    )
                  }
                  disabled={busyKey === `pref-dismiss:${preference.id}`}
                >
                  <ShieldBan className="mr-1 h-4 w-4" />
                  Dismiss
                </Button>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Active Memories</CardTitle>
          <CardDescription>Only non-dismissed memories are injected back into future agent turns.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {profile.memories.length === 0 && <p className="text-sm text-muted-foreground">No active memories yet.</p>}
          {profile.memories.map((memory) => (
            <div key={memory.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1">
                  <p className="text-sm font-medium">{formatLabel(memory.memory_type)}</p>
                  {editingMemoryId === memory.id ? (
                    <div className="mt-2 space-y-2">
                      <Textarea
                        value={editingMemorySummary}
                        onChange={(event) => setEditingMemorySummary(event.target.value)}
                        className="min-h-20"
                      />
                      <Input
                        value={editingMemoryCategory}
                        onChange={(event) => setEditingMemoryCategory(event.target.value)}
                        placeholder="Category"
                        className="h-8"
                      />
                    </div>
                  ) : (
                    <>
                      <p className="mt-1 text-sm text-muted-foreground whitespace-pre-wrap">{memory.summary}</p>
                      {memory.source_message && (
                        <p className="mt-2 text-xs text-muted-foreground">From: {memory.source_message}</p>
                      )}
                    </>
                  )}
                </div>
                <Badge variant="outline">{memory.category || "uncategorized"}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">importance {memory.importance.toFixed(2)}</Badge>
                <Badge variant="outline">accessed {memory.access_count}</Badge>
                <Badge variant="outline">{formatTime(memory.updated_at || memory.created_at)}</Badge>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {editingMemoryId === memory.id ? (
                  <>
                    <Button
                      size="sm"
                      onClick={() => void saveMemory(memory)}
                      disabled={busyKey === `memory-save:${memory.id}` || !editingMemorySummary.trim()}
                    >
                      Save
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingMemoryId(null)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => beginMemoryEdit(memory)}>
                    <Pencil className="mr-1 h-4 w-4" />
                    Edit
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void dismissWithReason(
                      `memory-dismiss:${memory.id}`,
                      (reason) => dismissMemoryItem(memory.id, reason),
                      "Memory dismissed",
                    )
                  }
                  disabled={busyKey === `memory-dismiss:${memory.id}`}
                >
                  <ShieldBan className="mr-1 h-4 w-4" />
                  Dismiss
                </Button>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Preference Signals</CardTitle>
          <CardDescription>Signals explain why the system inferred a habit or a preferred format.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {profile.signals.length === 0 && <p className="text-sm text-muted-foreground">No live preference signals.</p>}
          {profile.signals.map((signal: PreferenceSignal) => (
            <div key={signal.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">
                    {formatLabel(signal.dimension)}: {signal.value}
                  </p>
                  {signal.context?.evidence && (
                    <p className="mt-1 text-xs text-muted-foreground whitespace-pre-wrap">{signal.context.evidence}</p>
                  )}
                </div>
                <Badge variant="outline">{formatLabel(signal.signal_type)}</Badge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline">{formatTime(signal.created_at)}</Badge>
              </div>
              <div className="mt-3">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    void dismissWithReason(
                      `signal-dismiss:${signal.id}`,
                      (reason) => dismissPreferenceSignal(signal.id, reason),
                      "Signal dismissed",
                    )
                  }
                  disabled={busyKey === `signal-dismiss:${signal.id}`}
                >
                  <ShieldBan className="mr-1 h-4 w-4" />
                  Dismiss
                </Button>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Dismissed Items</CardTitle>
          <CardDescription>Dismissed preferences and memories stay out of prompt injection until restored.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Preferences</p>
            {profile.dismissed_preferences.length === 0 ? (
              <p className="text-sm text-muted-foreground">No dismissed preferences.</p>
            ) : (
              profile.dismissed_preferences.map((preference) => (
                <div key={preference.id} className="rounded-lg border p-3">
                  <p className="text-sm font-medium">{formatLabel(preference.dimension)}: {preference.value}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {preference.dismissal_reason || "Dismissed without a note"} · {formatTime(preference.dismissed_at)}
                  </p>
                  <div className="mt-3">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        void restoreItem(
                          `pref-restore:${preference.id}`,
                          () => restorePreferenceItem(preference.id),
                          "Preference restored",
                        )
                      }
                      disabled={busyKey === `pref-restore:${preference.id}`}
                    >
                      <RotateCcw className="mr-1 h-4 w-4" />
                      Restore
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Memories</p>
            {profile.dismissed_memories.length === 0 ? (
              <p className="text-sm text-muted-foreground">No dismissed memories.</p>
            ) : (
              profile.dismissed_memories.map((memory) => (
                <div key={memory.id} className="rounded-lg border p-3">
                  <p className="text-sm font-medium">{formatLabel(memory.memory_type)}</p>
                  <p className="mt-1 text-sm text-muted-foreground whitespace-pre-wrap">{memory.summary}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {memory.dismissal_reason || "Dismissed without a note"} · {formatTime(memory.dismissed_at)}
                  </p>
                  <div className="mt-3">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        void restoreItem(
                          `memory-restore:${memory.id}`,
                          () => restoreMemoryItem(memory.id),
                          "Memory restored",
                        )
                      }
                      disabled={busyKey === `memory-restore:${memory.id}`}
                    >
                      <RotateCcw className="mr-1 h-4 w-4" />
                      Restore
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Signals</p>
            {profile.dismissed_signals.length === 0 ? (
              <p className="text-sm text-muted-foreground">No dismissed signals.</p>
            ) : (
              profile.dismissed_signals.map((signal) => (
                <div key={signal.id} className="rounded-lg border p-3">
                  <p className="text-sm font-medium">
                    {formatLabel(signal.dimension)}: {signal.value}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {signal.dismissal_reason || "Dismissed without a note"} · {formatTime(signal.dismissed_at)}
                  </p>
                  <div className="mt-3">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        void restoreItem(
                          `signal-restore:${signal.id}`,
                          () => restorePreferenceSignal(signal.id),
                          "Signal restored",
                        )
                      }
                      disabled={busyKey === `signal-restore:${signal.id}`}
                    >
                      <RotateCcw className="mr-1 h-4 w-4" />
                      Restore
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
