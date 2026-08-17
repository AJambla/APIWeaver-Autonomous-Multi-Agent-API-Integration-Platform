"""Tests for EventPublisher and real-time event endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.services.event_publisher import EventPublisher


class TestEventPublisher:
    """Unit tests for EventPublisher."""

    @pytest.fixture
    def mock_redis(self):
        redis = MagicMock()
        redis.xadd = AsyncMock()
        return redis

    @pytest.fixture
    def publisher(self, mock_redis):
        return EventPublisher(mock_redis)

    @pytest.mark.asyncio
    async def test_publish_writes_to_run_stream(self, publisher, mock_redis):
        await publisher.publish("run-1", "proj-1", "test.event", {"key": "value"})
        assert mock_redis.xadd.called
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "workflow_events:run-1"

    @pytest.mark.asyncio
    async def test_publish_writes_to_project_stream(self, publisher, mock_redis):
        await publisher.publish("run-1", "proj-1", "test.event", {"key": "value"})
        assert mock_redis.xadd.call_count == 2

    @pytest.mark.asyncio
    async def test_publish_skips_project_stream_when_no_project(self, publisher, mock_redis):
        await publisher.publish("run-1", None, "test.event", {"key": "value"})
        assert mock_redis.xadd.call_count == 1
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "workflow_events:run-1"

    @pytest.mark.asyncio
    async def test_publish_workflow_started(self, publisher, mock_redis):
        await publisher.publish_workflow_started("run-1", "proj-1", ["plan", "generate"])
        assert mock_redis.xadd.called
        payload = json.loads(mock_redis.xadd.call_args[0][1]["payload"])
        assert payload["event_type"] == "workflow.started"
        assert payload["progress_percent"] == 0

    @pytest.mark.asyncio
    async def test_publish_node_completed(self, publisher, mock_redis):
        await publisher.publish_node_completed("run-1", "proj-1", "doc_agent", {"status": "ok"})
        payload = json.loads(mock_redis.xadd.call_args[0][1]["payload"])
        assert payload["event_type"] == "node_completed"
        assert payload["node_name"] == "doc_agent"

    @pytest.mark.asyncio
    async def test_publish_workflow_completed(self, publisher, mock_redis):
        await publisher.publish_workflow_completed("run-1", "proj-1", "completed")
        payload = json.loads(mock_redis.xadd.call_args[0][1]["payload"])
        assert payload["event_type"] == "workflow.completed"
        assert payload["status"] == "completed"
        assert payload["progress_percent"] == 100

    @pytest.mark.asyncio
    async def test_publish_test_result(self, publisher, mock_redis):
        await publisher.publish_test_result("run-1", "proj-1", 10, 2, 1, 500)
        payload = json.loads(mock_redis.xadd.call_args[0][1]["payload"])
        assert payload["event_type"] == "test.result"
        assert payload["passed"] == 10
        assert payload["failed"] == 2

    @pytest.mark.asyncio
    async def test_publish_export_progress(self, publisher, mock_redis):
        await publisher.publish_export_progress("run-1", "proj-1", "github", "completed", 3)
        payload = json.loads(mock_redis.xadd.call_args[0][1]["payload"])
        assert payload["event_type"] == "export.progress"
        assert payload["export_type"] == "github"
        assert payload["artifact_count"] == 3

    @pytest.mark.asyncio
    async def test_publish_silent_on_redis_failure(self, publisher, mock_redis):
        mock_redis.xadd = AsyncMock(side_effect=Exception("Redis down"))
        await publisher.publish("run-1", "proj-1", "test.event", {})
        # Should not raise
        assert mock_redis.xadd.called


class TestEventsAPI:
    """Integration tests for event SSE endpoints."""

    @pytest.mark.asyncio
    async def test_sse_endpoint_returns_streaming_response(self, client, auth_headers):
        """SSE endpoint returns text/event-stream content type."""
        project_id, _, headers = await _setup_project(client)
        response = await client.post(
            f"/api/v1/projects/{project_id}/workflows",
            json={"stages": ["plan"], "target_languages": ["python"]},
            headers=headers,
        )
        assert response.status_code == 202
        run_id = response.json()["workflow_run_id"]

        sse_res = await client.get(
            f"/api/v1/workflows/{run_id}/sse",
            headers=headers,
        )
        assert sse_res.status_code == 200
        assert sse_res.headers["content-type"] == "text/event-stream; charset=utf-8"

    @pytest.mark.asyncio
    async def test_sse_endpoint_requires_auth(self, client):
        """SSE endpoint rejects unauthenticated requests."""
        response = await client.get("/api/v1/workflows/00000000-0000-0000-0000-000000000000/sse")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_sse_endpoint_rejects_missing_run(self, client, auth_headers):
        """SSE endpoint returns 404 for non-existent runs."""
        import uuid
        response = await client.get(
            f"/api/v1/workflows/{uuid.uuid4()}/sse",
            headers=auth_headers,
        )
        assert response.status_code == 404


async def _setup_project(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    from tests.conftest import TEST_PASSWORD
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "events_user@example.com",
            "password": TEST_PASSWORD,
            "full_name": "Events Tester",
            "organization_name": "Events Org",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    org_id = me.json()["organizations"][0]["organization_id"]

    proj = await client.post(
        "/api/v1/projects",
        json={"name": "Events Test Project", "organization_id": org_id},
        headers=headers,
    )
    assert proj.status_code == 201
    return proj.json()["id"], org_id, headers
