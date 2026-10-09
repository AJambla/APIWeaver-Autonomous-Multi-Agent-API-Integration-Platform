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
        # First call writes to the run stream, with event_type as a sibling field.
        first_call = mock_redis.xadd.call_args_list[0]
        assert first_call[0][0] == "workflow_events:run-1"
        message = first_call[0][1]
        assert message["event_type"] == "test.event"
        assert json.loads(message["payload"]) == {"key": "value"}

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
        message = mock_redis.xadd.call_args[0][1]
        assert message["event_type"] == "workflow.started"
        payload = json.loads(message["payload"])
        assert payload["progress_percent"] == 0
        assert payload["stages"] == ["plan", "generate"]

    @pytest.mark.asyncio
    async def test_publish_node_completed(self, publisher, mock_redis):
        await publisher.publish_node_completed("run-1", "proj-1", "doc_agent", {"status": "ok"})
        message = mock_redis.xadd.call_args[0][1]
        assert message["event_type"] == "node_completed"
        payload = json.loads(message["payload"])
        assert payload["node_name"] == "doc_agent"
        assert payload["output_summary"] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_publish_workflow_completed(self, publisher, mock_redis):
        await publisher.publish_workflow_completed("run-1", "proj-1", "completed")
        message = mock_redis.xadd.call_args[0][1]
        assert message["event_type"] == "workflow.completed"
        payload = json.loads(message["payload"])
        assert payload["status"] == "completed"
        assert payload["progress_percent"] == 100

    @pytest.mark.asyncio
    async def test_publish_test_result(self, publisher, mock_redis):
        await publisher.publish_test_result("run-1", "proj-1", 10, 2, 1, 500)
        message = mock_redis.xadd.call_args[0][1]
        assert message["event_type"] == "test.result"
        payload = json.loads(message["payload"])
        assert payload["passed"] == 10
        assert payload["failed"] == 2

    @pytest.mark.asyncio
    async def test_publish_export_progress(self, publisher, mock_redis):
        await publisher.publish_export_progress("run-1", "proj-1", "github", "completed", 3)
        message = mock_redis.xadd.call_args[0][1]
        assert message["event_type"] == "export.progress"
        payload = json.loads(message["payload"])
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
    async def test_sse_endpoint_returns_streaming_response(
        self, client, auth_headers, monkeypatch
    ):
        """SSE endpoint returns text/event-stream content type."""
        # The real generator polls Redis forever; ASGITransport only returns the
        # response once the app completes, so an unpatched stream would hang the
        # client indefinitely. Substitute a finite stream to exercise the full
        # HTTP path (auth, run access, media type, SSE framing) and terminate.
        from app.api.v1 import events as events_module

        async def finite_stream(*args, **kwargs):
            yield "event: workflow.started\ndata: {}\n\n"

        monkeypatch.setattr(events_module, "_stream_redis_events", finite_stream)

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
        assert sse_res.text.startswith("event: ")

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


class _EmptyStream:
    """xread that never has anything new (an expired or fully-read stream)."""

    def __init__(self) -> None:
        self.reads: list[dict] = []

    async def xread(self, streams, block=None, count=None):
        self.reads.append(dict(streams))
        return []


async def _collect(gen, limit: int = 5) -> list[str]:
    out = []
    async for chunk in gen:
        out.append(chunk)
        if len(out) >= limit:
            break
    return out


@pytest.mark.asyncio
async def test_a_finished_run_with_nothing_to_replay_ends_with_a_terminal_event():
    """An expired stream for a finished run used to heartbeat forever."""
    from app.api.v1.events import _stream_redis_events

    chunks = await _collect(
        _stream_redis_events(_EmptyStream(), "workflow_events:x", "0-0", block_ms=1, finished_status="failed")
    )
    assert len(chunks) == 1
    assert chunks[0].startswith("event: workflow.failed\n")
    assert '"status": "failed"' in chunks[0]


@pytest.mark.asyncio
async def test_a_live_run_heartbeats_and_streams_close_at_their_lifetime():
    from app.api.v1.events import _stream_redis_events

    live = await _collect(_stream_redis_events(_EmptyStream(), "k", "0-0", block_ms=1), limit=2)
    assert live == [": heartbeat\n\n", ": heartbeat\n\n"]

    expired = await _collect(_stream_redis_events(_EmptyStream(), "k", "0-0", block_ms=1, max_seconds=-1))
    assert expired == []


@pytest.mark.asyncio
async def test_sse_rejects_a_malformed_last_event_id_and_uses_the_canonical_stream_key(
    client, monkeypatch
):
    from app.api.v1 import events as events_module

    keys: list[str] = []

    async def capture(redis_client, stream_key, last_id, *args, **kwargs):
        keys.append(stream_key)
        yield ": heartbeat\n\n"

    monkeypatch.setattr(events_module, "_stream_redis_events", capture)
    project_id, _, headers = await _setup_project(client)
    run = await client.post(
        f"/api/v1/projects/{project_id}/workflows",
        json={"stages": ["plan"], "target_languages": ["python"]},
        headers=headers,
    )
    run_id = run.json()["workflow_run_id"]

    bad = await client.get(f"/api/v1/workflows/{run_id}/sse?last_event_id=bogus", headers=headers)
    assert bad.status_code in (400, 422), bad.text

    ok = await client.get(f"/api/v1/workflows/{run_id.upper()}/sse", headers=headers)
    assert ok.status_code == 200, ok.text
    assert keys == [f"workflow_events:{run_id}"]
