import { useEffect, useRef, useState } from "react";

export type WorkflowEvent = {
  event_type: string;
  payload: any;
  id: string;
};

export function useWorkflowEvents(runId: string | null) {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`/api/v1/workflows/${runId}/sse`);
    esRef.current = es;

    es.addEventListener("open", () => setConnected(true));
    es.addEventListener("error", () => setConnected(false));

    const handler = (ev: MessageEvent) => {
      setEvents((prev) => [...prev, { event_type: ev.type, payload: JSON.parse(ev.data), id: ev.lastEventId ?? "" }]);
    };
    es.addEventListener("message", handler);
    es.addEventListener("workflow.progress", handler);
    es.addEventListener("node_completed", handler);
    es.addEventListener("workflow.completed", handler);
    es.addEventListener("workflow.failed", handler);
    es.addEventListener("test.result", handler);
    es.addEventListener("repair.attempt", handler);
    es.addEventListener("export.progress", handler);

    return () => {
      es.removeEventListener("message", handler);
      es.removeEventListener("workflow.progress", handler);
      es.removeEventListener("node_completed", handler);
      es.removeEventListener("workflow.completed", handler);
      es.removeEventListener("workflow.failed", handler);
      es.removeEventListener("test.result", handler);
      es.removeEventListener("repair.attempt", handler);
      es.removeEventListener("export.progress", handler);
      es.close();
      setConnected(false);
    };
  }, [runId]);

  return { events, connected };
}
