"""Pre-Sandbox Static Validation Gate for FastMCP Tools (Blueprint §5).

Validates generated Python code and FastMCP tool definitions statically using AST
before container execution, preventing syntax errors and invalid schemas from
wasting Docker execution cycles.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StaticValidationResult:
    is_valid: bool
    ast_syntax_valid: bool
    mcp_contract_valid: bool
    tool_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_mcp_code_statically(
    code: str,
    file_path: str = "tools.py",
) -> StaticValidationResult:
    """Statically validate Python code and FastMCP tool contracts before sandbox execution."""
    if not code or not code.strip():
        return StaticValidationResult(
            is_valid=False,
            ast_syntax_valid=False,
            mcp_contract_valid=False,
            errors=["Code content is empty."],
        )

    # 1. AST Syntax Parse Gate
    try:
        tree = ast.parse(code, filename=file_path)
    except SyntaxError as exc:
        line = exc.lineno or 0
        offset = exc.offset or 0
        msg = exc.msg or "Invalid syntax"
        err_msg = f"SyntaxError in {file_path} at line {line}:{offset}: {msg}"
        return StaticValidationResult(
            is_valid=False,
            ast_syntax_valid=False,
            mcp_contract_valid=False,
            errors=[err_msg],
        )
    except Exception as exc:
        return StaticValidationResult(
            is_valid=False,
            ast_syntax_valid=False,
            mcp_contract_valid=False,
            errors=[f"AST parsing failed: {exc}"],
        )

    # 2. FastMCP Tool Contract Inspection
    tool_names: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_mcp_tool = False
            for dec in node.decorator_list:
                # Matches @mcp.tool or @mcp.tool(...)
                if isinstance(dec, ast.Attribute) and dec.attr == "tool":
                    is_mcp_tool = True
                elif isinstance(dec, ast.Call):
                    func = dec.func
                    if isinstance(func, ast.Attribute) and func.attr == "tool":
                        is_mcp_tool = True
                    elif isinstance(func, ast.Name) and func.id == "tool":
                        is_mcp_tool = True

            if is_mcp_tool:
                tool_names.append(node.name)

                # Check docstring
                docstring = ast.get_docstring(node)
                if not docstring or not docstring.strip():
                    warnings.append(
                        f"Tool '{node.name}' at line {node.lineno} lacks a docstring description."
                    )

                # Check parameter type annotations (required for MCP JSON schema synthesis)
                args = node.args.args
                for arg in args:
                    if arg.arg in ("self", "cls", "ctx"):
                        continue
                    if arg.annotation is None:
                        errors.append(
                            f"Tool '{node.name}' parameter '{arg.arg}' at line {node.lineno} "
                            "is missing a type annotation (required for FastMCP schema synthesis)."
                        )

    # If validating tools.py specifically, ensure at least one tool exists
    if "tools" in file_path.lower() and not tool_names:
        warnings.append(f"No @mcp.tool decorated functions discovered in {file_path}.")

    is_valid = len(errors) == 0
    return StaticValidationResult(
        is_valid=is_valid,
        ast_syntax_valid=True,
        mcp_contract_valid=is_valid,
        tool_count=len(tool_names),
        tool_names=tool_names,
        errors=errors,
        warnings=warnings,
    )
