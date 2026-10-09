// Sandbox runner: executes one generated Node.js/TypeScript client call.
//
// Copied into the container as /sandbox/runner.mjs. In hermetic mode (payload.mock) the
// container has no network: globalThis.fetch answers from the mock and records each
// request, which is then checked against the endpoint's method, path and query.
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const RESULT_PREFIX = "APIWEAVER_RESULT:";
// Read and drop the per-run nonce before the generated module is imported, so code under
// test cannot print a result line the host would accept.
const NONCE = process.env.APIWEAVER_RESULT_NONCE || "";
delete process.env.APIWEAVER_RESULT_NONCE;
const BODY_NAMES = ["body", "payload", "data", "request", "jsonbody", "json"];

const norm = (name) => String(name).toLowerCase().replace(/[^a-z0-9]/g, "");

function emit(result) {
  console.log(RESULT_PREFIX + NONCE + ":" + JSON.stringify(result));
}

function installMock(mock, calls) {
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url ?? String(input));
    const method = String(init.method || (typeof input === "object" && input.method) || "GET");
    calls.push({
      method: method.toUpperCase(),
      path: url.pathname,
      query: [...new Set(url.searchParams.keys())].sort(),
    });
    const status = Number(mock.status || 200);
    const empty = status === 204 || status === 304 || mock.body === null || mock.body === undefined;
    return new Response(empty ? null : JSON.stringify(mock.body), {
      status,
      headers: empty ? {} : { "content-type": "application/json" },
    });
  };
}

