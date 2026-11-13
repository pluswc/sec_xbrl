"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { once } = require("node:events");
const test = require("node:test");
const root = path.resolve(__dirname, "../..");
const bridge = require(path.join(root, "examples/screening/windows-loopback-bridge.cjs"));
const source = fs.readFileSync(path.join(root, "examples/screening/display-assets/app.js"), "utf8");
const frozen = fs.readFileSync(path.join(root, "src/sec_xbrl/screening/ui.py"), "utf8").split("JS = r'''")[1].split("'''", 1)[0];
const numeric = vm.runInNewContext(source.slice(source.indexOf("function formatDecimal("), source.indexOf("function thresholdToApi(")) +
  "\n({formatDecimal,displayValue,shiftDecimal})");

test("display rounds decimal strings half-up without precision loss or unit policy changes", () => {
  for (const [input, places, expected] of [
    ["1.05", 1, "1.1"], ["-1.05", 1, "-1.1"], ["9.995", 2, "10.00"],
    ["-0.0049", 2, "0.00"], ["-0.005", 2, "-0.01"], ["0", 1, "0.0"],
    ["0", 2, "0.00"], [null, 2, "—"], [undefined, 1, "—"],
    ["90071992547409931234567890.995", 2, "90,071,992,547,409,931,234,567,891.00"],
    ["1.235e2", 2, "123.50"], ["-1.005e-1", 2, "-0.10"],
  ]) assert.equal(numeric.formatDecimal(input, places), expected);
  assert.equal(numeric.displayValue("41305000000", {unit_kind: "MONEY"}), "41,305");
  assert.equal(numeric.displayValue("1.235", {unit_kind: "RATIO"}), "1.24");
  assert.equal(numeric.displayValue("6.4", {unit_kind: "PERCENT"}), "6.4");
  assert.equal(numeric.displayValue("0", {unit_kind: "MONEY"}), "0");
  assert.equal(numeric.displayValue(null, {unit_kind: "MONEY"}), "—");
  assert.equal(numeric.displayValue("1e100", {unit_kind: "MONEY"}).replaceAll(",", ""), "1" + "0".repeat(94));
  for (const [value, kind, expected] of [
    ["499999", "MONEY", "<1"], ["-499999", "MONEY", ">-1"],
    ["500000", "MONEY", "1"], ["-500000", "MONEY", "-1"],
    ["0.049", "PERCENT", "<0.1"], ["-0.049", "PERCENT", ">-0.1"],
    ["0.05", "PERCENT", "0.1"], ["-0.05", "PERCENT", "-0.1"],
  ]) assert.equal(numeric.displayValue(value, {unit_kind: kind}), expected);
});

test("all existing non-presentation functions and financial workflow handlers stay byte-identical", () => {
  // History lifecycle changes only projection reads, owned opens and action availability.
  const allowed = new Set(["showView", "markDirty", "setCriteriaCompact", "renderLibrary", "loadLibrary", "addGuideMetric", "revisionContent", "loadScreenRecord", "togglePeriod", "switchFrequency", "setRun", "explorerPeriod", "renderProfile", "loadAnnualExplorer", "openAnnualProfile", "renderAnnualComparison", "bindAnnualExplorer", "newScreen", "api", "refreshScreens", "refreshRuns", "renderTimeline", "saveDecision", "syncResultActions", "openRun", "openSavedScreenRecord", "boot", "formatDecimal", "unitLabel", "displayValue", "renderRows", "renderMetricEvidence", "comparePeer", "explorerValue", "renderExplorer", "profileObservationCell", "renderProfileTrend", "explorerMetric", "updateExplorerSort", "loadExplorer", "openProfile", "closeProfile", "renderComparison", "openComparison", "bindExplorer", "updateCompareButton"]);
  for (const line of frozen.split("\n")) {
    const name = line.match(/^(?:async )?function (\w+)\(/)?.[1];
    if (name && !allowed.has(name)) assert(source.split("\n").includes(line), `changed protected function ${name}`);
    if (!name && line.startsWith("$(")) assert(source.includes(line), "changed button/event workflow binding");
  }
  for (const name of ["shiftDecimal", "thresholdToApi", "thresholdFromApi", "execute", "saveScreen", "saveResult", "exportRun"]) {
    const original = frozen.split("\n").find(line => new RegExp(`^(?:async )?function ${name}\\(`).test(line));
    if (original) assert(source.includes(original), name);
  }
});

test("partial numeric fragments become ellipses only where a whole mark fits", () => {
  const definition = source.slice(source.indexOf("function visibleNumberFragment("), source.indexOf("function maskPartialNumbers("));
  const calculate = vm.runInNewContext(definition + "\nvisibleNumberFragment");
  assert.equal(calculate({left: 220, right: 300}, 200, 320).clipped, false);
  assert.equal(calculate({left: 180, right: 260}, 224, 320).clipped, true);
  assert.equal(calculate({left: 180, right: 260}, 224, 320).visible, true);
  assert.equal(calculate({left: 280, right: 360}, 224, 320).markLeft, 26);
  assert.equal(calculate({left: 180, right: 230}, 224, 320).visible, false);
  assert.equal(calculate({left: 180, right: 200}, 224, 320).visible, false);
});

function bundleDirectory() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "screening-display-"));
  fs.writeFileSync(path.join(directory, "app.css"), "sheet-v1");
  fs.writeFileSync(path.join(directory, "app.js"), "script-v1");
  return directory;
}

