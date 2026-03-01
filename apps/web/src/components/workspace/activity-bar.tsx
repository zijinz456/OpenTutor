"use client";

import { BrainCircuit, Home, FileText, Pencil, MessageCircle, BarChart2, Settings, Workflow } from "lucide-react";
import { useRouter } from "next/navigation";

interface ActivityBarProps {
  activeItem: string;
  onItemClick: (item: string) => void;
}

const TOP_ITEMS = [
  { id: "notes", icon: FileText, title: "Notes" },
  { id: "practice", icon: Pencil, title: "Practice" },
  { id: "chat", icon: MessageCircle, title: "Chat" },
  { id: "progress", icon: BarChart2, title: "Progress" },
  { id: "activity", icon: Workflow, title: "Activity" },
  { id: "profile", icon: BrainCircuit, title: "Profile" },
];

export function ActivityBar({ activeItem, onItemClick }: ActivityBarProps) {
  const router = useRouter();

  return (
    <div className="w-12 bg-[#1E1B4B] flex flex-col items-center py-3 gap-1 shrink-0">
      <button
        onClick={() => router.push("/")}
        className="w-10 h-10 rounded-lg flex items-center justify-center text-white/50 hover:text-white/80 transition-colors"
        title="Home"
      >
        <Home className="w-5 h-5" />
      </button>

      <div className="w-7 h-px bg-white/15 my-1" />

      {TOP_ITEMS.map((item) => (
        <button
          key={item.id}
          onClick={() => onItemClick(item.id)}
          className={`w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${
            activeItem === item.id
              ? "bg-white/15 text-white"
              : "text-white/50 hover:text-white/80"
          }`}
          title={item.title}
        >
          <item.icon className="w-5 h-5" />
        </button>
      ))}

      <div className="flex-1" />

      <button
        onClick={() => router.push("/settings")}
        className="w-10 h-10 rounded-lg flex items-center justify-center text-white/50 hover:text-white/80 transition-colors"
        title="Settings"
      >
        <Settings className="w-5 h-5" />
      </button>
    </div>
  );
}
