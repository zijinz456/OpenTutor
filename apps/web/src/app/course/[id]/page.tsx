"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useWorkspaceStore } from "@/store/workspace";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { RuntimeAlert } from "@/components/shared/runtime-alert";
import { IngestionProgress } from "@/components/shared/ingestion-progress";
import { ContinueLearningCta } from "@/components/course/continue-learning-cta";
import { BlockGrid } from "@/components/blocks/block-grid";
import { ChatFab } from "@/components/chat/chat-fab";
import { ChatDrawer } from "@/components/chat/chat-drawer";
import { SearchDialog } from "@/components/shared/search-dialog";
import { NotesDrawer } from "@/components/blocks/notes-drawer";
import { ErrorBoundary } from "@/components/shared/error-boundary";
import { useT } from "@/lib/i18n-context";
import { useCourseData } from "./_components/use-course-data";
import { useBlockPersistence } from "./_components/use-block-persistence";
import { useChatActions, useQueueModeSuggestion } from "./_components/use-chat-actions";
import { useUnlockSuggestions, useReviewCheck } from "./_components/use-agent-autonomy";
import { useModeEvaluator, useInitPrompt, useGreeting } from "./_components/use-agent-lifecycle";
import { TemplatePicker } from "./_components/template-picker";
import { SyncSettingsPanel } from "@/components/course/sync-settings-panel";

export default function CoursePage() {
  const params = useParams();
  const t = useT();
  const courseId = params.id as string;
  const [chatOpen, setChatOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const notesDrawerOpen = useWorkspaceStore((s) => s.notesDrawerOpen);
  const setNotesDrawerOpen = useWorkspaceStore((s) => s.setNotesDrawerOpen);

  const { health, course, courses, contentTree, aiActionsEnabled } = useCourseData(courseId);
  const { blocks, blocksInitialized } = useBlockPersistence(courseId, course);
  const applyBlockTemplate = useWorkspaceStore((s) => s.applyBlockTemplate);

  const handleIngestionComplete = useCallback(() => {
    const store = useWorkspaceStore.getState();
    if (store.spaceLayout.blocks.length === 0) {
      store.applyBlockTemplate("stem_student");
    }
  }, []);
  const handleAction = useChatActions(courseId);
  const queueModeSuggestion = useQueueModeSuggestion(courseId);

  useUnlockSuggestions(courseId, courses, contentTree, health, blocksInitialized);
  useReviewCheck(courseId, course, aiActionsEnabled);
  useModeEvaluator(courseId, course, aiActionsEnabled, queueModeSuggestion);
  useInitPrompt(courseId, setChatOpen);
  useGreeting(courseId, course, handleAction);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const hasBlocks = blocks.length > 0;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <WorkspaceHeader courseName={course?.name || t("course.defaultTitle")} courseId={courseId} />

      <div className="px-5 pt-4 max-w-5xl mx-auto w-full space-y-3">
        <RuntimeAlert health={health} />
        <SyncSettingsPanel courseId={courseId} />
        <IngestionProgress
          courseId={courseId}
          onIngestionComplete={handleIngestionComplete}
        />
      </div>

      <main className="flex-1 max-w-5xl mx-auto w-full px-5 py-8 space-y-6">
        <ErrorBoundary section="workspace">
          {hasBlocks ? (
            <BlockGrid courseId={courseId} aiActionsEnabled={aiActionsEnabled} />
          ) : (
            <>
              <ContinueLearningCta courseId={courseId} nodes={contentTree} />
              <TemplatePicker onApplyTemplate={applyBlockTemplate} />
            </>
          )}
        </ErrorBoundary>
      </main>

      <ChatFab open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ErrorBoundary section="chat">
        <ChatDrawer
          courseId={courseId}
          open={chatOpen}
          aiActionsEnabled={aiActionsEnabled}
        />
      </ErrorBoundary>
      <ErrorBoundary section="notes-drawer">
        <NotesDrawer
          courseId={courseId}
          open={notesDrawerOpen}
          onOpenChange={setNotesDrawerOpen}
          aiActionsEnabled={aiActionsEnabled}
        />
      </ErrorBoundary>
      <SearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} courseId={courseId} />
    </div>
  );
}
