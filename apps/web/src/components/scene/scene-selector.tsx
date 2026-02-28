"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { type SwitchResult } from "@/lib/api";
import { useSceneStore, type Scene } from "@/store/scene";

interface SceneSelectorProps {
  courseId: string;
  getCurrentUiState?: () => Record<string, unknown>;
  onSwitch?: (sceneId: string, result: SwitchResult) => void;
}

export function SceneSelector({ courseId, getCurrentUiState, onSwitch }: SceneSelectorProps) {
  const { activeScene, scenes, fetchScenes, fetchActiveScene, switchScene, isSwitching } =
    useSceneStore();
  const [open, setOpen] = useState(false);
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
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const currentScene = scenes.find((s) => s.scene_id === activeScene);
  const displayName = currentScene?.display_name || activeScene;
  const icon = currentScene?.icon || "📚";

  const handleSwitch = async (scene: Scene) => {
    setOpen(false);
    if (scene.scene_id === activeScene) return;

    const result = await switchScene(courseId, scene.scene_id, getCurrentUiState?.());
    onSwitch?.(scene.scene_id, result);
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        data-testid="scene-selector-trigger"
        disabled={isSwitching}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-gray-200 bg-white text-xs font-medium text-gray-700 hover:border-indigo-400 hover:text-indigo-600 transition-colors disabled:opacity-50"
      >
        <span>{icon}</span>
        <span>{displayName}</span>
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-48 bg-white border border-gray-200 rounded-lg shadow-lg z-50 py-1">
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
