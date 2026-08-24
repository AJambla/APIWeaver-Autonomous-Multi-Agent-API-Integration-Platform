"use client";

import { cn } from "@/lib/cn";
import { WORKFLOW_STAGES, type WorkflowStage } from "@/lib/types";

type StepState = "complete" | "active" | "pending" | "error";

function deriveStates(
  currentStage: WorkflowStage | null | undefined,
  status: string,
): Record<WorkflowStage, StepState> {
  const order = WORKFLOW_STAGES;
  const currentIndex = currentStage
    ? order.indexOf(currentStage)
    : status === "failed" || status === "cancelled"
      ? order.length - 1
      : -1;

  const states = {} as Record<WorkflowStage, StepState>;
  order.forEach((stage, i) => {
    if (status === "failed" || status === "cancelled") {
      states[stage] =
        i < currentIndex ? "complete" : i === currentIndex ? "error" : "pending";
    } else if (i < currentIndex) {
      states[stage] = "complete";
    } else if (i === currentIndex) {
      states[stage] = "active";
    } else {
      states[stage] = "pending";
    }
  });
  if (status === "completed") {
    order.forEach((stage) => (states[stage] = "complete"));
  }
  return states;
}

const STAGE_LABELS: Record<WorkflowStage, string> = {
  plan: "Plan",
  generate: "Generate",
  test: "Test",
  export: "Export",
};

export function ProgressStepper({
  currentStage,
  status,
}: {
  currentStage?: WorkflowStage | null;
  status?: string;
}) {
  const states = deriveStates(currentStage, status ?? "queued");
  const stages = WORKFLOW_STAGES;

  return (
    <ol className="flex flex-col gap-3 md:flex-row md:items-center">
      {stages.map((stage, i) => {
        const state = states[stage];
        return (
          <li key={stage} className="flex flex-1 items-center gap-3 md:flex-col md:text-center">
            <div className="flex items-center gap-3 md:flex-col">
              <span
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors",
                  state === "complete" &&
                    "border-success bg-success text-white",
                  state === "active" &&
                    "border-brand-primary bg-brand-primary text-white animate-pulse",
                  state === "error" && "border-error bg-error text-white",
                  state === "pending" &&
                    "border-border bg-bg-secondary text-text-secondary",
                )}
                aria-current={state === "active" ? "step" : undefined}
              >
                {state === "complete" ? "✓" : state === "error" ? "✕" : i + 1}
              </span>
              <div>
                <p
                  className={cn(
                    "text-sm font-medium",
                    state === "pending"
                      ? "text-text-secondary"
                      : "text-text-primary",
                  )}
                >
                  {STAGE_LABELS[stage]}
                </p>
              </div>
            </div>
            {i < stages.length - 1 && (
              <span
                className={cn(
                  "h-0.5 flex-1 md:mt-4 md:h-0.5 md:w-full",
                  states[stages[i + 1]] === "complete" ||
                    states[stages[i + 1]] === "active"
                    ? "bg-brand-primary"
                    : "bg-border",
                )}
                aria-hidden="true"
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
