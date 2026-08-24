"use client";

import { Timeline } from "@/components/Timeline";
import { StatusBadge } from "@/components/StatusBadge";
import type { HistoryItem } from "@/lib/types";

function duration(item: HistoryItem): string {
  if (!item.started_at) return "—";
  const end = item.completed_at ? new Date(item.completed_at) : new Date();
  const mins = (end.getTime() - new Date(item.started_at).getTime()) / 60000;
  return mins > 0 ? `${mins.toFixed(1)} min` : "<1 min";
}

export function HistoryTimeline({ items }: { items: HistoryItem[] }) {
  const entries = items.map((item) => ({
    id: item.id,
    title: `Workflow Run`,
    subtitle: `${item.stages.length > 0 ? item.stages.join(" → ") : "full pipeline"}`,
    status: item.status,
    timestamp: item.started_at,
    meta: (
      <div className="flex flex-wrap gap-3 text-xs text-text-secondary">
        <span>Tokens: {item.total_tokens?.toLocaleString() ?? 0}</span>
        <span>Duration: {duration(item)}</span>
      </div>
    ),
  }));

  return <Timeline entries={entries} />;
}
