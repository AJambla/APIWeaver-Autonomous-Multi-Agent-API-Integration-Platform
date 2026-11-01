import pytest
from unittest.mock import patch, MagicMock
from app.services.sandbox_service import DockerSandboxExecutor, MockSandboxExecutor
from app.workflows.agents.test_agent import _build_sandbox_executor
from app.core.config import get_settings


def test_docker_socket_permission_error_diagnosed():
    settings = get_settings()
    executor = DockerSandboxExecutor(settings)
    with patch("docker.from_env", side_effect=PermissionError(13, "Permission denied")):
        with pytest.raises(PermissionError) as exc_info:
            executor._get_docker_client()
        assert "Permission denied" in str(exc_info.value)


def test_build_sandbox_executor_falls_back_when_docker_permission_denied(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    with patch("docker.from_env", side_effect=PermissionError(13, "Permission denied")):
        executor = _build_sandbox_executor(settings, network_enabled=False)
        assert isinstance(executor, MockSandboxExecutor)