test("explicit bundle rejects aliases, missing/empty/oversized files and relative roots", () => {
  const directory = bundleDirectory();
  try {
    assert.throws(() => bridge.loadDisplayAssets("relative"), /absolute/);
    fs.renameSync(path.join(directory, "app.css"), path.join(directory, "real.css"));
    fs.symlinkSync("real.css", path.join(directory, "app.css"));
    assert.throws(() => bridge.loadDisplayAssets(directory), /aliases/);
    fs.unlinkSync(path.join(directory, "app.css"));
    fs.writeFileSync(path.join(directory, "app.css"), "");
    assert.throws(() => bridge.loadDisplayAssets(directory), /bounded/);
    fs.writeFileSync(path.join(directory, "app.css"), Buffer.alloc(2 * 1024 * 1024 + 1));
    assert.throws(() => bridge.loadDisplayAssets(directory), /bounded/);
    fs.writeFileSync(path.join(directory, "app.css"), "sheet-v1");
    const alias = path.join(directory, "alias");
    fs.symlinkSync(directory, alias, "dir");
    assert.throws(() => bridge.loadDisplayAssets(alias), /aliases/);
    fs.unlinkSync(path.join(directory, "app.js"));
    assert.throws(() => bridge.loadDisplayAssets(directory), /ENOENT/);
  } finally { fs.rmSync(directory, {recursive: true, force: true}); }
});

function request(server, route, options = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({hostname: "127.0.0.1", port: server.address().port, path: route, agent: false,
      method: options.method || "GET", headers: {host: "127.0.0.1:0", ...options.headers}}, response => {
      const chunks = [];
      response.on("data", chunk => chunks.push(chunk));
      response.on("end", () => resolve({status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks).toString()}));
    });
    req.on("error", reject);
    req.end(options.body);
  });
}

async function bridgeFixture(assetsRoot, run) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "screening-relay-"));
  const executable = path.join(directory, "fake-wsl");
  fs.writeFileSync(executable, `#!/usr/bin/env node\nconst r=require('node:readline');r.createInterface({input:process.stdin}).on('line',line=>{const m=JSON.parse(line);console.log(JSON.stringify({id:m.id,status:200,headers:{'content-type':'text/plain','content-security-policy':"default-src 'self'; script-src 'self'"},body_base64:Buffer.from('relay:'+m.path).toString('base64')}))});\n`, {mode: 0o700});
  const instance = bridge.startBridge({wsl: executable, distribution: "fixture", linuxPython: "/unused/python", sourceRoot: "/unused/src", frontendPort: 0, backendPort: 1, assetsRoot});
  await once(instance.server, "listening");
  try { await run(instance.server); }
  finally {
    instance.server.closeAllConnections();
    await new Promise(resolve => instance.server.close(resolve));
    instance.relay.kill();
    fs.rmSync(directory, {recursive: true, force: true});
  }
}

test("opt-in bridge enforces existing security gates, serves immutable two-file bytes, and preserves relay/CSP", async () => {
  const directory = bundleDirectory();
  try {
    await bridgeFixture(directory, async server => {
      fs.writeFileSync(path.join(directory, "app.css"), "changed-after-start");
      const css = await request(server, "/app.css");
      assert.equal(css.body, "sheet-v1");
      assert.equal(css.headers["content-type"], "text/css; charset=utf-8");
      assert.equal(css.headers["cache-control"], "no-store");
      assert.equal(css.headers["x-content-type-options"], "nosniff");
      assert.equal((await request(server, "/app.js?version=one")).body, "script-v1");
      assert.equal((await request(server, "/app.js")).headers["content-type"], "text/javascript; charset=utf-8");
      assert.equal((await request(server, "/app.js", {headers: {host: "evil.invalid"}})).status, 403);
      assert.equal((await request(server, "/app.css", {headers: {origin: "https://evil.invalid"}})).status, 403);
      assert.equal((await request(server, "/app.css", {method: "POST", headers: {origin: "http://127.0.0.1:0", "content-type": "application/json"}, body: "{}"})).status, 405);
      assert.equal((await request(server, "/other.css")).status, 405);
      assert.equal((await request(server, "/app.css", {headers: {"content-length": String(1024 * 1024 + 1)}})).status, 413);
      for (const route of ["/", "/api/status", "/exports/example.csv"]) {
        const relayed = await request(server, route);
        assert.equal(relayed.body, "relay:" + route);
        assert.equal(relayed.headers["content-security-policy"], "default-src 'self'; script-src 'self'");
      }
    });
    await bridgeFixture(null, async server => {
      assert.equal((await request(server, "/app.css")).body, "relay:/app.css");
      assert.equal((await request(server, "/app.js")).body, "relay:/app.js");
    });
  } finally { fs.rmSync(directory, {recursive: true, force: true}); }
});
