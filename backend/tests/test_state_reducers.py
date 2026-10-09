"""Unit tests for LangGraph state reducers (S-02)."""

from __future__ import annotations

from app.workflows.state import (
    add_errors,
    merge_exports,
    merge_generated_files,
    merge_repair_attempts,
    merge_test_suite,
)


def test_merge_generated_files() -> None:
    left = [
        {"path": "client.py", "content": "class Client: pass"},
        {"path": "models.py", "content": "class User: pass"},
    ]
    right = [
        {"path": "client.py", "content": "class Client: def get(): pass"},
        {"path": "utils.py", "content": "def helper(): pass"},
    ]
    merged = merge_generated_files(left, right)
    assert len(merged) == 3
    by_path = {f["path"]: f["content"] for f in merged}
    assert by_path["client.py"] == "class Client: def get(): pass"
    assert by_path["models.py"] == "class User: pass"
    assert by_path["utils.py"] == "def helper(): pass"


def test_merge_generated_files_empty_cases() -> None:
    assert merge_generated_files(None, None) == []
    assert merge_generated_files([{"path": "a"}], None) == [{"path": "a"}]
    assert merge_generated_files(None, [{"path": "b"}]) == [{"path": "b"}]


def test_merge_repair_attempts() -> None:
    att1 = {"attempt_number": 1, "target_file": "client.py"}
    att2 = {"attempt_number": 2, "target_file": "client.py"}
    left = [att1]
    # Node already included left in its output list
    right = [att1, att2]
    merged = merge_repair_attempts(left, right)
    assert merged == [att1, att2]

    # Node returned only new attempt
    merged_single = merge_repair_attempts(left, [att2])
    assert merged_single == [att1, att2]


def test_merge_test_suite() -> None:
    left = [
        {"name": "test_auth", "status": "failed", "error": "401"},
        {"name": "test_users", "status": "passed"},
    ]
    right = [
        {"name": "test_auth", "status": "passed"},
        {"name": "test_billing", "status": "passed"},
    ]
    merged = merge_test_suite(left, right)
    assert len(merged) == 3
    by_name = {t["name"]: t["status"] for t in merged}
    assert by_name["test_auth"] == "passed"
    assert by_name["test_users"] == "passed"
    assert by_name["test_billing"] == "passed"


def test_merge_exports() -> None:
    left = [{"type": "python_package", "s3_key": "v1.tar.gz"}]
    right = [
        {"type": "python_package", "s3_key": "v2.tar.gz"},
        {"type": "docker", "s3_key": "image.tar"},
    ]
    merged = merge_exports(left, right)
    assert len(merged) == 2
    by_type = {e["type"]: e["s3_key"] for e in merged}
    assert by_type["python_package"] == "v2.tar.gz"
    assert by_type["docker"] == "image.tar"


def test_add_errors() -> None:
    left = ["Error 1"]
    right = ["Error 1", "Error 2"]
    merged = add_errors(left, right)
    assert merged == ["Error 1", "Error 2"]
