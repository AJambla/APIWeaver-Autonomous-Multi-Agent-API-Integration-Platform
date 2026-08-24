"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import type { DependencyEdge, DependencyGraph, DependencyNode } from "@/lib/types";

const METHOD_COLORS: Record<string, string> = {
  GET: "var(--color-info)",
  POST: "var(--color-success)",
  PUT: "var(--color-warning)",
  PATCH: "var(--color-warning)",
  DELETE: "var(--color-error)",
};

const RELATIONSHIP_LABEL: Record<string, string> = {
  requires_auth: "auth",
  requires_created_resource: "creates",
  optional_precedes: "precedes",
};

interface Pos {
  x: number;
  y: number;
}

/** Lightweight force-directed layout (no external dependency, SSR-safe). */
function layout(nodes: DependencyNode[], edges: DependencyEdge[], w: number, h: number): Record<string, Pos> {
  const pos: Record<string, Pos> = {};
  const n = nodes.length || 1;
  nodes.forEach((node, i) => {
    const angle = (i / n) * Math.PI * 2;
    const radius = Math.min(w, h) * 0.35;
    pos[node.id] = {
      x: w / 2 + Math.cos(angle) * radius,
      y: h / 2 + Math.sin(angle) * radius,
    };
  });

  const k = 0.04;
  const repulse = 6000;
  for (let iter = 0; iter < 200; iter++) {
    const disp: Record<string, Pos> = {};
    nodes.forEach((node) => (disp[node.id] = { x: 0, y: 0 }));

    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos[nodes[i].id];
        const b = pos[nodes[j].id];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = repulse / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        disp[nodes[i].id].x += fx;
        disp[nodes[i].id].y += fy;
        disp[nodes[j].id].x -= fx;
        disp[nodes[j].id].y -= fy;
      }
    }

    // Attraction along edges
    edges.forEach((e) => {
      const a = pos[e.from_id];
      const b = pos[e.to_id];
      if (!a || !b) return;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (dist - 120) * k;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      disp[e.from_id].x += fx;
      disp[e.from_id].y += fy;
      disp[e.to_id].x -= fx;
      disp[e.to_id].y -= fy;
    });

    nodes.forEach((node) => {
      const d = disp[node.id];
      const len = Math.sqrt(d.x * d.x + d.y * d.y) || 0.01;
      const limit = Math.min(len, 8);
      pos[node.id].x += (d.x / len) * limit;
      pos[node.id].y += (d.y / len) * limit;
      pos[node.id].x = Math.max(40, Math.min(w - 40, pos[node.id].x));
      pos[node.id].y = Math.max(40, Math.min(h - 40, pos[node.id].y));
    });
  }
  return pos;
}

