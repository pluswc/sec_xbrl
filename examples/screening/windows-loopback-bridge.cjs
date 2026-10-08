#!/usr/bin/env node
"use strict";

/*
 * Optional Windows-to-WSL loopback adapter for the local screening service.
 * Both listeners stay on 127.0.0.1. No external URL is accepted or opened.
 */

const childProcess = require("node:child_process");
const http = require("node:http");
const readline = require("node:readline");

const MAX_REQUEST_BODY = 1024 * 1024;
const MAX_RESPONSE_BODY = 32 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 35000;
const ALLOWED_RESPONSE_HEADERS = new Set([
  "cache-control",
  "content-disposition",
  "content-security-policy",
  "content-type",
  "referrer-policy",
  "x-content-type-options",
]);

function fail(message) {
  process.stderr.write(`screening loopback bridge: ${message}\n`);
  process.exitCode = 2;
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key || !key.startsWith("--") || value === undefined) {
      throw new Error("arguments must be --name value pairs");
    }
    if (Object.hasOwn(values, key)) {
      throw new Error(`duplicate argument: ${key}`);
    }
    values[key] = value;
  }
  const allowed = new Set([
    "--distribution",
    "--linux-python",
    "--source-root",
    "--backend-port",
    "--frontend-port",
    "--wsl",
  ]);
  for (const key of Object.keys(values)) {
    if (!allowed.has(key)) throw new Error(`unknown argument: ${key}`);
  }
  for (const key of [
    "--distribution",
    "--linux-python",
    "--source-root",
    "--backend-port",
    "--frontend-port",
  ]) {
    if (!Object.hasOwn(values, key)) throw new Error(`missing argument: ${key}`);
  }
  const text = (key) => {
    const value = values[key];
    if (!value || /[\u0000\r\n]/u.test(value)) throw new Error(`invalid argument: ${key}`);
    return value;
  };
  const port = (key) => {
    const raw = text(key);
    if (!/^[0-9]{1,5}$/u.test(raw)) throw new Error(`invalid port: ${key}`);
    const value = Number(raw);
    if (!Number.isInteger(value) || value < 1 || value > 65535) {
      throw new Error(`invalid port: ${key}`);
    }
    return value;
  };
  const backendPort = port("--backend-port");
  const frontendPort = port("--frontend-port");
  if (backendPort === frontendPort) throw new Error("frontend and backend ports must differ");
  return {
    distribution: text("--distribution"),
    linuxPython: text("--linux-python"),
    sourceRoot: text("--source-root"),
    backendPort,
    frontendPort,
    wsl: values["--wsl"] ? text("--wsl") : "wsl.exe",
  };
}

function allowedPath(value) {
  if (typeof value !== "string" || value.length > 4096 || /[\\\r\n]/u.test(value)) return false;
  let parsed;
  try {
    parsed = new URL(value, "http://127.0.0.1");
  } catch {
    return false;
  }
  if (!value.startsWith("/") || parsed.origin !== "http://127.0.0.1" || parsed.hash) return false;
  const path = parsed.pathname;
  return path === "/" || path === "/app.css" || path === "/app.js" || path === "/favicon.ico" ||
    /^\/api(?:\/[A-Za-z0-9_.-]+)*$/u.test(path) ||
    /^\/exports\/[A-Za-z0-9_.-]+$/u.test(path);
}

function localOrigin(port) {
  return `http://127.0.0.1:${port}`;
}

