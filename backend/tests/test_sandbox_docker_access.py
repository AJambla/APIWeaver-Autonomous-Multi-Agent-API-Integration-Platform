from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.services.sandbox_service import DockerSandboxExecutor
from app.workflows.agents.test_agent import _build_sandbox_executor


def test_docker_socket_permission_error_diagnosed():
    settings = get_settings()
    executor = DockerSandboxExecutor(settings)
    with patch("docker.from_env", side_effect=PermissionError(13, "Permission denied")):
        with pytest.raises(PermissionError) as exc_info:
            executor._get_docker_client()
        assert "Permission denied" in str(exc_info.value)


def test_build_sandbox_executor_raises_when_docker_permission_denied():
    from app.core.errors import DependencyUnavailableError

    settings = get_settings()
    with patch("docker.from_env", side_effect=PermissionError(13, "Permission denied")):
        with pytest.raises(DependencyUnavailableError) as exc_info:
            _build_sandbox_executor(settings, network_enabled=False)
        assert "Docker sandbox daemon is unavailable" in str(exc_info.value)

