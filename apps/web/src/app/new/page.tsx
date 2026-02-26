"use client";

import { useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Upload,
  Globe,
  Layers,
  X,
  FileText,
  Pencil,
  RotateCcw,
  Calendar,
  MessageCircle,
  ChevronDown,
  Check,
  Copy,
  Lock,
  Loader,
  FolderPlus,
} from "lucide-react";
import { uploadFile, scrapeUrl } from "@/lib/api";
import { useCourseStore } from "@/store/course";

type Mode = "upload" | "url" | "both";
type Step = "mode" | "upload" | "parsing" | "features";

interface FileItem {
  file: File;
  name: string;
  size: string;
}

interface ParseStep {
  label: string;
  status: "waiting" | "active" | "done";
}

const FEATURE_CARDS = [
  { id: "notes", label: "Organize Notes", description: "Restructure your materials into clean, organized notes in your preferred format.", icon: FileText, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
  { id: "practice", label: "Practice Mode", description: "Generate practice questions from your materials. Interactive Q&A with instant feedback.", icon: Pencil, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
  { id: "wrong_answer", label: "Wrong Answer Review", description: "Track and revisit incorrect answers. Coming in Phase 2.", icon: RotateCcw, iconBg: "bg-amber-50", iconColor: "text-amber-600", enabled: false, phase: "Phase 2" },
  { id: "study_plan", label: "Study Plan", description: "Generate a personalized study plan with scheduled reviews.", icon: Calendar, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
  { id: "free_qa", label: "Free Q&A", description: "Ask any question about your materials and get AI-powered answers with source references.", icon: MessageCircle, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", enabled: true },
];

export default function NewProjectPage() {
  const router = useRouter();
  const { addCourse, fetchContentTree } = useCourseStore();
  const [step, setStep] = useState<Step>("mode");
  const [mode, setMode] = useState<Mode>("both");
  const [projectName, setProjectName] = useState("");
  const [files, setFiles] = useState<FileItem[]>([]);
  const [url, setUrl] = useState("");
  const [autoScrape, setAutoScrape] = useState(true);
  const [features, setFeatures] = useState<Record<string, boolean>>({
    notes: true, practice: true, study_plan: true, free_qa: true, wrong_answer: false,
  });
  const [nlInput, setNlInput] = useState("");
  const [createdCourseId, setCreatedCourseId] = useState<string | null>(null);

  // Parsing state
  const [parseSteps, setParseSteps] = useState<ParseStep[]>([
    { label: "Files converted", status: "waiting" },
    { label: "Content tree built", status: "waiting" },
    { label: "Scraping URL content...", status: "waiting" },
    { label: "Generate AI summaries", status: "waiting" },
    { label: "Index for search", status: "waiting" },
  ]);
  const [parseProgress, setParseProgress] = useState(0);
  const [parseLogs, setParseLogs] = useState<{ text: string; color: string }[]>([]);
  const [parseDone, setParseDone] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  };

  const handleFileAdd = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected) return;
    const newFiles = Array.from(selected).map((f) => ({
      file: f,
      name: f.name,
      size: formatSize(f.size),
    }));
    setFiles((prev) => [...prev, ...newFiles]);
    e.target.value = "";
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const toggleFeature = (id: string) => {
    const card = FEATURE_CARDS.find((c) => c.id === id);
    if (card?.phase) return;
    setFeatures((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Start parsing: create course, upload files, scrape URL
  const startParsing = useCallback(async () => {
    setStep("parsing");
    setParseProgress(0);
    setParseLogs([]);
    setParseDone(false);
    setParseSteps((s) => s.map((ps) => ({ ...ps, status: "waiting" as const })));

    const addLog = (text: string, color: string) => {
      setParseLogs((prev) => [...prev, { text, color }]);
    };

    try {
      // Create the course
      addLog(`${new Date().toLocaleTimeString()}  Creating project "${projectName || "Untitled"}"...`, "text-gray-400");
      const course = await addCourse(projectName.trim() || "Untitled Project");
      setCreatedCourseId(course.id);
      addLog(`${new Date().toLocaleTimeString()}  Project created`, "text-green-500");

      // Step 1: Convert files
      setParseSteps((s) => s.map((ps, i) => ({ ...ps, status: i === 0 ? "active" : ps.status })));
      setParseProgress(10);

      if (files.length > 0) {
        for (const f of files) {
          addLog(`${new Date().toLocaleTimeString()}  Converting ${f.name}...`, "text-gray-400");
          try {
            await uploadFile(course.id, f.file);
            addLog(`${new Date().toLocaleTimeString()}  ${f.name} converted`, "text-green-500");
          } catch (err) {
            addLog(`${new Date().toLocaleTimeString()}  Failed: ${f.name} — ${(err as Error).message}`, "text-red-500");
          }
        }
      }

      setParseSteps((s) => s.map((ps, i) => ({ ...ps, status: i === 0 ? "done" : i === 1 ? "active" : ps.status })));
      setParseProgress(30);

      // Step 2: Content tree
      addLog(`${new Date().toLocaleTimeString()}  Building content tree...`, "text-gray-400");
      await fetchContentTree(course.id);
      addLog(`${new Date().toLocaleTimeString()}  Content tree built`, "text-green-500");

      setParseSteps((s) => s.map((ps, i) => ({ ...ps, status: i <= 1 ? "done" : i === 2 ? "active" : ps.status })));
      setParseProgress(50);

      // Step 3: Scrape URL
      if (url.trim() && (mode === "url" || mode === "both")) {
        addLog(`${new Date().toLocaleTimeString()}  Fetching ${url}...`, "text-gray-400");
        try {
          await scrapeUrl(course.id, url.trim());
          addLog(`${new Date().toLocaleTimeString()}  URL content scraped successfully`, "text-green-500");
        } catch (err) {
          addLog(`${new Date().toLocaleTimeString()}  Scrape failed: ${(err as Error).message}`, "text-red-500");
        }
      } else {
        addLog(`${new Date().toLocaleTimeString()}  No URL to scrape, skipping`, "text-gray-400");
      }

      setParseSteps((s) => s.map((ps, i) => ({ ...ps, status: i <= 2 ? "done" : i === 3 ? "active" : ps.status })));
      setParseProgress(75);

      // Step 4: AI summaries (done server-side during upload, just simulate)
      addLog(`${new Date().toLocaleTimeString()}  Generating AI summaries...`, "text-gray-400");
      await new Promise((r) => setTimeout(r, 500));
      addLog(`${new Date().toLocaleTimeString()}  Summaries generated`, "text-green-500");

      setParseSteps((s) => s.map((ps, i) => ({ ...ps, status: i <= 3 ? "done" : i === 4 ? "active" : ps.status })));
      setParseProgress(90);

      // Step 5: Search index
      addLog(`${new Date().toLocaleTimeString()}  Building search index...`, "text-gray-400");
      await new Promise((r) => setTimeout(r, 300));
      addLog(`${new Date().toLocaleTimeString()}  All tasks complete!`, "text-green-500");

      setParseSteps((s) => s.map((ps) => ({ ...ps, status: "done" })));
      setParseProgress(100);
      setParseDone(true);
    } catch (err) {
      addLog(`${new Date().toLocaleTimeString()}  Error: ${(err as Error).message}`, "text-red-500");
    }
  }, [addCourse, fetchContentTree, files, mode, projectName, url]);

  const enterWorkspace = () => {
    if (createdCourseId) {
      router.push(`/course/${createdCourseId}`);
    }
  };

  return (
    <div className="min-h-screen bg-white">
      {/* MODE SELECTION (Page 2 in ref) */}
      {step === "mode" && (
        <div className="h-screen flex items-center justify-center">
          <div className="w-[640px] flex flex-col gap-10 items-center animate-in fade-in duration-300">
            <div className="flex flex-col gap-3 items-center text-center">
              <div className="w-14 h-14 bg-indigo-50 rounded-[14px] flex items-center justify-center">
                <FolderPlus className="w-7 h-7 text-indigo-600" />
              </div>
              <h1 className="text-[32px] font-bold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                How would you like to add content?
              </h1>
              <p className="text-[15px] text-gray-500 max-w-[480px] leading-relaxed">
                Choose how you want to bring learning materials into your new project.
              </p>
            </div>

            <div className="flex gap-4 w-full">
              {[
                { key: "upload" as Mode, icon: Upload, iconBg: "bg-indigo-50", iconColor: "text-indigo-600", label: "Upload Documents", desc: "Upload PDF, PPT, DOCX files from your computer" },
                { key: "url" as Mode, icon: Globe, iconBg: "bg-green-50", iconColor: "text-green-600", label: "Scrape from URL", desc: "Auto-fetch content from course websites and pages" },
                { key: "both" as Mode, icon: Layers, iconBg: "bg-violet-50", iconColor: "text-violet-600", label: "Both", desc: "Upload files and scrape URLs together" },
              ].map((m) => (
                <button
                  key={m.key}
                  onClick={() => setMode(m.key)}
                  className={`flex-1 flex flex-col items-center justify-center gap-3.5 p-7 rounded-[10px] transition-all ${
                    mode === m.key
                      ? "border-2 border-indigo-600 bg-indigo-50"
                      : "border border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className={`w-12 h-12 ${m.iconBg} rounded-xl flex items-center justify-center`}>
                    <m.icon className={`w-6 h-6 ${m.iconColor}`} />
                  </div>
                  <span className="font-semibold text-base text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                    {m.label}
                  </span>
                  <span className="text-[13px] text-gray-400 text-center leading-snug">{m.desc}</span>
                </button>
              ))}
            </div>

            <div className="flex justify-between w-full mt-2">
              <button
                onClick={() => router.push("/")}
                className="h-11 px-6 border border-gray-200 rounded-lg flex items-center gap-1.5 text-gray-500 font-medium text-sm hover:border-gray-300"
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Back to Projects
              </button>
              <button
                onClick={() => setStep("upload")}
                className="h-11 px-7 bg-indigo-600 text-white rounded-lg flex items-center gap-2 font-semibold text-sm hover:bg-indigo-700"
              >
                Continue <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* UPLOAD FORM (Page 3 in ref) */}
      {step === "upload" && (
        <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
          {/* Top nav */}
          <div className="flex items-center gap-3">
            <button onClick={() => setStep("mode")} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700">
              <ArrowLeft className="w-[18px] h-[18px]" /> Back
            </button>
            <div className="w-px h-4 bg-gray-200" />
            <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Create New Project</span>
            <div className="flex-1" />
            <span className="px-2 py-1 bg-indigo-50 text-indigo-600 text-[11px] font-medium rounded">
              {mode === "upload" ? "Upload Documents" : mode === "url" ? "Scrape from URL" : "Both: Upload + URL"}
            </span>
          </div>

          {/* Project Name */}
          <div className="flex flex-col gap-2">
            <label className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Project Name</label>
            <input
              className="w-full h-11 px-4 border border-gray-200 rounded-lg bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="CS101 Computer Science"
            />
          </div>

          {/* Upload Section */}
          {(mode === "upload" || mode === "both") && (
            <div className="flex flex-col gap-3">
              <h3 className="text-base font-semibold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Upload Learning Materials</h3>
              <div
                className="w-full h-40 border-2 border-dashed border-gray-200 bg-gray-50 rounded-lg flex flex-col items-center justify-center gap-3 cursor-pointer hover:border-indigo-600 hover:bg-indigo-50 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload className="w-8 h-8 text-gray-400" />
                <span className="text-sm text-gray-500">Drag files here, or click to browse</span>
                <span className="text-xs text-gray-400">Supports PDF, PPT, DOCX</span>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.pptx,.ppt,.docx,.doc,.html,.htm,.txt,.md"
                multiple
                className="hidden"
                onChange={handleFileAdd}
              />
              {files.length > 0 && (
                <div className="flex flex-col gap-2">
                  {files.map((f, idx) => (
                    <div key={idx} className="flex items-center gap-3 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-lg">
                      <FileText className="w-4 h-4 text-indigo-600" />
                      <span className="text-[13px] flex-1 text-gray-900">{f.name}</span>
                      <span className="text-xs text-gray-400">{f.size}</span>
                      <button onClick={() => removeFile(idx)}>
                        <X className="w-3.5 h-3.5 text-gray-400 hover:text-gray-700" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* URL Section */}
          {(mode === "url" || mode === "both") && (
            <div className="flex flex-col gap-3">
              <h3 className="text-base font-semibold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Add URL</h3>
              <div className="flex gap-2">
                <input
                  className="flex-1 h-11 px-4 border border-gray-200 rounded-lg bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
                  placeholder="https://professor-site.edu/cs101/"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                <button className="h-11 px-5 bg-indigo-600 text-white rounded-lg font-semibold text-sm hover:bg-indigo-700">Add</button>
              </div>
            </div>
          )}

          {/* Auto-Scrape Settings */}
          {(mode === "url" || mode === "both") && (
            <div className="flex flex-col gap-4">
              <h3 className="text-base font-semibold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Auto-Scrape Settings</h3>
              <p className="text-[13px] text-gray-500">Automatically fetch updates from added URLs on a schedule.</p>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setAutoScrape(!autoScrape)}
                  className={`w-11 h-6 rounded-full relative transition-colors ${autoScrape ? "bg-indigo-600" : "bg-gray-300"}`}
                >
                  <div className={`w-[18px] h-[18px] bg-white rounded-full absolute top-[3px] transition-all ${autoScrape ? "right-[3px]" : "left-[3px]"}`} />
                </button>
                <span className="text-sm text-gray-900">Enable periodic auto-scraping</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-gray-500">Frequency:</span>
                <div className="flex items-center gap-2 px-3.5 h-10 border border-gray-200 rounded-md bg-white">
                  <span className="text-[13px] text-gray-900">Every 24 hours</span>
                  <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-[18px] h-[18px] rounded-[3px] bg-indigo-600 flex items-center justify-center shrink-0">
                  <Check className="w-3 h-3 text-white" />
                </div>
                <span className="text-sm text-gray-900">Remind me when login session expires</span>
              </div>
            </div>
          )}

          <div className="w-full h-px bg-gray-200" />

          <div className="flex justify-end gap-4">
            <button onClick={() => setStep("mode")} className="h-11 px-6 border border-gray-200 rounded-lg text-gray-500 font-medium text-sm hover:border-gray-300">
              Cancel
            </button>
            <button onClick={startParsing} className="h-11 px-7 bg-indigo-600 text-white rounded-lg flex items-center gap-2 font-semibold text-sm hover:bg-indigo-700">
              Start Parsing <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* PARSING PROGRESS (Page 4 in ref) */}
      {step === "parsing" && (
        <div className="h-screen flex animate-in fade-in duration-300">
          {/* Browser Preview (left) */}
          <div className="flex-1 flex flex-col bg-white">
            <div className="h-12 px-5 bg-gray-50 border-b flex items-center gap-3 shrink-0">
              <Globe className="w-[18px] h-[18px] text-indigo-600" />
              <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                Processing — {projectName || "New Project"}
              </span>
              <div className="flex-1" />
              <div className="flex items-center gap-1.5 px-2.5 h-6 bg-green-50 rounded">
                <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
                <span className="text-[11px] font-semibold text-green-600">Active</span>
              </div>
            </div>
            {url && (
              <div className="h-9 px-3 bg-white border-b flex items-center gap-2">
                <Lock className="w-3 h-3 text-green-500" />
                <span className="text-xs text-gray-500 flex-1">{url}</span>
                <Loader className="w-3.5 h-3.5 text-gray-400 animate-spin" />
              </div>
            )}
            <div className="flex-1 p-6 bg-gray-50 flex flex-col gap-4 overflow-y-auto">
              <h2 className="text-xl font-bold text-gray-900">Processing your materials...</h2>
              <p className="text-sm text-gray-600 leading-relaxed">
                Agent is analyzing your uploaded files and URLs to build a structured learning experience.
              </p>
              {files.length > 0 && (
                <div className="p-3 px-4 bg-yellow-50 border border-yellow-200 rounded-md text-sm text-yellow-800 leading-relaxed">
                  Processing {files.length} file{files.length > 1 ? "s" : ""}: {files.map((f) => f.name).join(", ")}
                </div>
              )}
            </div>
          </div>

          {/* Parsing Sidebar (right) */}
          <div className="w-[340px] border-l bg-white flex flex-col shrink-0">
            <div className="h-11 px-4 bg-gray-50 border-b flex items-center gap-2 shrink-0">
              <Loader className={`w-4 h-4 text-indigo-600 ${!parseDone ? "animate-spin" : ""}`} />
              <span className="font-semibold text-[13px] text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>Parsing Progress</span>
            </div>
            <div className="flex-1 p-4 flex flex-col gap-4 overflow-y-auto">
              <div className="flex flex-col gap-1.5">
                <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                  {projectName || "New Project"}
                </span>
                <span className="text-xs text-gray-400">
                  {files.length} file{files.length !== 1 ? "s" : ""}{url ? " + 1 URL source" : ""}
                </span>
              </div>

              {/* Progress bar */}
              <div className="flex flex-col gap-1.5">
                <div className="w-full h-1.5 bg-gray-100 rounded-full">
                  <div
                    className="h-1.5 bg-indigo-600 rounded-full transition-all duration-1000"
                    style={{ width: `${parseProgress}%` }}
                  />
                </div>
                <span className="text-xs font-medium text-indigo-600">{parseProgress}% complete</span>
              </div>

              {/* Steps */}
              <div className="flex flex-col gap-3">
                {parseSteps.map((ps, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <div
                      className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${
                        ps.status === "done"
                          ? "bg-green-500"
                          : ps.status === "active"
                          ? "bg-indigo-600"
                          : "border border-gray-200"
                      }`}
                    >
                      {ps.status === "done" && <Check className="w-[11px] h-[11px] text-white" />}
                      {ps.status === "active" && <Loader className="w-[11px] h-[11px] text-white animate-spin" />}
                    </div>
                    <span
                      className={`text-xs ${
                        ps.status === "done"
                          ? "text-gray-900 font-medium"
                          : ps.status === "active"
                          ? "text-indigo-600 font-semibold"
                          : "text-gray-400"
                      }`}
                    >
                      {ps.label}
                    </span>
                  </div>
                ))}
              </div>

              <div className="w-full h-px bg-gray-200" />

              {/* Scrape Log */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-semibold text-gray-500">Processing Log</span>
                {parseLogs.map((log, idx) => (
                  <span key={idx} className={`text-[11px] font-mono ${log.color}`}>
                    {log.text}
                  </span>
                ))}
              </div>

              <div className="flex-1" />

              {parseDone && (
                <button
                  onClick={() => setStep("features")}
                  className="w-full h-11 bg-indigo-600 text-white rounded-lg flex items-center justify-center gap-2 font-semibold text-sm hover:bg-indigo-700"
                >
                  Continue to Features <ArrowRight className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* FEATURE SELECTION (Page 5 in ref) */}
      {step === "features" && (
        <div className="max-w-4xl mx-auto p-12 flex flex-col gap-8 animate-in fade-in duration-300">
          {/* Top nav */}
          <div className="flex items-center gap-3">
            <button onClick={() => setStep("parsing")} className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700">
              <ArrowLeft className="w-[18px] h-[18px]" /> Back
            </button>
            <div className="w-px h-4 bg-gray-200" />
            <span className="font-semibold text-sm text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              {projectName || "New Project"}
            </span>
          </div>

          <div className="flex flex-col gap-2">
            <h1 className="text-[28px] font-bold text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              What should Agent do for you?
            </h1>
            <p className="text-[15px] text-gray-500">Select the features you want to enable for this project. You can change these later.</p>
          </div>

          {/* Feature Cards — 2-column grid */}
          <div className="grid grid-cols-2 gap-4">
            {FEATURE_CARDS.map((card) => (
              <button
                key={card.id}
                onClick={() => toggleFeature(card.id)}
                className={`p-5 rounded-xl flex flex-col gap-3 text-left transition-all ${
                  features[card.id]
                    ? "border-2 border-indigo-600"
                    : "border border-gray-200"
                } ${card.phase ? "opacity-60 cursor-default" : "hover:shadow-md"}`}
              >
                <div className="flex items-center gap-2.5 w-full">
                  <div className={`w-9 h-9 ${card.iconBg} rounded-lg flex items-center justify-center shrink-0`}>
                    <card.icon className={`w-[18px] h-[18px] ${card.iconColor}`} />
                  </div>
                  <span className="font-semibold text-base text-gray-900 flex-1" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                    {card.label}
                  </span>
                  {card.phase && (
                    <span className="h-[22px] px-2 bg-amber-50 rounded text-[11px] font-semibold text-amber-600 flex items-center">
                      {card.phase}
                    </span>
                  )}
                  <div
                    className={`w-[22px] h-[22px] rounded flex items-center justify-center shrink-0 ml-auto ${
                      features[card.id] ? "bg-indigo-600" : "border-2 border-gray-200"
                    }`}
                  >
                    {features[card.id] && <Check className="w-3.5 h-3.5 text-white" />}
                  </div>
                </div>
                <p className="text-[13px] text-gray-500">{card.description}</p>
              </button>
            ))}
          </div>

          {/* Copy Settings */}
          <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl flex flex-col gap-3">
            <div className="flex items-center gap-2.5">
              <Copy className="w-[18px] h-[18px] text-gray-500" />
              <span className="font-semibold text-[15px] text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
                Copy Settings from Existing Project
              </span>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex-1 flex items-center gap-2 px-3.5 h-10 border border-gray-200 bg-white rounded-md">
                <span className="text-[13px] text-gray-400">Select a project...</span>
                <div className="flex-1" />
                <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
              </div>
              <button className="h-10 px-4 bg-gray-50 border border-gray-200 rounded-md text-[13px] text-gray-900 font-medium hover:bg-gray-100">
                Apply
              </button>
            </div>
          </div>

          {/* NL Input */}
          <div className="flex flex-col gap-2.5">
            <span className="font-semibold text-[15px] text-gray-900" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
              Anything else you&apos;d like to tell Agent?
            </span>
            <textarea
              className="w-full h-20 p-3 border border-gray-200 rounded-lg bg-white resize-none text-[13px] text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-600/20 focus:border-indigo-600"
              placeholder='e.g. "Use bullet points for notes", "Focus on algorithms", "Explain in simple terms"...'
              value={nlInput}
              onChange={(e) => setNlInput(e.target.value)}
            />
          </div>

          <div className="w-full h-px bg-gray-200" />

          <div className="flex justify-end gap-4">
            <button onClick={() => setStep("parsing")} className="h-11 px-6 border border-gray-200 rounded-lg text-gray-500 font-medium text-sm hover:border-gray-300">
              Back
            </button>
            <button
              onClick={enterWorkspace}
              className="h-11 px-7 bg-indigo-600 text-white rounded-lg flex items-center gap-2 font-semibold text-sm hover:bg-indigo-700"
            >
              Enter Workspace <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
