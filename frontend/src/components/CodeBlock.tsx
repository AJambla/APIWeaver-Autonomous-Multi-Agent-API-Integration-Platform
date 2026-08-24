"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";

const MonacoEditor = dynamic(
  () => import("@monaco-editor/react").then((m) => m.Editor),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center bg-bg-tertiary text-sm text-text-secondary">
        Loading editor…
      </div>
    ),
  },
);

const MonacoDiffEditor = dynamic(
  () => import("@monaco-editor/react").then((m) => m.DiffEditor),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center bg-bg-tertiary text-sm text-text-secondary">
        Loading diff…
      </div>
    ),
  },
);

function useIsDark(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setDark(mq.matches);
    const handler = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return dark;
}

export function CodeBlock({
  code,
  language = "json",
  height = 320,
  readOnly = true,
}: {
  code: string;
  language?: string;
  height?: number;
  readOnly?: boolean;
}) {
  const dark = useIsDark();
  return (
    <div
      className="overflow-hidden rounded-md border border-border"
      style={{ height }}
    >
      <MonacoEditor
        height="100%"
        language={language}
        value={code}
        theme={dark ? "vs-dark" : "light"}
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 13,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          wordWrap: "on",
          renderLineHighlight: "none",
        }}
      />
    </div>
  );
}

export function CodeDiff({
  original,
  modified,
  language = "json",
  height = 360,
}: {
  original: string;
  modified: string;
  language?: string;
  height?: number;
}) {
  const dark = useIsDark();
  return (
    <div
      className="overflow-hidden rounded-md border border-border"
      style={{ height }}
    >
      <MonacoDiffEditor
        height="100%"
        language={language}
        original={original}
        modified={modified}
        theme={dark ? "vs-dark" : "light"}
        options={{
          readOnly: true,
          minimap: { enabled: false },
          fontSize: 13,
          scrollBeyondLastLine: false,
          automaticLayout: true,
          renderSideBySide: true,
          wordWrap: "on",
        }}
      />
    </div>
  );
}
