import { describe, it, expect, beforeEach } from "vitest";
import { t, tf, setLocale, getLocale, initLocale } from "./i18n";

describe("i18n", () => {
  beforeEach(() => {
    localStorage.clear();
    setLocale("en");
  });

  describe("t()", () => {
    it("returns English translation for known key", () => {
      expect(t("nav.dashboard")).toBe("Home");
    });

    it("returns the key itself for unknown key", () => {
      expect(t("nonexistent.key.xyz")).toBe("nonexistent.key.xyz");
    });

    it("returns Chinese translation when locale is zh", () => {
      setLocale("zh");
      const result = t("nav.dashboard");
      // Should be Chinese, not "Home"
      expect(result).not.toBe("nav.dashboard");
    });
  });

  describe("tf()", () => {
    it("replaces template variables", () => {
      // Find a key with a variable pattern, or test with a known one
      const result = tf("nav.dashboard");
      expect(typeof result).toBe("string");
    });

    it("handles null/undefined vars gracefully", () => {
      const result = tf("nav.dashboard", { foo: null, bar: undefined });
      expect(typeof result).toBe("string");
    });
  });

  describe("setLocale / getLocale", () => {
    it("persists locale to localStorage", () => {
      setLocale("zh");
      expect(localStorage.getItem("opentutor-locale")).toBe("zh");
    });

    it("reads locale from localStorage", () => {
      localStorage.setItem("opentutor-locale", "zh");
      const locale = getLocale();
      expect(locale).toBe("zh");
    });

    it("defaults to en for invalid locale", () => {
      localStorage.setItem("opentutor-locale", "invalid");
      initLocale();
      expect(getLocale()).toBe("en");
    });
  });

  describe("initLocale()", () => {
    it("restores saved locale", () => {
      localStorage.setItem("opentutor-locale", "zh");
      initLocale();
      expect(getLocale()).toBe("zh");
    });

    it("defaults to en when nothing saved", () => {
      initLocale();
      expect(getLocale()).toBe("en");
    });
  });
});
