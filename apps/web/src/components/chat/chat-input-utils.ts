import type { ImageAttachment } from "@/lib/api";

export const ACCEPTED_FILE_TYPES =
  ".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md,.csv,.xlsx,.xls";

export const MAX_IMAGE_SIZE = 10 * 1024 * 1024; // 10MB
export const MAX_IMAGES = 5;

/** Convert a File to a base64-encoded ImageAttachment. */
export async function fileToImageAttachment(
  file: File,
): Promise<ImageAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Strip the data:...;base64, prefix
      const base64 = result.split(",")[1];
      resolve({
        data: base64,
        media_type: file.type || "image/png",
        filename: file.name,
      });
    };
    reader.onerror = () => reject(new Error("Failed to read image file"));
    reader.readAsDataURL(file);
  });
}

/**
 * Derive the `active_tab` hint sent with chat messages from the current
 * route, e.g. `/course/abc/practice` → "practice". Falls back to "workspace".
 */
export function activeTabFromPathname(pathname: string | null): string {
  const match = pathname?.match(/^\/course\/[^/]+\/([^/?#]+)/);
  const segment = match?.[1];
  switch (segment) {
    case "notes":
    case "practice":
    case "plan":
    case "review":
    case "unit":
      return segment;
    case "profile":
      return "analytics";
    default:
      return "workspace";
  }
}
