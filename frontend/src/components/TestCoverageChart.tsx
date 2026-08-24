"use client";

import { DonutChart } from "@/components/charts";
import { CHART_COLORS } from "@/components/charts";

export function TestCoverageChart({
  passed,
  failed,
  skipped,
}: {
  passed: number;
  failed: number;
  skipped: number;
}) {
  const data = [
    { name: "Passed", value: passed, color: CHART_COLORS.success },
    { name: "Failed", value: failed, color: CHART_COLORS.error },
    { name: "Skipped", value: skipped, color: CHART_COLORS.warning },
  ].filter((d) => d.value > 0);

  const total = passed + failed + skipped;

  if (total === 0) {
    return (
      <div className="flex h-[220px] items-center justify-center text-sm text-text-secondary">
        No coverage data yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center">
      <DonutChart data={data} centerLabel={String(total)} />
      <div className="mt-2 flex flex-wrap justify-center gap-3 text-xs">
        {data.map((d) => (
          <span key={d.name} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: d.color }}
            />
            {d.name}: {d.value}
          </span>
        ))}
      </div>
    </div>
  );
}
