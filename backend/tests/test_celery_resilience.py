"""Unit tests for Celery redelivery idempotency and dead-letter publishing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agent_worker.celery_app import app
from agent_worker.tasks.base import AsyncTask, _send_dead_letter
from agent_worker.tasks.dlq_tasks import dead_letter_task


class RecordingTask(AsyncTask):
    name = "agent_worker.tests.recording"

    def __init__(self) -> None:
        super().__init__()
        self.executions = 0

    async def run_async(self, *args: Any, **kwargs: Any) -> Any:
        self.executions += 1
        return {"executions": self.executions, "args": args}


RecordingTask.bind(app)


def test_completed_task_redelivery_returns_cached_result(monkeypatch):
    monkeypatch.setattr(
        "celery.result.AsyncResult",
        lambda task_id, app=None: SimpleNamespace(state="SUCCESS", result={"cached": True}),
    )
    task = RecordingTask()
    task.push_request(id="redelivery-1")
    try:
        out = task.run("payload")
    finally:
        task.pop_request()

    assert out == {"cached": True}
    assert task.executions == 0


def test_uncompleted_task_executes_normally(monkeypatch):
    monkeypatch.setattr(
        "celery.result.AsyncResult",
        lambda task_id, app=None: SimpleNamespace(state="STARTED", result=None),
    )
    task = RecordingTask()
    task.push_request(id="redelivery-2")
    try:
        out = task.run("payload")
    finally:
        task.pop_request()

    assert out == {"executions": 1, "args": ("payload",)}
    assert task.executions == 1


def test_missing_request_id_executes_without_result_lookup(monkeypatch):
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("AsyncResult should not be consulted without a task id")

    monkeypatch.setattr("celery.result.AsyncResult", _boom)
    task = RecordingTask()

    out = task.run("payload")

    assert out == {"executions": 1, "args": ("payload",)}


def test_on_failure_publishes_dead_letter_record(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_send(app: Any, record: dict[str, Any]) -> None:
        captured["app"] = app
        captured["record"] = record

    monkeypatch.setattr("agent_worker.tasks.base._send_dead_letter", fake_send)
    task = RecordingTask()

    task.on_failure(ValueError("boom"), "task-123", (1, "two"), {"k": 1}, None)

    record = captured["record"]
    assert record["task"] == "agent_worker.tests.recording"
    assert record["task_id"] == "task-123"
    assert record["error"] == "ValueError: boom"
    assert "'two'" in record["args"]
    assert captured["app"] is task.app


def test_on_failure_swallows_publish_errors(monkeypatch):
    def broken_send(app: Any, record: dict[str, Any]) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr("agent_worker.tasks.base._send_dead_letter", broken_send)
    task = RecordingTask()

    task.on_failure(ValueError("boom"), "task-123", (), {}, None)


def test_send_dead_letter_targets_dlq_queue():
    captured: dict[str, Any] = {}

    def fake_send_task(name: str, args: Any = None, queue: str | None = None) -> None:
        captured.update(name=name, args=args, queue=queue)

    fake_app = SimpleNamespace(send_task=fake_send_task)
    record = {"task": "t", "task_id": "1"}

    _send_dead_letter(fake_app, record)

    assert captured["name"] == "agent_worker.tasks.dead_letter"
    assert captured["args"] == [record]
    assert captured["queue"] == "dlq"


def test_dead_letter_task_registered():
    assert "agent_worker.tasks.dead_letter" in app.tasks


def test_dead_letter_run_records():
    out = dead_letter_task.run(
        {"task": "t", "task_id": "1", "args": "()", "kwargs": "{}", "error": "E"}
    )

    assert out == {"recorded": True}


def test_dead_letter_failure_does_not_republish(monkeypatch):
    called: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "agent_worker.tasks.base._send_dead_letter",
        lambda app, record: called.append(record),
    )

    dead_letter_task.on_failure(ValueError("x"), "task-9", (), {}, None)

    assert called == []


def test_celery_conf_redelivery_settings():
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.task_routes["agent_worker.tasks.dead_letter"]["queue"] == "dlq"
    assert app.conf.broker_transport_options["visibility_timeout"] == 3600
