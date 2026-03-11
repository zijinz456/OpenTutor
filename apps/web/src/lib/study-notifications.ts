/**
 * Browser notification system for study reminders.
 * Uses the Notification API to remind users during their optimal study windows.
 */

import { getOptimalStudyWindows, getPersona, formatStudyWindow } from "./learner-persona";

const NOTIF_PERM_KEY = "opentutor_notif_permission";
const LAST_NOTIF_KEY = "opentutor_last_study_notif";

/** Request notification permission if not already granted. */
export async function requestNotificationPermission(): Promise<boolean> {
  if (typeof window === "undefined" || !("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;

  const result = await Notification.requestPermission();
  if (result === "granted") {
    try { localStorage.setItem(NOTIF_PERM_KEY, "granted"); } catch { /* quota */ }
    return true;
  }
  return false;
}

/** Check if we should send a study reminder right now. */
function shouldNotify(): boolean {
  const persona = getPersona();
  if (persona.totalSessions < 5) return false; // need enough data

  const windows = getOptimalStudyWindows();
  if (windows.length === 0) return false;

  const now = new Date();
  const currentDay = now.getDay();
  const currentHour = now.getHours();

  // Check if current time matches an optimal window
  const match = windows.find(
    (w) => w.dayOfWeek === currentDay && w.hour === currentHour,
  );
  if (!match) return false;

  // Don't notify more than once per 4 hours
  const lastNotif = localStorage.getItem(LAST_NOTIF_KEY);
  if (lastNotif) {
    const lastTime = new Date(lastNotif).getTime();
    if (Date.now() - lastTime < 4 * 60 * 60 * 1000) return false;
  }

  return true;
}

/** Send a study reminder notification if appropriate. */
export function checkAndNotifyStudyReminder(): void {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  if (!shouldNotify()) return;

  try { localStorage.setItem(LAST_NOTIF_KEY, new Date().toISOString()); } catch { /* quota */ }

  const windows = getOptimalStudyWindows();
  const windowLabel = windows.length > 0 ? formatStudyWindow(windows[0]) : "";

  // Use locale-aware strings from localStorage cache if available,
  // fallback to English since Notification API runs outside React context.
  let title = "Time to study!";
  let body = `This is your usual study time (${windowLabel}). Open OpenTutor to keep your streak going.`;
  try {
    const locale = localStorage.getItem("opentutor_locale") ?? "en";
    if (locale === "zh") {
      title = "\u8BE5\u5B66\u4E60\u4E86\uFF01";
      body = `\u73B0\u5728\u662F\u4F60\u7684\u5E38\u89C4\u5B66\u4E60\u65F6\u95F4\uFF08${windowLabel}\uFF09\u3002\u6253\u5F00 OpenTutor \u4FDD\u6301\u5B66\u4E60\u8282\u594F\u3002`;
    }
  } catch { /* ignore */ }
  new Notification(title, {
    body,
    icon: "/favicon.ico",
    tag: "opentutor-study-reminder",
  });
}

/**
 * Initialize the study notification checker.
 * Call once on app mount. Checks every 30 minutes.
 */
export function initStudyNotifications(): () => void {
  // Initial check after a short delay
  const initialTimer = setTimeout(checkAndNotifyStudyReminder, 5000);
  // Periodic check every 30 minutes
  const intervalId = setInterval(checkAndNotifyStudyReminder, 30 * 60 * 1000);

  return () => {
    clearTimeout(initialTimer);
    clearInterval(intervalId);
  };
}
