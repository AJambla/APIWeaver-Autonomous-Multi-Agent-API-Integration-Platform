"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { ApiError } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { Card, CardTitle } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";

type UploadStatus = "idle" | "uploading" | "processing" | "done" | "error";

export default function UploadPage() {
  const params = useParams<{ id: string }>();
  const projectId = params.id;
  const router = useRouter();
  const { notify } = useToast();
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [message, setMessage] = useState("");
  const [format, setFormat] = useState<string | null>(null);
  const [workflowRunId, setWorkflowRunId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");

  const onFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setStatus("uploading");
    setMessage("Uploading document…");

    try {
      const form = new FormData();
      form.append("file", file);
      const res = await apiFetch<{
        document_id: string;
        api_spec_id?: string;
        status: string;
        workflow_run_id: string;
        endpoints_discovered?: number;
      }>(`/projects/${projectId}/upload`, {
        method: "POST",
        body: form as any,
      });
      setFormat(res.status === "processing" ? "openapi" : res.status);
      setWorkflowRunId(res.workflow_run_id);
      setStatus("processing");
      setMessage(`Parsing document… ${res.endpoints_discovered ?? 0} endpoints discovered`);
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof ApiError ? err.message : "Upload failed");
    }
  }, [projectId]);

  useEffect(() => {
    if (!workflowRunId || status !== "processing") return;
    const es = new EventSource(`/api/v1/workflows/${workflowRunId}/sse`);
    es.addEventListener("workflow.completed", () => {
      setStatus("done");
      setMessage("Upload complete. Ready to plan.");
      es.close();
    });
    es.addEventListener("workflow.failed", (ev) => {
      setStatus("error");
      setMessage((ev as any).detail ?? "Processing failed");
      es.close();
    });
    return () => es.close();
  }, [workflowRunId, status]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Upload API Documentation</h1>
        <p className="text-sm text-text-secondary">
          Upload an OpenAPI, Swagger, Postman, or freeform document to begin.
        </p>
      </div>

      <Card>
        <div
          className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-border p-10 text-center hover:border-brand-primary"
          onClick={() => fileRef.current?.click()}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".json,.yaml,.yml,.md,.pdf,.html,.txt"
            className="hidden"
            onChange={onFileChange}
          />
          {fileName ? (
            <p className="text-sm font-medium">{fileName}</p>
          ) : (
            <>
              <p className="text-sm font-medium">Drop a file here or click to browse</p>
              <p className="mt-1 text-xs text-text-secondary">
                OpenAPI 3.x, Swagger 2.0, Postman v2.1, Markdown, HTML, PDF
              </p>
            </>
          )}
        </div>
      </Card>

      {status !== "idle" && (
        <Card>
          <div className="flex items-center gap-3">
            <StatusBadge status={status === "error" ? "failed" : status === "done" ? "completed" : "running"} />
            <div>
              <p className="text-sm font-medium">{message}</p>
              {format && (
                <p className="text-xs text-text-secondary">Format: {format}</p>
              )}
            </div>
          </div>
          {status === "done" && (
            <div className="mt-4">
              <Button onClick={() => router.push(`/projects/${projectId}/plan`)}>
                Continue to Plan
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
