"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";

export interface TabItem {
  id: string;
  label: string;
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabItem[];
  active?: string;
  onChange: (id: string) => void;
}) {
  const [internal, setInternal] = useState(tabs[0]?.id);
  const current = active ?? internal;

  return (
    <div className="border-b border-border">
      <div className="flex gap-1" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={current === tab.id}
            className={cn(
              "border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              current === tab.id
                ? "border-brand-primary text-text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary",
            )}
            onClick={() => {
              setInternal(tab.id);
              onChange(tab.id);
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  );
}