export function DependencyGraphView({ graph }: { graph: DependencyGraph }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragging = useRef<{ x: number; y: number } | null>(null);

  const W = 800;
  const H = 480;

  const positions = useMemo(() => layout(graph.nodes, graph.edges, W, H), [graph]);

  const neighbors = useMemo(() => {
    const map: Record<string, Set<string>> = {};
    graph.nodes.forEach((n) => (map[n.id] = new Set()));
    graph.edges.forEach((e) => {
      map[e.from_id]?.add(e.to_id);
      map[e.to_id]?.add(e.from_id);
    });
    return map;
  }, [graph]);

  const isHighlighted = useCallback(
    (id: string) => {
      if (!selected) return true;
      return id === selected || neighbors[selected]?.has(id);
    },
    [selected, neighbors],
  );

  const isEdgeHighlighted = useCallback(
    (e: DependencyEdge) => {
      if (!selected) return true;
      return e.from_id === selected || e.to_id === selected;
    },
    [selected],
  );

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = -e.deltaY * 0.001;
    setTransform((t) => ({
      ...t,
      scale: Math.min(2.5, Math.max(0.4, t.scale + delta)),
    }));
  };

  const onMouseDown = (e: React.MouseEvent) => {
    if (e.target === svgRef.current) {
      dragging.current = { x: e.clientX - transform.x, y: e.clientY - transform.y };
    }
  };

  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current) return;
    setTransform((t) => ({
      ...t,
      x: e.clientX - dragging.current!.x,
      y: e.clientY - dragging.current!.y,
    }));
  };

  const onMouseUp = () => {
    dragging.current = null;
  };

  if (graph.nodes.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-border bg-bg-secondary text-sm text-text-secondary">
        No endpoints available to graph yet. Upload API docs to generate a spec.
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-lg border border-border bg-bg-secondary">
      <div className="absolute right-3 top-3 z-10 flex gap-1">
        <button
          className="rounded border border-border bg-bg-primary px-2 py-1 text-xs"
          onClick={() => setTransform((t) => ({ ...t, scale: Math.min(2.5, t.scale + 0.15) }))}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          className="rounded border border-border bg-bg-primary px-2 py-1 text-xs"
          onClick={() => setTransform((t) => ({ ...t, scale: Math.max(0.4, t.scale - 0.15) }))}
          aria-label="Zoom out"
        >
          −
        </button>
        <button
          className="rounded border border-border bg-bg-primary px-2 py-1 text-xs"
          onClick={() => {
            setTransform({ x: 0, y: 0, scale: 1 });
            setSelected(null);
          }}
          aria-label="Reset view"
        >
          ⟲
        </button>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="h-[480px] w-full cursor-grab touch-none"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
      >
        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
          {graph.edges.map((e, i) => {
            const a = positions[e.from_id];
            const b = positions[e.to_id];
            if (!a || !b) return null;
            const hi = isEdgeHighlighted(e);
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={hi ? "var(--color-brand-primary)" : "var(--color-border)"}
                strokeWidth={hi ? 2 : 1}
                strokeOpacity={hi ? 0.9 : 0.4}
                markerEnd="url(#arrow)"
              >
                <title>{RELATIONSHIP_LABEL[e.relationship] ?? e.relationship}</title>
              </line>
            );
          })}
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--color-border)" />
            </marker>
          </defs>
          {graph.nodes.map((node) => {
            const p = positions[node.id];
            const hi = isHighlighted(node.id);
            const color = METHOD_COLORS[node.method] ?? "var(--color-text-secondary)";
            return (
              <g
                key={node.id}
                transform={`translate(${p.x},${p.y})`}
                className="cursor-pointer"
                onClick={() => setSelected((s) => (s === node.id ? null : node.id))}
                style={{ opacity: hi ? 1 : 0.3 }}
              >
                <circle
                  r={node.is_destructive ? 14 : 12}
                  fill="var(--color-bg-primary)"
                  stroke={node.is_destructive ? "var(--color-error)" : color}
                  strokeWidth={node.is_destructive ? 3 : 2}
                />
                {node.is_destructive && (
                  <text textAnchor="middle" dy="4" fontSize="12" fill="var(--color-error)">
                    !
                  </text>
                )}
                <text
                  textAnchor="middle"
                  y={-20}
                  fontSize="10"
                  fill="var(--color-text-primary)"
                  className="font-mono"
                >
                  {node.method}
                </text>
                <text
                  textAnchor="middle"
                  y={28}
                  fontSize="9"
                  fill="var(--color-text-secondary)"
                  className="font-mono"
                >
                  {node.path.length > 22 ? node.path.slice(0, 21) + "…" : node.path}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-3 py-2 text-xs text-text-secondary">
        {Object.keys(METHOD_COLORS).map((m) => (
          <span key={m} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: METHOD_COLORS[m] }}
            />
            {m}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="inline-flex h-3 w-3 items-center justify-center rounded-full border-2 border-error text-[8px] text-error">
            !
          </span>
          Destructive
        </span>
      </div>
    </div>
  );
}
