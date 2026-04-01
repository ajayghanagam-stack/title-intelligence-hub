"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface EntitySectionProps {
  title: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  badge?: string;
}

export function EntitySection({
  title,
  icon,
  defaultOpen = true,
  children,
  badge,
}: EntitySectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="card-warm overflow-hidden">
      {/* Header bar */}
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className={cn(
          "flex w-full items-center gap-3 px-4 py-3",
          "bg-gradient-to-r from-amber-50 to-amber-100/60",
          "border-b border-amber-200/40",
          "text-left transition-colors hover:from-amber-100 hover:to-amber-100/80"
        )}
      >
        {icon && (
          <span className="flex h-6 w-6 items-center justify-center text-amber-700">
            {icon}
          </span>
        )}
        <span className="flex-1 text-sm font-semibold text-amber-900">
          {title}
        </span>
        {badge && (
          <span className="rounded-full bg-amber-200/70 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
            {badge}
          </span>
        )}
        <ChevronDown
          className={cn(
            "h-4 w-4 text-amber-600 transition-transform duration-200",
            isOpen ? "rotate-0" : "-rotate-90"
          )}
        />
      </button>

      {/* Collapsible content */}
      <div
        className={cn(
          "transition-all duration-200 ease-in-out overflow-hidden",
          isOpen ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0"
        )}
      >
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
