"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Sparkles } from "lucide-react";
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
  const icon = currentScene?.icon || "📚";

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
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-gray-200 bg-white text-xs font-medium text-gray-700 hover:border-indigo-400 hover:text-indigo-600 transition-colors disabled:opacity-50"
      >
        <span>{icon}</span>
        <span>{displayName}</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-72 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1">
          {loadingRecommendation && (
            <div className="px-3 py-2 text-xs text-gray-500">Loading recommendation…</div>
          )}
          {recommendation && recommendation.switch_recommended && recommendation.scene_id !== activeScene && (
            <div className="mx-2 mb-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-900">
              <div className="flex items-start gap-2">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 text-indigo-500" />
                <div className="space-y-1">
                  <p className="font-semibold">
                    Recommended: {scenes.find((scene) => scene.scene_id === recommendation.scene_id)?.display_name || recommendation.scene_id}
                  </p>
                  <p>{recommendation.reason}</p>
                  {recommendation.expected_benefit && (
                    <p className="text-indigo-700">Benefit: {recommendation.expected_benefit}</p>
                  )}
                  {recommendation.reversible_action && (
                    <p className="text-indigo-700">Reversible: {recommendation.reversible_action}</p>
                  )}
                  <div className="flex flex-wrap gap-1">
                    <span className="rounded-full border border-indigo-200 bg-white px-2 py-0.5 text-[10px]">
                      {recommendation.layout_policy}
                    </span>
                    <span className="rounded-full border border-indigo-200 bg-white px-2 py-0.5 text-[10px]">
                      {recommendation.reasoning_policy}
                    </span>
                    <span className="rounded-full border border-indigo-200 bg-white px-2 py-0.5 text-[10px]">
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
                    className="mt-1 rounded-md border border-indigo-300 bg-white px-2 py-1 text-[11px] font-medium text-indigo-700 hover:bg-indigo-100"
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
              className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-indigo-50 transition-colors ${
                scene.scene_id === activeScene
                  ? "bg-indigo-50 text-indigo-700 font-medium"
                  : "text-gray-700"
              }`}
            >
              <span>{scene.icon || "📄"}</span>
              <span>{scene.display_name}</span>
              {scene.scene_id === activeScene && (
                <span className="ml-auto text-[10px] text-indigo-400">active</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
