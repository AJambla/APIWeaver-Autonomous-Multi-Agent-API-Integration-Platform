"""Aggregates the v1 routers.

URL-path versioning per `API.md §2` — breaking changes ship under `/api/v2`, so this
prefix is the version boundary.
"""

from fastapi import APIRouter, Depends

from app.api.v1 import auth, documents, projects
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
