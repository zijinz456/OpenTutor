"use client";

import { create } from "zustand";


interface PersistedBadDayState {
  active: boolean;
  activated_date: string;
}

export interface BadDayState extends PersistedBadDayState {
  toggle: () => void;
  isActiveToday: () => boolean;
}

const STORAGE_KEY = "ld:bad-day";
const EMPTY_STATE: PersistedBadDayState = { active: false, activated_date: "" };

function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

function readInitial(): PersistedBadDayState {
  if (typeof window === "undefined") return EMPTY_STATE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_STATE;
    const parsed = JSON.parse(raw) as Partial<PersistedBadDayState>;
    return {
      active: parsed.active === true,
      activated_date:
        typeof parsed.activated_date === "string" ? parsed.activated_date : "",
    };
  } catch {
    return EMPTY_STATE;
  }
}

function writeState(next: PersistedBadDayState): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

export const useBadDayStore = create<BadDayState>((set, get) => ({
  ...readInitial(),

  toggle: () => {
    const next: PersistedBadDayState = get().isActiveToday()
      ? { active: false, activated_date: todayUtc() }
      : { active: true, activated_date: todayUtc() };
    set(next);
    writeState(next);
  },

  isActiveToday: () => {
    const state = get();
    return state.active && state.activated_date === todayUtc();
  },
}));
