"use client";

import { ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbsBarProps {
  items: BreadcrumbItem[];
}

export function BreadcrumbsBar({ items }: BreadcrumbsBarProps) {
  const router = useRouter();

  return (
    <div className="h-9 px-4 bg-gray-50 border-b flex items-center gap-2 shrink-0">
      {items.map((item, idx) => (
        <span key={idx} className="flex items-center gap-2">
          {idx > 0 && <ChevronRight className="w-3 h-3 text-gray-400" />}
          {item.href ? (
            <button
              onClick={() => router.push(item.href!)}
              className="text-xs font-medium text-indigo-600 hover:underline cursor-pointer"
            >
              {item.label}
            </button>
          ) : (
            <span className="text-xs text-gray-500">{item.label}</span>
          )}
        </span>
      ))}
    </div>
  );
}
