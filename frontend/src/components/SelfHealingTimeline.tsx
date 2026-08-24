"use client";

import { CodeBlock, CodeDiff } from "@/components/CodeBlock";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/cn";
import type { RepairAttempt } from "@/lib/types";

function RepairDiff({ diff }: { diff: Record<string, any> | null }) {
  if (!diff) {
    return <p className="text-xs text-text-secondary">No diff recorded.</p>;
  }
  const original = typeof diff.original === "string" ? diff.original : null;
  const modified = typeof diff.modified === "string" ? diff.modified : null;

  if (original !== null && modified !== null) {
    return <CodeDiff original={original} modified={modified} height={240} />;
  }
  return <CodeBlock code={JSON.stringify(diff, null, 2)} height={200} />;
}

export function SelfHealingTimeline({
  repairs,
  testResultId,
}: {
  repairs: RepairAttempt[];
  testResultId?: string | null;
}) {
  const relevant = repairs.filter(
    (r) => testResultId == null || r.test_result_id === testResultId,
  );

  if (relevant.length === 0) {
    return (
      <p className="text-xs text-text-secondary">No self-healing attempts for this test.</p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-text-secondary">Self-Healing Attempts</p>
      <ol className="relative space-y-3 border-l border-border pl-4">
        {relevant.map((r) => {
          const failed = r.outcome === "failed" || r.outcome == null;
          return (
            <li key={r.id} className="relative">
              <span
                className={cn(
                  "absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-bg-primary",
                  failed ? "bg-warning" : "bg-success",
                )}
                aria-hidden="true"
              />
              <details className="rounded-md border border-border bg-bg-secondary">
                <summary className="flex cursor-pointer items-center justify-between px-3 py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="font-medium">Attempt #{r.attempt_number}</span>
                    {r.failure_classification && (
                      <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-xs text-text-secondary">
                        {r.failure_classification}
                      </span>
                    )}
                  </span>
                  <StatusBadge status={r.outcome ?? "unknown"} />
                </summary>
                <div className="border-t border-border px-3 py-2">
                  <RepairDiff diff={r.diff_summary} />
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
