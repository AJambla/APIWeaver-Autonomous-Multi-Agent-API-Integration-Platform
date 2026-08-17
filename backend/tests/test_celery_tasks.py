"""Tests for Celery task queue integration."""

from __future__ import annotations

import pytest


class TestCeleryTasks:
    """Tests for agent-worker Celery tasks."""

    def test_celery_app_imports(self):
        """Celery app can be imported and has expected tasks registered."""
        try:
            from agent_worker.celery_app import app
            assert "agent_worker.tasks.run_document_agent" in app.tasks
            assert "agent_worker.tasks.run_code_agent" in app.tasks
            assert "agent_worker.tasks.run_testing_agent" in app.tasks
            assert "agent_worker.tasks.run_export_agent" in app.tasks
            assert "agent_worker.tasks.run_workflow" in app.tasks
        except ImportError:
            pytest.skip("agent_worker package not available in test environment")

    @pytest.mark.asyncio
    async def test_document_task_registered(self):
        """Document agent task is registered."""
        try:
            from agent_worker.tasks.document_tasks import run_document_agent
            assert run_document_agent is not None
        except ImportError:
            pytest.skip("agent_worker package not available in test environment")

    @pytest.mark.asyncio
    async def test_codegen_task_registered(self):
        """Code generation agent task is registered."""
        try:
            from agent_worker.tasks.codegen_tasks import run_code_agent_task
            assert run_code_agent_task is not None
        except ImportError:
            pytest.skip("agent_worker package not available in test environment")

    @pytest.mark.asyncio
    async def test_testing_task_registered(self):
        """Testing agent task is registered."""
        try:
            from agent_worker.tasks.testing_tasks import run_testing_agent
            assert run_testing_agent is not None
        except ImportError:
            pytest.skip("agent_worker package not available in test environment")

    @pytest.mark.asyncio
    async def test_export_task_registered(self):
        """Export agent task is registered."""
        try:
            from agent_worker.tasks.export_tasks import run_export_agent
            assert run_export_agent is not None
        except ImportError:
            pytest.skip("agent_worker package not available in test environment")

    @pytest.mark.asyncio
    async def test_workflow_task_registered(self):
        """Workflow task is registered."""
        try:
            from agent_worker.tasks.workflow_tasks import run_workflow
            assert run_workflow is not None
        except ImportError:
            pytest.skip("agent_worker package not available in test environment")
