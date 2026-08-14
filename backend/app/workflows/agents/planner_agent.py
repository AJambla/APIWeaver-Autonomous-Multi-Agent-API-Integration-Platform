"""Planner Agent (`AI_Instruction.md §1, §2.2`, `Feature.md §4, §5`).

Builds dependency graphs, endpoint clusters, and an ordered execution plan with risk assessment.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger
from app.workflows.llm import LLMClient
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

    endpoints = spec.get("endpoints", [])

    # Algorithmic baseline clustering & dependency extraction
    nodes: list[dict[str, Any]] = []
    destructive: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for idx, ep in enumerate(endpoints):
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")
        ep_id = f"ep_{idx}"
        nodes.append({"id": ep_id, "label": f"{method} {path}"})
        if method == "DELETE":
            destructive.append({"method": method, "path": path, "auto_test_safe": False})

    # Prepare LLM fallback plan
    fallback_plan = {
        "summary": f"Execution plan for {spec.get('title', 'API')} ({len(endpoints)} endpoints)",
        "resource_groups": [
            {
                "name": "Default Group",
                "endpoints": [f"{ep.get('method')} {ep.get('path')}" for ep in endpoints],
            }
        ],
        "phases": [
            {
                "phase_number": 1,
                "name": "All Endpoints",
                "endpoints": [f"{ep.get('method')} {ep.get('path')}" for ep in endpoints],
            }
        ],
        "dependency_graph": {
            "nodes": nodes,
            "edges": edges,
        },
        "destructive_endpoints": destructive,
    }

    user_prompt = f"Normalized API Spec:\n{json.dumps(spec, indent=2)[:8000]}"
    plan_json, tokens = await client.generate_json(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        fallback_json=fallback_plan,
    )
    total_tokens += tokens

    return {
        "execution_plan": plan_json,
        "current_node": "planner_agent",
        "progress_percent": 50,
        "status": "plan_ready",
        "total_tokens_used": total_tokens,
    }
