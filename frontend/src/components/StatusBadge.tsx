import { cn } from "@/lib/cn";

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-bg-tertiary text-text-secondary",
  planning: "bg-info/10 text-info",
  building: "bg-brand-accent/10 text-brand-accent",
  testing: "bg-warning/10 text-warning",
  ready: "bg-success/10 text-success",
  failed: "bg-error/10 text-error",
  completed: "bg-success/10 text-success",
  running: "bg-brand-accent/10 text-brand-accent",
  paused_for_approval: "bg-warning/10 text-warning",
};

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  planning: "Planning",
  building: "Building",
  testing: "Testing",
  ready: "Ready",
  failed: "Failed",
  completed: "Completed",
  running: "Running",
  paused_for_approval: "Awaiting Approval",
};

export function StatusBadge({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  const style = STATUS_STYLES[status] ?? "bg-bg-tertiary text-text-secondary";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        style,
      )}
    >
      <span
        aria-hidden="true"
        className={status === "failed" ? "✕" : status === "ready" || status === "completed" ? "✓" : "•"}
      />
      {label}
    </span>
  );
}
