import { useEffect, useState } from "react";
import { refreshAccessToken, resolveEndpoint } from "./api";

export type WorkflowEvent = {
  event_type: string;
  payload: unknown;
  id: string;
};

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;
// A healthy stream carries an event or a heartbeat every few seconds.
const STALL_TIMEOUT_MS = 30000;

// Lifecycle events after which the run is over and the stream is left.
const TERMINAL_EVENT_TYPES = new Set(["workflow.completed", "workflow.failed", "workflow.cancelled"]);

// The plan gate pauses by publishing workflow.completed with a paused status;
// that is a hold, not an end — the same stream carries the resume.
const PAUSED_STATUS = "paused_for_approval";

export function isWorkflowTerminal(eventType: string, payload: unknown): boolean {
  if (!TERMINAL_EVENT_TYPES.has(eventType)) return false;
  const status = (payload as { status?: unknown } | null)?.status;
  return status !== PAUSED_STATUS;
}

type SseFrame = { event: string; data: string; id: string | null };

function parseFrame(block: string): SseFrame | null {
  let event = "message";
  const dataLines: string[] = [];
  let id: string | null = null;
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") dataLines.push(value);
    else if (field === "id") id = value;
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n"), id };
}

export function useWorkflowEvents(runId: string | null) {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    // Events belong to one run only; a stale terminal event from a previous
    // run must never finalize the next one.
    setEvents([]);
    setConnected(false);
    if (!runId) return;

    let cancelled = false;
    let finished = false;
    let attempt = 0;
    let lastEventId = "";
    let reconnectTimer: number | null = null;
    let stallTimer: number | null = null;
    let controller: AbortController | null = null;

    const clearStallTimer = () => {
      if (stallTimer !== null) {
        window.clearTimeout(stallTimer);
        stallTimer = null;
      }
    };

    type Outcome = "ended" | "retry" | "retry-now" | "stop";

    const connect = async (): Promise<Outcome> => {
      controller = new AbortController();
      // Rebuilt per attempt so a token refreshed mid-run is picked up.
      const { url, sameOrigin } = resolveEndpoint(`/workflows/${runId}/sse`);
      const headers = new Headers({ Accept: "text/event-stream" });
      if (lastEventId) headers.set("Last-Event-ID", lastEventId);
      const token = sessionStorage.getItem("access_token");
      if (token && sameOrigin) headers.set("Authorization", `Bearer ${token}`);
      const requestUrl = lastEventId
        ? `${url}${url.includes("?") ? "&" : "?"}last_event_id=${encodeURIComponent(lastEventId)}`
        : url;

      const armStallTimer = () => {
        clearStallTimer();
        stallTimer = window.setTimeout(() => controller?.abort(), STALL_TIMEOUT_MS);
      };

      try {
        armStallTimer();
        const response = await fetch(requestUrl, { headers, signal: controller.signal });
        if (response.status === 401) {
          // Throws (and redirects to /login) when the session is truly gone.
          await refreshAccessToken();
          return "retry-now";
        }
        // The run is gone or not ours: retrying every 15s forever helps nobody.
        if (response.status === 403 || response.status === 404) return "stop";
        if (!response.ok || !response.body) return "retry";
        attempt = 0;
        setConnected(true);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          armStallTimer();
          const { done, value } = await reader.read();
          if (done) break;
          buffer = (buffer + decoder.decode(value, { stream: true }))
            .replace(/\r\n/g, "\n")
            .replace(/\r/g, "\n");
          for (;;) {
            const sep = buffer.indexOf("\n\n");
            if (sep === -1) break;
            const block = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            const frame = parseFrame(block);
            if (!frame) continue;
            if (frame.id === "") lastEventId = "";
            else if (frame.id !== null) lastEventId = frame.id;
            let payload: unknown = null;
            try {
              payload = JSON.parse(frame.data);
            } catch {
              // A malformed body still leaves the event type and id usable.
            }
            setEvents((prev) => [...prev, { event_type: frame.event, payload, id: frame.id ?? "" }]);
            if (isWorkflowTerminal(frame.event, payload)) finished = true;
          }
          if (finished) break;
        }
        return finished ? "stop" : "ended";
      } catch {
        return cancelled || finished ? "stop" : "retry";
      } finally {
        clearStallTimer();
        controller.abort();
      }
    };

    const follow = async () => {
      for (;;) {
        if (cancelled || finished) break;
        const outcome = await connect();
        setConnected(false);
        if (cancelled || finished || outcome === "stop") break;
        if (outcome === "retry-now") {
          attempt = 0;
          continue;
        }
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
        attempt += 1;
        await new Promise<void>((resolve) => {
          reconnectTimer = window.setTimeout(resolve, delay);
        });
      }
    };
    follow();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      clearStallTimer();
      controller?.abort();
      setConnected(false);
    };
  }, [runId]);

  return { events, connected };
}
