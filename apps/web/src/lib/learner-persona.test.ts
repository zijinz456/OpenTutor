import { describe, it, expect, beforeEach } from "vitest";
import {
  getPersona,
  updatePersona,
  recordSessionVisit,
  getOptimalStudyWindows,
  formatStudyWindow,
} from "./learner-persona";

describe("learner-persona", () => {
  beforeEach(() => localStorage.clear());

  describe("getPersona", () => {
    it("returns defaults when nothing stored", () => {
      const persona = getPersona();
      expect(persona.noteFormat).toBe("auto");
      expect(persona.totalSessions).toBe(0);
      expect(persona.studyTimes).toEqual([]);
    });

    it("merges stored data with defaults", () => {
      localStorage.setItem(
        "opentutor_learner_persona",
        JSON.stringify({ noteFormat: "summary", totalSessions: 5 }),
      );
      const persona = getPersona();
      expect(persona.noteFormat).toBe("summary");
      expect(persona.totalSessions).toBe(5);
      expect(persona.explanationStyle).toBe("balanced"); // default preserved
    });
  });

  describe("updatePersona", () => {
    it("persists partial updates", () => {
      updatePersona({ difficultyPreference: "hard" });
      const persona = getPersona();
      expect(persona.difficultyPreference).toBe("hard");
      expect(persona.noteFormat).toBe("auto"); // other fields intact
    });
  });

  describe("recordSessionVisit", () => {
    it("increments session count", () => {
      recordSessionVisit();
      const persona = getPersona();
      expect(persona.totalSessions).toBe(1);
      expect(persona.lastSessionAt).toBeTruthy();
    });

    it("skips if last session was less than 30 minutes ago", () => {
      const recent = new Date().toISOString();
      updatePersona({ lastSessionAt: recent, totalSessions: 1 });
      recordSessionVisit();
      expect(getPersona().totalSessions).toBe(1); // not incremented
    });

    it("records study time histogram", () => {
      // Set last session to more than 30 min ago so it records
      const old = new Date(Date.now() - 60 * 60 * 1000).toISOString();
      updatePersona({ lastSessionAt: old });
      recordSessionVisit();
      expect(getPersona().studyTimes.length).toBeGreaterThan(0);
    });
  });

  describe("getOptimalStudyWindows", () => {
    it("returns top 3 study time slots", () => {
      updatePersona({
        studyTimes: [
          { dayOfWeek: 1, hour: 9, count: 10 },
          { dayOfWeek: 2, hour: 14, count: 8 },
          { dayOfWeek: 3, hour: 20, count: 5 },
          { dayOfWeek: 4, hour: 11, count: 3 },
        ],
      });
      const windows = getOptimalStudyWindows();
      expect(windows).toHaveLength(3);
      expect(windows[0].count).toBe(10);
    });
  });

  describe("formatStudyWindow", () => {
    it("formats hour and day", () => {
      const result = formatStudyWindow({ dayOfWeek: 1, hour: 14 });
      expect(result).toContain("2PM");
    });

    it("handles midnight", () => {
      const result = formatStudyWindow({ dayOfWeek: 0, hour: 0 });
      expect(result).toContain("12AM");
    });
  });
});
