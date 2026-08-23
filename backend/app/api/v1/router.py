"""Aggregates the v1 routers.

URL-path versioning per `API.md §2` — breaking changes ship under `/api/v2`, so this
prefix is the version boundary.
"""

from fastapi import APIRouter, Depends

from app.api.v1 import (
    api_keys,
    auth,
    auth_config,
    dependency_graph,
    documents,
    events,
    export,
    generate,
    github,
    history,
    logs,
    monitoring,
    projects,
    spec_patch,
    testing,
    workflows,
)
from app.core.ratelimit import enforce_org_rate_limit

api_router = APIRouter(prefix="/api/v1")

# The auth router carries no org-tier limiter: `register`, `login`, and `refresh` are
# unauthenticated by definition, and that dependency resolves a principal. Those routes
# are covered by the per-IP `RateLimitMiddleware`, which is the layer that actually
# defends against credential stuffing (`Security.md §8`, A07).
api_router.include_router(auth.router)

# Everything below is authenticated, so it gets per-organization tier limiting
# (`API.md §3`) attached once here rather than repeated per route.
api_router.include_router(projects.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(documents.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(auth_config.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(workflows.router, dependencies=[Depends(enforce_org_rate_limit)])

api_router.include_router(generate.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(testing.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(export.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(github.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(events.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(api_keys.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(dependency_graph.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(history.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(logs.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(monitoring.router, dependencies=[Depends(enforce_org_rate_limit)])
api_router.include_router(spec_patch.router, dependencies=[Depends(enforce_org_rate_limit)])

