"""Dedicated unit tests for workflow_input_service and test_run_service."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import RepairOutcome, TestResultStatus
from app.models.spec import APISpec, Endpoint
from app.models.testing import (
    RepairAttempt,
)
from app.models.testing import (
    TestResult as DBTestResult,
)
from app.models.testing import (
    TestRun as DBTestRun,
)
from app.models.workflow import WorkflowRun
from app.services.test_run_service import record_test_run_results
from app.services.workflow_input_service import (
    endpoint_labels,
    load_latest_test_results,
    load_normalized_spec,
)
from tests.conftest import make_org, make_project

# Prevent pytest from treating DB models/enums as test suites
DBTestRun.__test__ = False
DBTestResult.__test__ = False
TestResultStatus.__test__ = False


@pytest.mark.asyncio
async def test_endpoint_labels_mapping():
    """endpoint_labels correctly maps (METHOD, path) to endpoint UUIDs."""
    ep1_id = uuid.uuid4()
    ep2_id = uuid.uuid4()
    ep1 = Endpoint(id=ep1_id, method="get", path="/users")
    ep2 = Endpoint(id=ep2_id, method="POST", path="/users")

    labels = endpoint_labels([ep1, ep2])
    assert labels[("GET", "/users")] == ep1_id
    assert labels[("POST", "/users")] == ep2_id


@pytest.mark.asyncio
async def test_load_normalized_spec_empty_and_populated(db: AsyncSession):
    """load_normalized_spec returns None when no spec exists, and returns dict when spec exists."""
    unrelated_id = uuid.uuid4()
    assert await load_normalized_spec(db, unrelated_id) is None

    org = await make_org(db, name="Spec Org")
    project = await make_project(db, org=org, name="Test Spec Project")
    proj_id = project.id

    spec = APISpec(
        project_id=proj_id,
        title="Test API",
        raw_normalized={
            "title": "Test API",
            "endpoints": [
                {"path": "/ping", "method": "GET", "parameters": [], "request_schema": None}
            ],
        },
    )
    db.add(spec)
    await db.commit()

    loaded = await load_normalized_spec(db, proj_id)
    assert loaded is not None
    assert loaded["title"] == "Test API"


@pytest.mark.asyncio
async def test_record_test_run_results_and_load_latest(
    db: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
):
    """record_test_run_results persists test outcomes and load_latest_test_results retrieves them."""
    org = await make_org(db, name="Test Run Org")
    project = await make_project(db, org=org, name="Test Run Project")
    proj_id = project.id

    spec = APISpec(
        project_id=proj_id,
        title="Test API",
        raw_normalized={"title": "Test API"},
    )
    db.add(spec)
    await db.flush()

    ep_get = Endpoint(api_spec_id=spec.id, method="GET", path="/users")
    ep_post = Endpoint(api_spec_id=spec.id, method="POST", path="/users")
    db.add_all([ep_get, ep_post])

    wf_run_id = uuid.uuid4()
    wf_run = WorkflowRun(
        id=wf_run_id,
        project_id=proj_id,
        status="running",
    )
    db.add(wf_run)
    await db.commit()

    test_suite = [
        {
            "method": "GET",
            "path": "/users",
            "status": "passed",
            "status_code": 200,
            "latency_ms": 42.5,
            "response_snapshot": {"status_code": 200},
        },
        {
            "method": "POST",
            "path": "/users",
            "status": "failed",
            "status_code": 500,
            "error": "Server error",
            "response_snapshot": {"error": "Server error"},
        },
    ]

    repair_attempts = [
        {
            "method": "POST",
            "path": "/users",
            "attempt_number": 1,
            "classification": "server_error",
            "diff_summary": "patched payload",
            "target_file": "app/users.py",
            "error": "500",
        }
    ]

    await record_test_run_results(
        session_factory,
        workflow_run_id=wf_run_id,
        project_id=proj_id,
        test_suite=test_suite,
        status="completed",
        summary={"total": 2, "passed": 1, "failed": 1},
        repair_attempts=repair_attempts,
    )

    # Verify rows in DB
    async with session_factory() as s:
        run = await s.scalar(select(DBTestRun).where(DBTestRun.workflow_run_id == wf_run_id))
        assert run is not None
        assert run.status == "completed"

        results = list(
            (await s.scalars(select(DBTestResult).where(DBTestResult.test_run_id == run.id))).all()
        )
        assert len(results) == 2
        statuses = {r.status for r in results}
        assert TestResultStatus.PASSED.value in statuses
        assert TestResultStatus.FAILED.value in statuses

        repairs = list((await s.scalars(select(RepairAttempt))).all())
        assert len(repairs) == 1
        assert repairs[0].attempt_number == 1
        assert repairs[0].outcome == RepairOutcome.STILL_FAILING.value

    # Verify load_latest_test_results retrieves persisted results with matched endpoints
    async with session_factory() as s:
        loaded_suite, summary = await load_latest_test_results(s, proj_id)
        assert len(loaded_suite) == 2
        paths = {item["path"] for item in loaded_suite}
        assert "/users" in paths
        methods = {item["method"] for item in loaded_suite}
        assert "GET" in methods
        assert "POST" in methods
        assert summary == {"total": 2, "passed": 1, "failed": 1}