// Declared parameter names of a function, or null when they cannot be read reliably
// (destructured or computed signatures), in which case a single options object is used.
function paramNames(fn) {
  const source = Function.prototype.toString
    .call(fn)
    .replace(/\/\/.*$/gm, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const match = source.match(/^[^(]*\(([^)]*)\)/);
  if (!match) return null;
  const raw = match[1].trim();
  if (!raw) return [];
  if (raw.includes("{") || raw.includes("[")) return null;
  return raw
    .split(",")
    .map((p) => p.trim().replace(/^\.\.\./, "").split(/[=:?\s]/)[0].trim())
    .filter(Boolean);
}

function selectClientClass(mod, opId) {
  const classes = Object.entries(mod)
    .filter(([key, val]) => typeof val === "function" && key.toLowerCase().includes("client"))
    .map(([, val]) => val);
  if (classes.length === 0 && typeof mod.default === "function") classes.push(mod.default);
  const target = norm(opId);
  for (const cls of classes) {
    if (Object.getOwnPropertyNames(cls.prototype || {}).map(norm).includes(target)) return cls;
  }
  return classes.sort(
    (a, b) =>
      Object.getOwnPropertyNames(b.prototype || {}).length -
      Object.getOwnPropertyNames(a.prototype || {}).length,
  )[0];
}

function resolveOperation(client, opId) {
  const candidates = [
    opId,
    opId.replace(/_([a-z0-9])/gi, (_, c) => c.toUpperCase()),
    opId.replace(/([A-Z])/g, "_$1").toLowerCase().replace(/^_/, ""),
  ];
  for (const name of candidates) {
    if (typeof client[name] === "function") return client[name];
  }
  const target = norm(opId);
  let proto = Object.getPrototypeOf(client);
  while (proto && proto !== Object.prototype) {
    for (const name of Object.getOwnPropertyNames(proto)) {
      if (name !== "constructor" && norm(name) === target && typeof client[name] === "function") {
        return client[name];
      }
    }
    proto = Object.getPrototypeOf(proto);
  }
  throw new Error(`method '${opId}' not found on client`);
}

function bindArguments(names, params, body) {
  const byNorm = {};
  for (const [k, v] of Object.entries(params)) if (!(norm(k) in byNorm)) byNorm[norm(k)] = v;
  const bodyNorm =
    body && typeof body === "object" && !Array.isArray(body)
      ? Object.fromEntries(Object.entries(body).map(([k, v]) => [norm(k), v]))
      : {};
  return names.map((name) => {
    if (name in params) return params[name];
    if (norm(name) in byNorm) return byNorm[norm(name)];
    if (BODY_NAMES.includes(norm(name))) return body;
    if (norm(name) in bodyNorm) return bodyNorm[norm(name)];
    return undefined;
  });
}

function statusOf(res) {
  if (res == null) return null;
  if (res.response && typeof res.response.status === "number") return res.response.status;
  for (const key of ["status", "statusCode", "status_code"]) {
    if (typeof res[key] === "number") return res[key];
  }
  return null;
}

function evaluate(result, payload, calls) {
  const mock = payload.mock;
  const fail = (message) => {
    result.status = "failed";
    result.error = message;
  };
  if (mock) {
    if (calls.length === 0) return fail("client made no HTTP request");
    const call = calls[calls.length - 1];
    if (call.method !== mock.method) {
      return fail(`expected a ${mock.method} request, client sent ${call.method} ${call.path}`);
    }
    if (!new RegExp(mock.path_regex).test(call.path)) {
      return fail(`expected a request to ${mock.path}, client requested ${call.path}`);
    }
    const absent = (mock.required_query || []).filter((q) => !call.query.includes(q));
    if (absent.length) return fail(`required query parameter(s) not sent: ${absent.join(", ")}`);
    if (result.status_code === null) result.status_code = Number(mock.status || 200);
  }
  const code = result.status_code;
  if (code === null) return;
  const expected = payload.expected_status;
  if (!expected || (expected >= 200 && expected < 300)) {
    if (!(code >= 200 && code < 300)) fail(`Expected 2xx status, got ${code}`);
  } else if (code !== expected) {
    fail(`Expected status ${expected}, got ${code}`);
  }
}

async function main() {
  const payloadPath = process.env.APIWEAVER_PAYLOAD_PATH || "/sandbox/payload.json";
  const payload = JSON.parse(fs.readFileSync(payloadPath, "utf-8"));
  const calls = [];
  if (payload.mock) installMock(payload.mock, calls);

  const relPath = payload.client_file || "client.ts";
  const mod = await import(pathToFileURL(path.resolve("/sandbox", relPath)).href);
  const ClientClass = selectClientClass(mod, payload.op_id || "");
  if (!ClientClass) throw new Error(`no client class found in module ${relPath}`);

  const client = new ClientClass({
    baseUrl: payload.base_url,
    apiKey: process.env.APIWEAVER_API_KEY || payload.api_key,
  });
  const operation = resolveOperation(client, payload.op_id || "");

  const request = payload.request || {};
  const params = request.params || {};
  const body = request.body;
  const names = paramNames(operation);
  const args =
    names === null ? [{ ...params, ...(body !== undefined ? { body } : {}) }] : bindArguments(names, params, body);

  const started = performance.now();
  let response;
  try {
    // Called exactly once: retrying after a throw could send a POST twice.
    response = await operation.apply(client, args);
  } finally {
    if (typeof client.close === "function") {
      try {
        await client.close();
      } catch {
        /* closing is best effort */
      }
    }
  }
  const result = {
    status: "passed",
    status_code: statusOf(response),
    latency_ms: Math.round(performance.now() - started),
    response_snapshot: null,
    error: null,
    stack_trace: null,
    requests: calls.slice(-5),
  };
  // The snapshot always carries the parsed body under `body`, matching the Python runner,
  // so the host can chain ids from either language.
  if (response && typeof response.json === "function") {
    try {
      result.response_snapshot = { status_code: result.status_code, body: await response.json() };
    } catch {
      result.response_snapshot = { status_code: result.status_code, body: null };
    }
  } else if (response && response.data !== undefined) {
    result.response_snapshot = { status_code: result.status_code, body: response.data };
  } else {
    result.response_snapshot = { status_code: result.status_code, body: response ?? null };
  }
  evaluate(result, payload, calls);
  emit(result);
}

main().catch((err) => {
  let code = null;
  if (err && typeof err.statusCode === "number") code = err.statusCode;
  else if (err?.response && typeof err.response.status === "number") code = err.response.status;
  emit({
    status: "failed",
    status_code: code,
    latency_ms: 0,
    response_snapshot: null,
    error: String(err?.message || err),
    stack_trace: String(err?.stack || ""),
  });
  process.exit(1);
});
