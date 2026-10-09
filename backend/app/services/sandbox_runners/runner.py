"""Sandbox runner: executes one generated-client call inside the sandbox container.

Copied into the container as `/sandbox/runner.py` and launched with `python -P`, so the
sandbox directory is not prepended to `sys.path`: a generated `json.py` or `asyncio.py`
cannot shadow the standard library. Standard library only, plus `httpx` (present in the
sandbox image) for the hermetic mock transport.
"""

import asyncio
import importlib
import inspect
import json
import os
import re
import sys
import time
import traceback

_PREFIX = "APIWEAVER_RESULT:"
# Read and drop the per-run nonce before any generated code is imported. The host only
# accepts a result line carrying it, so code under test cannot print a forged "passed".
# Captured in a local closure so generated client code cannot inspect module or global namespace.
def _make_emitter():
    nonce = os.environ.pop("APIWEAVER_RESULT_NONCE", "")

    def _emit(result):
        print(_PREFIX + nonce + ":" + json.dumps(result, default=str), flush=True)

    return _emit


_emit = _make_emitter()
del _make_emitter
_BODY_NAMES = ("body", "payload", "data", "request", "json_body", "json")


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _setup_path(payload_path):
    roots = [os.path.dirname(payload_path)] if os.path.dirname(payload_path) else []
    for root, dirs, _ in os.walk("/sandbox"):
        dirs[:] = [d for d in dirs if not d.startswith((".", "__")) and d != "node_modules"]
        roots.append(root)
    for root in roots:
        if root not in sys.path:
            sys.path.append(root)


def _install_mock(mock, calls):
    """Answer every HTTP request the client makes from the payload's mock response.

    Hermetic contract mode: the container has no network, and the recorded calls are
    checked against the endpoint's method, path and required query parameters.
    """
    import httpx

    def handler(request):
        raw_path = request.url.raw_path.split(b"?", 1)[0].decode("ascii", "replace")
        calls.append(
            {
                "method": request.method.upper(),
                "path": raw_path,
                "query": sorted(set(request.url.params.keys())),
            }
        )
        status = int(mock.get("status") or 200)
        body = mock.get("body")
        if status in (204, 304) or body is None:
            return httpx.Response(status)
        return httpx.Response(status, json=body)

    transport = httpx.MockTransport(handler)

    def patch(cls):
        original = cls.__init__

        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            kwargs.pop("mounts", None)
            original(self, *args, **kwargs)

        cls.__init__ = __init__

    patch(httpx.AsyncClient)
    patch(httpx.Client)


def _select_client_class(module, op_id):
    classes = [
        getattr(module, a)
        for a in dir(module)
        if isinstance(getattr(module, a), type) and "Client" in a
    ]
    if not classes:
        classes = [
            getattr(module, a)
            for a in dir(module)
            if isinstance(getattr(module, a), type)
            and a not in ("BaseModel", "Exception", "APIWeaverError")
            and not a.startswith("_")
        ]
    target = _norm(op_id)
    for cls in classes:
        if target in {_norm(m) for m in dir(cls) if not m.startswith("_")}:
            return cls
    if classes:
        return max(
            classes,
            key=lambda c: len(
                [m for m in dir(c) if not m.startswith("_") and callable(getattr(c, m, None))]
            ),
        )
    return None


def _construct(client_class, payload):
    # Credentials arrive via the APIWEAVER_API_KEY env var (never a file inside the
    # container — Security.md §7); payload["api_key"] is a legacy secondary source.
    credential = os.environ.get("APIWEAVER_API_KEY") or payload.get("api_key")
    kwargs = {}
    try:
        params = inspect.signature(client_class.__init__).parameters
    except (TypeError, ValueError):
        params = {}
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if "base_url" in params or has_varkw:
        kwargs["base_url"] = payload.get("base_url")
    for name in ("api_key", "token", "auth_token"):
        if name in params:
            kwargs[name] = credential
            break
    else:
        if has_varkw:
            kwargs["api_key"] = credential
    return client_class(**kwargs)


def _resolve_operation(client, op_id):
    candidates = [
        op_id,
        re.sub(r"(?<!^)(?=[A-Z])", "_", op_id).lower().replace("__", "_"),
        op_id.split("_")[0] + "".join(p.title() for p in op_id.split("_")[1:]),
    ]
    for name in candidates:
        if name and callable(getattr(client, name, None)):
            return getattr(client, name)
    target = _norm(op_id)
    for name in dir(client):
        if (
            not name.startswith("_")
            and _norm(name) == target
            and callable(getattr(client, name, None))
        ):
            return getattr(client, name)
    available = [
        m for m in dir(client) if not m.startswith("_") and callable(getattr(client, m, None))
    ]
    raise RuntimeError(f"method '{op_id}' not found on client. Available methods: {available}")


