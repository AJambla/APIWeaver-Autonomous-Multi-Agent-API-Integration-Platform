from app.services.validation_service import StaticValidationResult
from app.services.verification_service import (
    OverallStatus,
    VerificationStatus,
    build_verification_report,
    render_report_markdown,
)


def test_build_verification_report_sandbox_verified():
    endpoints = [
        {"method": "GET", "path": "/pets", "summary": "List pets", "operation_id": "list_pets"},
        {"method": "DELETE", "path": "/pets/{id}", "summary": "Delete pet", "operation_id": "delete_pet"},
    ]
    test_results = [
        {"method": "GET", "path": "/pets", "status": "passed"},
        {"method": "DELETE", "path": "/pets/{id}", "status": "passed"},
    ]
    static_res = StaticValidationResult(
        is_valid=True,
        ast_syntax_valid=True,
        mcp_contract_valid=True,
        tool_count=2,
        tool_names=["list_pets", "delete_pet"],
    )

    report = build_verification_report(
        project_id="proj-12345",
        static_result=static_res,
        test_suite_results=test_results,
        endpoints=endpoints,
        repair_cycles=1,
    )

    assert report.static_status == VerificationStatus.PASS
    assert report.sandbox_status == VerificationStatus.PASS
    assert report.live_status == VerificationStatus.NOT_RUN
    assert report.overall_status == OverallStatus.SANDBOX_VERIFIED
    assert report.total_tools == 2
    assert report.passed_tools == 2
    assert report.failed_tools == 0

    # Verify tool inventory safety badges
    tools_dict = {t.tool_name: t for t in report.tools}
    assert tools_dict["list_pets"].safety_badge == "[SAFE]"
    assert tools_dict["list_pets"].requires_confirmation is False
    assert tools_dict["delete_pet"].safety_badge == "[DESTRUCTIVE ⚠]"
    assert tools_dict["delete_pet"].requires_confirmation is True

    # Render Markdown
    md = render_report_markdown(report)
    assert "Verification Status: STATIC: PASS | SANDBOX: PASS | LIVE: NOT RUN | Overall: SANDBOX VERIFIED" in md
    assert "## Tool Inventory & Safety Classification" in md
    assert "[DESTRUCTIVE ⚠]" in md
    assert "Yes ⚠" in md


def test_build_verification_report_static_failed():
    endpoints = [{"method": "GET", "path": "/pets", "operation_id": "list_pets"}]
    static_res = StaticValidationResult(
        is_valid=False,
        ast_syntax_valid=False,
        mcp_contract_valid=False,
        errors=["SyntaxError at line 10"],
    )

    report = build_verification_report(
        project_id="proj-fail",
        static_result=static_res,
        endpoints=endpoints,
    )

    assert report.static_status == VerificationStatus.FAIL
    assert report.overall_status == OverallStatus.UNVERIFIED


def test_build_verification_report_live_verified():
    endpoints = [{"method": "GET", "path": "/pets", "operation_id": "list_pets"}]
    report = build_verification_report(
        project_id="proj-live",
        endpoints=endpoints,
        live_tested=True,
        live_passed=True,
    )

    assert report.live_status == VerificationStatus.PASS
    assert report.overall_status == OverallStatus.LIVE_VERIFIED
