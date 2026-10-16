"""Planner Agent (`AI_Instruction.md §1, §2.2`, `Feature.md §4, §5`).

Builds dependency graphs, endpoint clusters, and an ordered execution plan with risk assessment.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.workflows.llm import LLMClient, fence_untrusted
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

PLANNER_SYSTEM_PROMPT = """You are the Planner Agent.
You receive a normalized API spec and must produce an execution plan:
an ordered list of build phases, a dependency graph between endpoints,
and a risk assessment for destructive operations.

Rules:
- Never mark an endpoint as safe-to-auto-test if it is a DELETE or has no
  documented idempotency guarantee, unless explicitly whitelisted by the user.
- Group endpoints into logical resource clusters (e.g., "Orders", "Customers", "Auth").
- Order phases so that prerequisite endpoints (auth, resource creation) are
  scheduled before dependent endpoints.

Output JSON matching this schema:
{
  "summary": "Integration build plan for...",
  "resource_groups": [
    {
      "name": "Authentication",
      "endpoints": ["POST /oauth/token"]
    },
    {
      "name": "Users",
      "endpoints": ["GET /users", "POST /users", "GET /users/{id}"]
    }
  ],
  "phases": [
    {
      "phase_number": 1,
      "name": "Auth and Core Resources",
      "endpoints": ["POST /oauth/token", "POST /users"]
    },
    {
      "phase_number": 2,
      "name": "Resource Operations",
      "endpoints": ["GET /users", "GET /users/{id}"]
    }
  ],
  "dependency_graph": {
    "nodes": [
      {"id": "ep_1", "label": "POST /users"}
    ],
    "edges": [
      {"from": "ep_1", "to": "ep_2", "relationship": "requires_created_resource"}
    ]
  },
  "destructive_endpoints": [
    {"method": "DELETE", "path": "/users/{id}", "auto_test_safe": false}
  ]
}
"""


def _generate_deterministic_plan(spec: dict[str, Any]) -> dict[str, Any]:
    """Generates a topological execution plan and DAG algorithmically if LLM is unavailable."""
    endpoints = spec.get("endpoints", [])
    title = spec.get("title", "API")

    resource_map: dict[str, list[str]] = {}
    phase1_eps: list[str] = []
    phase2_eps: list[str] = []
    phase3_eps: list[str] = []
    nodes: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []
    destructive: list[dict[str, Any]] = []

    for idx, ep in enumerate(endpoints):
        method = str(ep.get("method", "GET")).upper()
        path = str(ep.get("path", "/"))
        ep_str = f"{method} {path}"
        ep_id = f"ep_{idx}"
        nodes.append({"id": ep_id, "label": ep_str})

        parts = [p for p in path.split("/") if p and not p.startswith("{")]
        resource = parts[0].capitalize() if parts else "Core"
        resource_map.setdefault(resource, []).append(ep_str)

        if method == "DELETE":
            destructive.append({"method": method, "path": path, "auto_test_safe": False})
            phase3_eps.append(ep_str)
        elif method in ("POST", "PUT") and any(k in path.lower() for k in ("auth", "token", "login")):
            phase1_eps.insert(0, ep_str)
        elif method in ("POST", "PUT"):
            phase1_eps.append(ep_str)
        elif method == "GET":
            phase2_eps.append(ep_str)
        else:
            phase3_eps.append(ep_str)

    post_nodes = {n["label"].split()[1]: n["id"] for n in nodes if n["label"].startswith("POST")}
    for n in nodes:
        method, _, path = n["label"].partition(" ")
        if method in ("GET", "DELETE") and path in post_nodes:
            edges.append({
                "from": post_nodes[path],
                "to": n["id"],
                "relationship": "requires_created_resource" if method == "GET" else "cleans_up_resource"
            })

    phases = []
    if phase1_eps:
        phases.append({
            "phase_number": 1,
            "name": "Core Resources & Creation",
            "endpoints": phase1_eps,
        })
    if phase2_eps:
        phases.append({
            "phase_number": len(phases) + 1,
            "name": "Resource Operations & Queries",
            "endpoints": phase2_eps,
        })
    if phase3_eps:
        phases.append({
            "phase_number": len(phases) + 1,
            "name": "Destructive & Cleanup Operations",
            "endpoints": phase3_eps,
        })
    if not phases:
        phases.append({
            "phase_number": 1,
            "name": "All Endpoints",
            "endpoints": [n["label"] for n in nodes],
        })

    resource_groups = [{"name": name, "endpoints": eps} for name, eps in resource_map.items()]

    return {
        "summary": f"Deterministic execution and DAG plan for {title} (algorithmic fallback)",
        "resource_groups": resource_groups,
        "phases": phases,
        "dependency_graph": {
            "nodes": nodes,
            "edges": edges,
        },
        "destructive_endpoints": destructive,
    }


async def run_planner_agent(
    state: WorkflowState,
    llm_client: LLMClient | None = None,
) -> dict[str, Any]:
    """Execution node for the Planner Agent."""
    logger.info("planner_agent_started", workflow_run_id=state.get("workflow_run_id"))
    client = llm_client or LLMClient()
    total_tokens = state.get("total_tokens_used", 0)

    spec = state.get("normalized_spec")
    if not spec:
        return {
            "current_node": "planner_agent",
            "progress_percent": 50,
            "status": "failed",
            "errors": ["Cannot plan without a normalized API spec."],
        }

    plan_json: dict[str, Any]
    try:
        user_prompt = fence_untrusted("SPEC DATA", json.dumps(spec, indent=2)[:100000])
        plan_json, tokens = await client.generate_json(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        total_tokens += tokens
    except Exception as exc:
        logger.warning(
            "planner_llm_failed_using_deterministic_baseline",
            error=str(exc),
            workflow_run_id=state.get("workflow_run_id"),
        )
        plan_json = _generate_deterministic_plan(spec)

    return {
        "execution_plan": plan_json,
        "current_node": "planner_agent",
        "progress_percent": 50,
        "status": "plan_ready",
        "total_tokens_used": total_tokens,
    }
