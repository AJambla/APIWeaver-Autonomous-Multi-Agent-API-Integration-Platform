"use client";

import { CodeDiff } from "@/components/CodeBlock";
import type { VersionItem } from "@/lib/types";

function versionText(v: VersionItem): string {
  return [
    `artifact_type: ${v.artifact_type}`,
    `version_number: ${v.version_number}`,
    `created_at: ${new Date(v.created_at).toISOString()}`,
    `is_active: ${v.is_active}`,
    `diff_ref: ${v.diff_ref ?? "null"}`,
  ].join("\n");
}

export function RunComparisonView({
  base,
  compare,
}: {
  base: VersionItem;
  compare: VersionItem;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-sm text-text-secondary">
        <span>
          <span className="font-mono">{base.artifact_type}</span> v{base.version_number}
        </span>
        <span aria-hidden>→</span>
        <span>
          <span className="font-mono">{compare.artifact_type}</span> v
          {compare.version_number}
        </span>
      </div>
      <CodeDiff
        original={versionText(base)}
        modified={versionText(compare)}
        language="yaml"
        height={360}
      />
    </div>
  );
}