def _bind_arguments(operation, params, body):
    """Map fixture values onto the operation's signature; never invent values."""
    signature = inspect.signature(operation)
    by_norm = {}
    for key, value in params.items():
        by_norm.setdefault(_norm(key), value)
    body_by_norm = {_norm(k): v for k, v in body.items()} if isinstance(body, dict) else {}

    kwargs, missing, body_bound, varkw = {}, [], False, False
    for name, parameter in signature.parameters.items():
        if name == "self" or parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            varkw = True
            continue
        required = parameter.default is inspect.Parameter.empty
        if name in params:
            kwargs[name] = params[name]
        elif _norm(name) in by_norm:
            kwargs[name] = by_norm[_norm(name)]
        elif name in _BODY_NAMES and body is not None:
            kwargs[name] = body
            body_bound = True
        elif required and _norm(name) in body_by_norm:
            kwargs[name] = body_by_norm[_norm(name)]
        elif required:
            missing.append(name)
    if varkw:
        bound = {_norm(k) for k in kwargs}
        for key, value in params.items():
            if _norm(key) not in bound and key.isidentifier():
                kwargs[key] = value
        if body is not None and not body_bound:
            kwargs.setdefault("body", body)
    return kwargs, missing


def _status_of(response):
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    if isinstance(response, dict) and isinstance(response.get("status_code"), int):
        return response["status_code"]
    return None


def _snapshot(response, status_code):
    snapshot = {"status_code": status_code, "headers": {}}
    try:
        snapshot["headers"] = dict(getattr(response, "headers", {}) or {})
    except Exception:
        pass
    if hasattr(response, "json") and callable(response.json):
        try:
            snapshot["body"] = response.json()
        except Exception:
            snapshot["body"] = getattr(response, "text", None)
    else:
        snapshot["body"] = response
    return snapshot


def _fail(result, message):
    result["status"] = "failed"
    result["error"] = message


def _evaluate(result, payload, calls):
    mock = payload.get("mock")
    if mock:
        if not calls:
            return _fail(result, "client made no HTTP request")
        call = calls[-1]
        if call["method"] != mock["method"]:
            return _fail(
                result,
                f"expected a {mock['method']} request, client sent {call['method']} {call['path']}",
            )
        if not re.search(mock["path_regex"], call["path"]):
            return _fail(
                result, f"expected a request to {mock['path']}, client requested {call['path']}"
            )
        absent = [q for q in mock.get("required_query", []) if q not in call["query"]]
        if absent:
            return _fail(result, f"required query parameter(s) not sent: {absent}")
        if result["status_code"] is None:
            # The client returned parsed data rather than the response object.
            result["status_code"] = int(mock.get("status") or 200)

    status_code = result["status_code"]
    if status_code is None:
        return None  # Nothing raised and nothing to compare: the call itself succeeded.
    expected = payload.get("expected_status")
    if expected is None or (isinstance(expected, int) and 200 <= expected < 300):
        if not 200 <= status_code < 300:
            _fail(result, f"Expected 2xx status, got {status_code}")
    elif status_code != expected:
        _fail(result, f"Expected status {expected}, got {status_code}")
    return None


async def _close(client):
    close = getattr(client, "close", None) or getattr(client, "aclose", None)
    if close is None:
        return
    try:
        outcome = close()
        if inspect.isawaitable(outcome):
            await outcome
    except Exception:
        pass


async def _main():
    payload_path = os.environ.get("APIWEAVER_PAYLOAD_PATH", "/sandbox/payload.json")
    _setup_path(payload_path)
    with open(payload_path, encoding="utf-8") as handle:
        payload = json.load(handle)

    calls = []
    if payload.get("mock"):
        _install_mock(payload["mock"], calls)

    module_name = payload["module_name"]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        module = importlib.import_module(module_name.split(".")[-1])

    op_id = payload.get("op_id", "")
    client_class = _select_client_class(module, op_id)
    if client_class is None:
        raise RuntimeError(f"no client class found in module {module_name}")
    client = _construct(client_class, payload)
    operation = _resolve_operation(client, op_id)

    request = payload.get("request") or {}
    kwargs, missing = _bind_arguments(
        operation, request.get("params") or {}, request.get("body")
    )
    if missing:
        await _close(client)
        raise RuntimeError(f"fixture provides no value for required parameter(s): {missing}")

    started = time.perf_counter()
    try:
        # Called exactly once: retrying after a failure could send a POST twice.
        response = operation(**kwargs)
        if inspect.isawaitable(response):
            response = await response
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        await _close(client)

    status_code = _status_of(response)
    result = {
        "status": "passed",
        "status_code": status_code,
        "latency_ms": latency_ms,
        "response_snapshot": None,
        "error": None,
        "stack_trace": None,
        "requests": calls[-5:],
    }
    try:
        result["response_snapshot"] = _snapshot(response, status_code)
    except Exception as snapshot_error:
        result["response_snapshot"] = {"snapshot_error": str(snapshot_error)}
    _evaluate(result, payload, calls)
    _emit(result)
    return 0


def _run():
    try:
        return asyncio.run(_main())
    except Exception as exc:
        failure = traceback.format_exc()
        message = str(exc) or (failure.strip().splitlines()[-1] if failure else "Unknown error")
        status_code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if isinstance(getattr(response, "status_code", None), int):
            status_code = response.status_code
        _emit(
            {
                "status": "failed",
                "status_code": status_code if isinstance(status_code, int) else None,
                "latency_ms": 0,
                "response_snapshot": None,
                "error": message,
                "stack_trace": failure,
            }
        )
        return 1


if __name__ == "__main__":
    sys.exit(_run())
