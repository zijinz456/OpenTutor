/**
 * Scene state management using Zustand.
 *
 * Manages active scene, available scenes, and scene switching for the v3 scene system.
 */

import { create } from "zustand";
import { listScenes, getActiveScene, switchScene, type SceneConfig, type SwitchResult } from "@/lib/api";

export type Scene = SceneConfig & { is_preset?: boolean };

interface SceneState {
  activeScene: string;
  scenes: Scene[];
  sceneConfig: SceneConfig | null;
  isLoading: boolean;
  isSwitching: boolean;
  error: string | null;

  fetchScenes: () => Promise<void>;
  fetchActiveScene: (courseId: string) => Promise<void>;
  switchScene: (courseId: string, sceneId: string, uiState?: Record<string, unknown>) => Promise<SwitchResult>;
  setActiveScene: (sceneId: string) => void;
}

export const useSceneStore = create<SceneState>((set) => ({
  activeScene: "study_session",
  scenes: [],
  sceneConfig: null,
  isLoading: false,
  isSwitching: false,
  error: null,

  fetchScenes: async () => {
    set({ isLoading: true, error: null });
    try {
      const scenes = await listScenes();
      set({ scenes, isLoading: false });
    } catch (e) {
      set({ isLoading: false, error: (e as Error).message });
    }
  },

  fetchActiveScene: async (courseId: string) => {
    try {
      const result = await getActiveScene(courseId);
      set({
        activeScene: result.scene_id,
        sceneConfig: result.config,
      });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  switchScene: async (courseId: string, sceneId: string, uiState?: Record<string, unknown>) => {
    set({ isSwitching: true });
    try {
      const result = await switchScene(courseId, sceneId, uiState);
      set({
        activeScene: result.scene_id,
        sceneConfig: result.config,
        isSwitching: false,
      });
      return result;
    } catch (e) {
      set({ isSwitching: false });
      throw e;
    }
  },

  setActiveScene: (sceneId: string) => set({ activeScene: sceneId }),
}));