function writeJson(response, status, payload) {
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-length": String(body.length),
    "content-type": "application/json; charset=utf-8",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

function startBridge(options) {
  const relay = childProcess.spawn(
    options.wsl,
    [
      "-d", options.distribution, "--exec", "/usr/bin/env", `PYTHONPATH=${options.sourceRoot}`,
      options.linuxPython, "-m", "sec_xbrl.screening.bridge",
      "--backend-port", String(options.backendPort),
    ],
    { stdio: ["pipe", "pipe", "inherit"], windowsHide: true },
  );
  const pending = new Map();
  let nextId = 1;
  let stopping = false;

  const completePending = (status, message) => {
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      writeJson(entry.response, status, { error: message });
    }
    pending.clear();
  };

  readline.createInterface({ input: relay.stdout, crlfDelay: Infinity }).on("line", (line) => {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    const entry = message && typeof message.id === "string" ? pending.get(message.id) : undefined;
    if (!entry) return;
    pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.relay_error) {
      writeJson(entry.response, 502, { error: "local relay failed", detail: String(message.message || "") });
      return;
    }
    let body;
    try {
      body = Buffer.from(message.body_base64, "base64");
    } catch {
      writeJson(entry.response, 502, { error: "local relay returned invalid bytes" });
      return;
    }
    if (body.length > MAX_RESPONSE_BODY || !Number.isInteger(message.status) || message.status < 100 || message.status > 599) {
      writeJson(entry.response, 502, { error: "local relay returned an invalid response" });
      return;
    }
    const headers = { "content-length": String(body.length) };
    if (message.headers && typeof message.headers === "object") {
      for (const [name, value] of Object.entries(message.headers)) {
        const lower = name.toLowerCase();
        if (ALLOWED_RESPONSE_HEADERS.has(lower) && typeof value === "string" && !/[\r\n]/u.test(value)) {
          headers[lower] = value;
        }
      }
    }
    entry.response.writeHead(message.status, headers);
    entry.response.end(body);
  });

  relay.on("error", () => completePending(502, "local WSL relay could not start"));
  relay.on("exit", () => {
    if (!stopping) completePending(502, "local WSL relay stopped");
  });

  const server = http.createServer((request, response) => {
    const expectedHost = `127.0.0.1:${options.frontendPort}`;
    const expectedOrigin = localOrigin(options.frontendPort);
    const method = request.method || "";
    if (request.headers.host !== expectedHost) {
      writeJson(response, 403, { error: "Host must match the Windows loopback service" });
      request.resume();
      return;
    }
    if (!new Set(["GET", "POST"]).has(method) || !allowedPath(request.url || "")) {
      writeJson(response, 405, { error: "method or path is not allowed" });
      request.resume();
      return;
    }
    const origin = request.headers.origin;
    if (origin !== undefined && origin !== expectedOrigin) {
      writeJson(response, 403, { error: "Origin must match the Windows loopback service" });
      request.resume();
      return;
    }
    if (method === "POST" && origin !== expectedOrigin) {
      writeJson(response, 403, { error: "POST requires the same loopback Origin" });
      request.resume();
      return;
    }
    if (method === "POST" && request.headers["content-type"] !== "application/json") {
      writeJson(response, 400, { error: "POST requires application/json" });
      request.resume();
      return;
    }
    const declaredLength = request.headers["content-length"];
    if (declaredLength !== undefined && (!/^[0-9]+$/u.test(declaredLength) || Number(declaredLength) > MAX_REQUEST_BODY)) {
      writeJson(response, 413, { error: "request body exceeds bridge limit" });
      request.resume();
      return;
    }
    const chunks = [];
    let size = 0;
    let rejected = false;
    request.on("data", (chunk) => {
      if (rejected) return;
      size += chunk.length;
      if (size > MAX_REQUEST_BODY) {
        rejected = true;
        writeJson(response, 413, { error: "request body exceeds bridge limit" });
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (rejected) return;
      const id = String(nextId++);
      const message = {
        id,
        method,
        path: request.url,
        headers: {
          accept: typeof request.headers.accept === "string" ? request.headers.accept : "",
          "content-type": typeof request.headers["content-type"] === "string" ? request.headers["content-type"] : undefined,
        },
        body_base64: Buffer.concat(chunks).toString("base64"),
      };
      const timer = setTimeout(() => {
        const current = pending.get(id);
        if (!current) return;
        pending.delete(id);
        writeJson(current.response, 504, { error: "local relay timed out" });
      }, REQUEST_TIMEOUT_MS);
      pending.set(id, { response, timer });
      relay.stdin.write(`${JSON.stringify(message)}\n`, (error) => {
        if (!error) return;
        const current = pending.get(id);
        if (!current) return;
        pending.delete(id);
        clearTimeout(timer);
        writeJson(current.response, 502, { error: "local relay is unavailable" });
      });
    });
  });

  server.on("clientError", (_error, socket) => socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n"));
  server.listen(options.frontendPort, "127.0.0.1", () => {
    process.stdout.write(`screening dashboard: ${localOrigin(options.frontendPort)}/\n`);
  });

  const stop = () => {
    if (stopping) return;
    stopping = true;
    completePending(503, "local bridge is stopping");
    server.close();
    relay.kill();
  };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  return { relay, server };
}

if (require.main === module) {
  try {
    startBridge(parseArgs(process.argv.slice(2)));
  } catch (error) {
    fail(error instanceof Error ? error.message : "invalid bridge arguments");
  }
}

module.exports = { allowedPath, parseArgs, startBridge };
