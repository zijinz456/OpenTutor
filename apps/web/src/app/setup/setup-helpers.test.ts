import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api/client", () => ({
  request: vi.fn(),
  API_BASE: "http://localhost:8000/api",
}));

vi.mock("@/lib/api", () => ({
  setPreference: vi.fn().mockResolvedValue({}),
}));

vi.mock("@/store/workspace", () => ({
  useWorkspaceStore: Object.assign(
    () => ({}),
    { getState: () => ({ setSpaceLayout: vi.fn() }), setState: vi.fn() },
  ),
}));

describe("setup-helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("validateNameValue returns null for valid names", async () => {
    const { validateNameValue } = await import("./setup-helpers");
    const t = (key: string) => key;
    expect(validateNameValue("My Course", t)).toBeNull();
  });

  it("validateNameValue returns error for empty name", async () => {
    const { validateNameValue } = await import("./setup-helpers");
    const t = (key: string) => key;
    expect(validateNameValue("", t)).toBeTruthy();
  });

  it("validateNameValue returns error for name too long", async () => {
    const { validateNameValue } = await import("./setup-helpers");
    const t = (key: string) => key;
    const longName = "a".repeat(101);
    expect(validateNameValue(longName, t)).toBeTruthy();
  });

  it("validateUrlValue returns no error for valid URL", async () => {
    const { validateUrlValue } = await import("./setup-helpers");
    const t = (key: string) => key;
    const result = validateUrlValue("https://example.com", t);
    expect(result.error).toBeNull();
  });

  it("validateUrlValue returns error for invalid URL", async () => {
    const { validateUrlValue } = await import("./setup-helpers");
    const t = (key: string) => key;
    const result = validateUrlValue("not a url", t);
    expect(result.error).toBeTruthy();
  });

  it("validateUrlValue detects Canvas URLs", async () => {
    const { validateUrlValue } = await import("./setup-helpers");
    const t = (key: string) => key;
    const result = validateUrlValue("https://school.instructure.com/courses/123", t);
    expect(result.isCanvas).toBe(true);
  });

  it("buildCourseMetadata produces metadata with workspace features", async () => {
    const { buildCourseMetadata } = await import("./setup-helpers");
    const result = buildCourseMetadata(
      [] as unknown as { length: number }, // no files
      "https://example.com",
      "stem_student",
      "course_following",
    );
    expect(result.metadata).toBeTruthy();
    expect(result.sourceMode).toBe("url");
  });

  it("buildCourseMetadata handles upload mode", async () => {
    const { buildCourseMetadata } = await import("./setup-helpers");
    const fakeFiles = [{ name: "test.pdf" }];
    const result = buildCourseMetadata(
      fakeFiles as unknown as { length: number },
      "",
      null,
      null,
    );
    expect(result.sourceMode).toBe("upload");
  });
});
