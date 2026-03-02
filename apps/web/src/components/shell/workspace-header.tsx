"use client";

import Link from "next/link";
import { ArrowLeft, Settings, ChevronDown, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { useSceneStore } from "@/store/scene";
import { useT } from "@/lib/i18n-context";
import { NotificationBell } from "@/components/shared/notification-bell";

interface WorkspaceHeaderProps {
  courseId: string;
  courseName: string;
}

/**
 * Thin top bar for the workspace.
 *
 * Scene data is fetched by the parent page — this component only reads store state.
 */
export function WorkspaceHeader({ courseId, courseName }: WorkspaceHeaderProps) {
  const t = useT();
  const activeScene = useSceneStore((s) => s.activeScene);
  const scenes = useSceneStore((s) => s.scenes);
  const switchScene = useSceneStore((s) => s.switchScene);
  const isSwitching = useSceneStore((s) => s.isSwitching);

  const currentScene = scenes.find((s) => s.scene_id === activeScene);
  const sceneDisplayName = currentScene?.display_name ?? activeScene;
  const sceneIcon = currentScene?.icon ?? "";

  const handleSceneSwitch = async (sceneId: string) => {
    if (sceneId === activeScene) return;
    await switchScene(courseId, sceneId);
  };

  return (
    <header
      className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3"
      style={{ background: "var(--section-header)" }}
    >
      {/* Left: back + course name */}
      <div className="flex items-center gap-1.5 min-w-0">
        <Button
          variant="ghost"
          size="icon-xs"
          asChild
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          <Link href="/" aria-label={t("nav.back") || "Back"}>
            <ArrowLeft className="size-3.5" />
          </Link>
        </Button>

        <span className="truncate text-xs font-medium text-foreground">
          {courseName}
        </span>
      </div>

      {/* Right: scene selector + settings */}
      <div className="ml-auto flex items-center gap-1.5">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="xs"
              disabled={isSwitching}
              className="gap-1 text-xs font-medium"
              data-testid="workspace-scene-trigger"
            >
              {sceneIcon && <span className="text-xs">{sceneIcon}</span>}
              <span className="max-w-[120px] truncate">{sceneDisplayName}</span>
              <ChevronDown className="size-3 text-muted-foreground" />
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              {t("course.scene") || "Scene"}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />

            {scenes.map((scene) => (
              <DropdownMenuItem
                key={scene.scene_id}
                onClick={() => void handleSceneSwitch(scene.scene_id)}
                className="gap-2 text-xs"
                data-testid={`workspace-scene-${scene.scene_id}`}
              >
                {scene.icon && <span>{scene.icon}</span>}
                <span className="flex-1 truncate">{scene.display_name}</span>
                {scene.scene_id === activeScene && (
                  <Check className="size-3.5 text-primary" />
                )}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <NotificationBell />

        <Button
          variant="ghost"
          size="icon-xs"
          asChild
          className="text-muted-foreground hover:text-foreground"
        >
          <Link href="/settings" aria-label={t("nav.settings") || "Settings"}>
            <Settings className="size-3.5" />
          </Link>
        </Button>
      </div>
    </header>
  );
}
