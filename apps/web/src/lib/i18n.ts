import en from "@/locales/en.json";
import zh from "@/locales/zh.json";

export type Locale = "en" | "zh";

const SUPPORTED_LOCALES: Locale[] = ["en", "zh"];

const translations: Record<Locale, Record<string, string>> = { en, zh };

let currentLocale: Locale = "en";

export function setLocale(locale: Locale): void {
  currentLocale = locale;
  if (typeof window !== "undefined") {
    localStorage.setItem("opentutor-locale", locale);
  }
}

export function getLocale(): Locale {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("opentutor-locale") as Locale | null;
    if (saved && SUPPORTED_LOCALES.includes(saved)) {
      currentLocale = saved;
    }
  }
  return currentLocale;
}

export function t(key: string): string {
  return translations[currentLocale]?.[key] ?? translations.en[key] ?? key;
}

export function initLocale(): void {
  if (typeof window !== "undefined") {
    const saved = localStorage.getItem("opentutor-locale") as Locale | null;
    if (saved && SUPPORTED_LOCALES.includes(saved)) {
      currentLocale = saved;
    } else {
      currentLocale = "en";
    }
  }
}
