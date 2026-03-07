"use client";

import { type ReactNode, Suspense, useState } from "react";
import { Button } from "@/components/ui/button";

export interface TabDef<T extends string> {
  id: T;
  label: string;
  testId?: string;
}

function SubViewSkeleton() {
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="h-4 w-32 bg-muted animate-pulse rounded" />
    </div>
  );
}

interface TabbedSectionProps<T extends string> {
  tabs: TabDef<T>[];
  defaultTab: T;
  testId: string;
  /** External override — when set, the tab switches to this value and the prop is cleared. */
  externalTab?: T | null;
  onExternalTabConsumed?: () => void;
  children: (activeTab: T) => ReactNode;
}

export function TabbedSection<T extends string>({
  tabs,
  defaultTab,
  testId,
  externalTab,
  onExternalTabConsumed,
  children,
}: TabbedSectionProps<T>) {
  const [activeTab, setActiveTab] = useState<T>(defaultTab);
  const externalCandidate =
    externalTab && tabs.some((t) => t.id === externalTab) ? externalTab : null;

  const resolvedActiveTab =
    tabs.find((tab) => tab.id === externalCandidate)?.id ??
    tabs.find((tab) => tab.id === activeTab)?.id ??
    tabs.find((tab) => tab.id === defaultTab)?.id ??
    tabs[0]?.id ??
    defaultTab;

  return (
    <div className="flex-1 flex flex-col overflow-hidden" data-testid={testId}>
      <div className="px-3 py-1.5 border-b shrink-0">
        <div className="flex items-center gap-1">
          {tabs.map((tab) => (
            <Button
              key={tab.id}
              type="button"
              size="sm"
              variant={resolvedActiveTab === tab.id ? "secondary" : "ghost"}
              className="h-6 px-2.5 text-xs"
              data-testid={tab.testId}
              onClick={() => {
                if (externalCandidate) onExternalTabConsumed?.();
                setActiveTab(tab.id);
              }}
            >
              {tab.label}
            </Button>
          ))}
        </div>
      </div>

      <Suspense fallback={<SubViewSkeleton />}>
        {children(resolvedActiveTab)}
      </Suspense>
    </div>
  );
}
