"use client";

import { useEffect, useRef, useState } from "react";
import { recommendScene, type SceneRecommendation, type SwitchResult } from "@/lib/api";
import { useSceneStore, type Scene } from "@/store/scene";

interface SceneSelectorProps {
  courseId: string;
  activeTab?: string;
  getCurrentUiState?: () => Record<string, unknown>;
  onSwitch?: (sceneId: string, result: SwitchResult) => void;
}

export function SceneSelector({ courseId, activeTab, getCurrentUiState, onSwitch }: SceneSelectorProps) {
  const { activeScene, scenes, fetchScenes, fetchActiveScene, switchScene, isSwitching } =
    useSceneStore();
  const [open, setOpen] = useState(false);
  const [recommendation, setRecommendation] = useState<SceneRecommendation | null>(null);
  const [loadingRecommendation, setLoadingRecommendation] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchScenes();
    fetchActiveScene(courseId);
  }, [courseId, fetchScenes, fetchActiveScene]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setLoadingRecommendation(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const currentScene = scenes.find((s) => s.scene_id === activeScene);
  const displayName = currentScene?.display_name || activeScene;
  const icon = currentScene?.icon || "";

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    recommendScene(courseId, activeTab, "")
      .then((result) => {
        if (!cancelled) {
          setRecommendation(result);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRecommendation(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingRecommendation(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeTab, courseId, open]);

  const handleSwitch = async (scene: Scene) => {
    setOpen(false);
    if (scene.scene_id === activeScene) return;

    const result = await switchScene(courseId, scene.scene_id, getCurrentUiState?.());
    onSwitch?.(scene.scene_id, result);
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => {
          const nextOpen = !open;
          if (nextOpen) {
            setLoadingRecommendation(true);
          } else {
            setRecommendation(null);
            setLoadingRecommendation(false);
          }
          setOpen(nextOpen);
        }}
        data-testid="scene-selector-trigger"
        disabled={isSwitching}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border bg-background text-xs font-medium text-foreground hover:border-brand hover:text-brand transition-colors disabled:opacity-50"
      >
        {icon && <span>{icon}</span>}
        <span>{displayName}</span>
        <span className={`text-[10px] transition-transform inline-block ${open ? "rotate-180" : ""}`} aria-hidden="true">{"\u25BC"}</span>
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-72 bg-background border border-border rounded-lg shadow-lg z-50 py-1">
          {loadingRecommendation && (
            <div className="px-3 py-2 text-xs text-muted-foreground">Loading recommendation...</div>
          )}
          {recommendation && recommendation.switch_recommended && recommendation.scene_id !== activeScene && (
            <div className="mx-2 mb-2 rounded-lg border border-brand/30 bg-brand/5 px-3 py-2 text-xs text-foreground">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 text-brand font-bold text-xs">*</span>
                <div className="space-y-1">
                  <p className="font-semibold">
                    Recommended: {scenes.find((scene) => scene.scene_id === recommendation.scene_id)?.display_name || recommendation.scene_id}
                  </p>
                  <p>{recommendation.reason}</p>
                  {recommendation.expected_benefit && (
                    <p className="text-brand">Benefit: {recommendation.expected_benefit}</p>
                  )}
                  {recommendation.reversible_action && (
                    <p className="text-brand">Reversible: {recommendation.reversible_action}</p>
                  )}
                  <div className="flex flex-wrap gap-1">
                    <span className="rounded-full border border-brand/30 bg-background px-2 py-0.5 text-[10px]">
                      {recommendation.layout_policy}
                    </span>
                    <span className="rounded-full border border-brand/30 bg-background px-2 py-0.5 text-[10px]">
                      {recommendation.reasoning_policy}
                    </span>
                    <span className="rounded-full border border-brand/30 bg-background px-2 py-0.5 text-[10px]">
                      {recommendation.workflow_policy}
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      const scene = scenes.find((entry) => entry.scene_id === recommendation.scene_id);
                      if (scene) {
                        void handleSwitch(scene);
                      }
                    }}
                    className="mt-1 rounded-md border border-brand/40 bg-background px-2 py-1 text-[11px] font-medium text-brand hover:bg-brand/10"
                  >
                    Switch to recommended scene
                  </button>
                </div>
              </div>
            </div>
          )}
          {scenes.map((scene) => (
            <button
              key={scene.scene_id}
              onClick={() => handleSwitch(scene)}
              data-testid={`scene-option-${scene.scene_id}`}
              className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-muted transition-colors ${
                scene.scene_id === activeScene
                  ? "bg-muted text-brand font-medium"
                  : "text-foreground"
              }`}
            >
              <span>{scene.icon || ""}</span>
              <span>{scene.display_name}</span>
              {scene.scene_id === activeScene && (
                <span className="ml-auto text-[10px] text-brand/60">active</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
