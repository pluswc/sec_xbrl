#!/usr/bin/env node
"use strict";

/*
 * Optional Windows-to-WSL loopback adapter for the local screening service.
 * Both listeners stay on 127.0.0.1. No external URL is accepted or opened.
 */

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const readline = require("node:readline");

const MAX_DISPLAY_ASSET = 2 * 1024 * 1024;
const MAX_BREAKDOWN_ASSET = 16 * 1024 * 1024;
const MAX_BREAKDOWN_COMPANY = 512 * 1024;
const MAX_REVENUE_COMPANY = 1024 * 1024;
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
    "--assets-root",
    "--revenue-breakdowns",
    "--revenue-breakdowns-sha256",
    "--financial-growth",
    "--financial-growth-sha256",
    "--history-worker",
    "--journal-store",
    "--auxiliary-union",
    "--auxiliary-union-sha256",
    "--auxiliary-union-parent",
    "--auxiliary-union-parent-sha256",
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
  if (Object.hasOwn(values, "--history-worker") !== Object.hasOwn(values, "--journal-store")) {
    throw new Error("--history-worker and --journal-store must be configured together");
  }
  for (const key of ["--history-worker", "--journal-store"]) {
    if (Object.hasOwn(values, key) && (!text(key).startsWith("/") || text(key).split("/").some(part => part === "." || part === ".."))) {
      throw new Error(`${key} must be an explicit absolute Linux path without aliases`);
    }
  }
  const hasBreakdowns = Object.hasOwn(values, "--revenue-breakdowns");
  if (hasBreakdowns !== Object.hasOwn(values, "--revenue-breakdowns-sha256") ||
      (hasBreakdowns && (!path.isAbsolute(text("--revenue-breakdowns")) ||
        !/^[0-9a-f]{64}$/u.test(text("--revenue-breakdowns-sha256"))))) {
    throw new Error("revenue breakdowns require an absolute asset path and SHA-256 pin");
  }
  const hasGrowth = Object.hasOwn(values, "--financial-growth");
  if (hasGrowth !== Object.hasOwn(values, "--financial-growth-sha256") ||
      (hasGrowth && (!path.isAbsolute(text("--financial-growth")) ||
        !/^[0-9a-f]{64}$/u.test(text("--financial-growth-sha256"))))) {
    throw new Error("financial growth requires an absolute asset path and SHA-256 pin");
  }
  const hasAuxiliaryUnion = Object.hasOwn(values, "--auxiliary-union");
  if (hasAuxiliaryUnion !== Object.hasOwn(values, "--auxiliary-union-sha256") ||
      (hasAuxiliaryUnion && (!path.isAbsolute(text("--auxiliary-union")) ||
        !/^[0-9a-f]{64}$/u.test(text("--auxiliary-union-sha256"))))) {
    throw new Error("auxiliary union requires an absolute manifest path and SHA-256 pin");
  }
  const hasAuxiliaryParent = Object.hasOwn(values, "--auxiliary-union-parent");
  if (hasAuxiliaryParent !== Object.hasOwn(values, "--auxiliary-union-parent-sha256") ||
      (hasAuxiliaryParent && (!hasAuxiliaryUnion || !path.isAbsolute(text("--auxiliary-union-parent")) ||
        !/^[0-9a-f]{64}$/u.test(text("--auxiliary-union-parent-sha256"))))) {
    throw new Error("auxiliary delta parent requires an explicit host path and SHA-256 pin");
  }
  return {
    auxiliaryUnion: hasAuxiliaryUnion ? text("--auxiliary-union") : null,
    auxiliaryUnionSha256: hasAuxiliaryUnion ? text("--auxiliary-union-sha256") : null,
    ...(hasAuxiliaryParent ? {auxiliaryUnionParent:{path:text("--auxiliary-union-parent"),sha256:text("--auxiliary-union-parent-sha256")}} : {}),
    revenueBreakdowns: hasBreakdowns ? text("--revenue-breakdowns") : null,
    revenueBreakdownsSha256: hasBreakdowns ? text("--revenue-breakdowns-sha256") : null,
    financialGrowth: hasGrowth ? text("--financial-growth") : null,
    financialGrowthSha256: hasGrowth ? text("--financial-growth-sha256") : null,
    historyWorker: values["--history-worker"] || null,
    journalStore: values["--journal-store"] || null,
    distribution: text("--distribution"),
    linuxPython: text("--linux-python"),
    sourceRoot: text("--source-root"),
    backendPort,
    frontendPort,
    wsl: values["--wsl"] ? text("--wsl") : "wsl.exe",
    assetsRoot: Object.hasOwn(values, "--assets-root") ? text("--assets-root") : null,
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

function loadDisplayAssets(root) {
  if (typeof root !== "string" || !path.isAbsolute(root)) {
    throw new Error("display assets root must be an explicit absolute directory");
  }
  const directory = path.resolve(root);
  for (let entry = directory; ; entry = path.dirname(entry)) {
    if (fs.lstatSync(entry).isSymbolicLink()) throw new Error("display asset aliases are forbidden");
    if (path.dirname(entry) === entry) break;
  }
  if (!fs.lstatSync(directory).isDirectory()) throw new Error("display assets root is not a directory");
  const assets = new Map();
  for (const [route, filename, type] of [
    ["/app.css", "app.css", "text/css; charset=utf-8"],
    ["/app.js", "app.js", "text/javascript; charset=utf-8"],
  ]) {
    const file = path.join(directory, filename);
    if (fs.lstatSync(file).isSymbolicLink()) throw new Error("display asset aliases are forbidden");
    const descriptor = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
    try {
      const before = fs.fstatSync(descriptor);
      if (!before.isFile() || before.size < 1 || before.size > MAX_DISPLAY_ASSET) {
        throw new Error("display asset must be a bounded nonempty regular file");
      }
      const buffer = Buffer.alloc(before.size + 1);
      const count = fs.readSync(descriptor, buffer, 0, buffer.length, 0);
      const after = fs.fstatSync(descriptor);
      if (count !== before.size || after.size !== before.size || after.mtimeMs !== before.mtimeMs) {
        throw new Error("display asset changed while loading");
      }
      const body = buffer.subarray(0, count);
      assets.set(route, { body, type, sha256: crypto.createHash("sha256").update(body).digest("hex") });
    } finally {
      fs.closeSync(descriptor);
    }
  }
  return { directory, assets };
}

function loadPinnedJson(file, digest, label) {
  if (!path.isAbsolute(file) || !/^[0-9a-f]{64}$/u.test(digest)) {
    throw new Error(`${label} asset requires an absolute path and SHA-256 pin`);
  }
  const source = path.resolve(file);
  for (let entry = source; ; entry = path.dirname(entry)) {
    if (fs.lstatSync(entry).isSymbolicLink()) throw new Error(`${label} aliases are forbidden`);
    if (path.dirname(entry) === entry) break;
  }
  const descriptor = fs.openSync(source, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  let payload;
  try {
    const before = fs.fstatSync(descriptor);
    if (!before.isFile() || before.size < 1 || before.size > MAX_BREAKDOWN_ASSET) {
      throw new Error(`${label} asset must be a bounded nonempty file`);
    }
    const buffer = Buffer.alloc(before.size + 1);
    const count = fs.readSync(descriptor, buffer, 0, buffer.length, 0);
    if (count !== before.size || fs.fstatSync(descriptor).size !== before.size ||
        crypto.createHash("sha256").update(buffer.subarray(0, count)).digest("hex") !== digest) {
      throw new Error(`${label} asset differs from pin`);
    }
    payload = JSON.parse(buffer.subarray(0, count).toString("utf8"));
  } finally {
    fs.closeSync(descriptor);
  }
  return payload;
}

function loadProfileAsset(file, digest, label, schema, validate, maxCompanyBytes = MAX_BREAKDOWN_COMPANY) {
  const payload = loadPinnedJson(file, digest, label);
  const { schema_version, dataset_id, dataset_publication_id, financial_as_of, dataset_manifest_sha256, companies } = payload;
  if (!(Array.isArray(schema) ? schema.includes(schema_version) : schema_version === schema) ||
      ![dataset_id, dataset_publication_id].every(value => typeof value === "string" && /^[A-Za-z0-9_.-]{1,128}$/u.test(value)) ||
      !/^\d{4}-\d{2}-\d{2}$/u.test(financial_as_of) || !/^[0-9a-f]{64}$/u.test(dataset_manifest_sha256) ||
      !companies || typeof companies !== "object" || Array.isArray(companies)) {
    throw new Error(`invalid ${label} asset scope`);
  }
  const scope = { schema_version, dataset_id, dataset_publication_id, financial_as_of, dataset_manifest_sha256 };
  const project = validate(payload);
  const byCik = new Map();
  for (const [cik, company] of Object.entries(companies)) {
    if (!/^\d{10}$/u.test(cik) || !company || typeof company !== "object" || Array.isArray(company)) {
      throw new Error(`invalid ${label} company scope`);
    }
    const body = Buffer.from(JSON.stringify({ ...project(company), ...scope, cik }), "utf8");
    if (body.length > maxCompanyBytes) throw new Error(`${label} company exceeds response limit`);
    byCik.set(cik, body);
  }
  return { scope, byCik };
}

function loadRevenueBreakdowns(file, digest) {
  return loadProfileAsset(file, digest, "revenue breakdown", "screening-revenue-breakdowns-v1", () => company => {
    if (![company.annual, company.quarterly].every(view => view && Array.isArray(view.periods) && view.groups)) {
      throw new Error("invalid revenue breakdown company scope");
    }
    return company;
  }, MAX_REVENUE_COMPANY);
}

function loadFinancialGrowth(file, digest) {
  const isRecord = value => value && typeof value === "object" && !Array.isArray(value);
  const isDecimal = value => typeof value === "string" && /^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/iu.test(value);
  const nullableDecimal = value => value === null || isDecimal(value);
  const reference = row => row === null || isRecord(row) && typeof row.observation_id === "string" && row.end_convention === "EXCLUSIVE" &&
    nullableDecimal(row.value) && ["period_start", "period_end"].every(key => row[key] === null || /^\d{4}-\d{2}-\d{2}$/u.test(row[key]));
  const statuses = new Set(["UNAVAILABLE", "RATE_AVAILABLE", "ZERO_REACHED", "ZERO_BASE", "ZERO_UNCHANGED",
    "POSITIVE_TURN", "NEGATIVE_TURN", "NEGATIVE_MAGNITUDE_REDUCED", "NEGATIVE_MAGNITUDE_EXPANDED", "NEGATIVE_MAGNITUDE_UNCHANGED", "CHANGE_AVAILABLE"]);
  const rowValid = row => isRecord(row) && statuses.has(row.status) && reference(row.current) && reference(row.prior) &&
    ["yoy", "delta", "negative_magnitude_change"].every(key => nullableDecimal(row[key])) &&
    (row.status === "UNAVAILABLE" ? row.yoy === null && row.delta === null && row.negative_magnitude_change === null :
      row.current?.value != null && row.prior?.value != null && row.delta !== null &&
      typeof row.basis_assurance === "string" && row.basis_assurance.length > 0);
  return loadProfileAsset(file, digest, "financial growth", ["screening-financial-growth-v1", "screening-financial-growth-v2"], payload => {
    if (payload.schema_version === "screening-financial-growth-v2") return validateFinancialComparisonV2(payload, rowValid, isRecord);
    const { definitions, rule_version, source_compatibility_sha256, period_end_convention } = payload;
    const metrics = ["operating_income", "cfo", "standardized_fcf"];
    const expected = Object.fromEntries(Object.entries({FY: "", QTD_3M: "quarter_", TTM: "ttm_"}).flatMap(
      ([basis, prefix]) => metrics.map(id => [prefix + id, basis])));
    if (rule_version !== "signed-prepared-financial-yoy-v1" || period_end_convention !== "EXCLUSIVE" || !/^[0-9a-f]{64}$/u.test(source_compatibility_sha256) || !isRecord(definitions) ||
        Object.keys(definitions).length !== Object.keys(expected).length ||
        Object.entries(expected).some(([id, basis]) => definitions[id]?.basis !== basis ||
          typeof definitions[id].definition_version !== "string" || !definitions[id].definition_version ||
          !["ordinary_yoy", "negative_magnitude_change", "delta"].every(kind => {
            const formula = definitions[id].formulas?.[kind];
            return formula?.unit === (kind === "delta" ? "USD" : "PERCENT") &&
              typeof formula.expression === "string" && typeof formula.eligibility === "string";
          }))) {
      throw new Error("invalid financial growth definitions");
    }
    return company => {
      if (Object.entries(company).some(([id, periods]) => !Object.hasOwn(expected, id) || !isRecord(periods) ||
          Object.entries(periods).some(([slot, row]) => !(expected[id] === "FY" ? /^\d{4}$/u : /^\d{4}Q[1-4]$/u).test(slot) || (!rowValid(row)||row.status === "CHANGE_AVAILABLE")))) {
        throw new Error("invalid financial growth company series");
      }
      return { definitions, rule_version, source_compatibility_sha256, period_end_convention, series: company };
    };
  });
}

function validateFinancialComparisonV2(payload, legacyRowValid, isRecord) {
  const {definitions, rule_version, source_compatibility_sha256, period_end_convention}=payload;
  if(rule_version!=="catalog-prepared-financial-comparison-v2" || period_end_convention!=="EXCLUSIVE" ||
      !/^[0-9a-f]{64}$/u.test(source_compatibility_sha256) || !isRecord(definitions) ||
      !Object.keys(definitions).length || Object.keys(definitions).length>256) throw new Error("invalid comparison definitions");
  const decimal=value=>value===null||typeof value==="string"&&/^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/iu.test(value);
  for(const [id,definition] of Object.entries(definitions)){
    if(!/^[a-z][a-z0-9_]{0,127}$/u.test(id) || !["FY","QTD_3M","TTM"].includes(definition.basis) ||
        !["FY","QTD_3M","TTM","INSTANT"].includes(definition.period_class) ||
        typeof definition.definition_version!=="string" || !definition.definition_version ||
        !["MONEY","PERCENT"].includes(definition.unit_kind) ||
        definition.comparison_kind!==(definition.unit_kind==="MONEY"?"YOY":"PERCENTAGE_POINT")) throw new Error("invalid comparison definition");
    const kinds=definition.unit_kind==="MONEY"?["ordinary_yoy","negative_magnitude_change","delta"]:["change_pp"];
    if(kinds.some(key=>!isRecord(definition.formulas?.[key])||typeof definition.formulas[key].expression!=="string"||
        typeof definition.formulas[key].eligibility!=="string"||definition.formulas[key].unit!==
        (key==="change_pp"?"PERCENTAGE_POINT":key==="delta"?"USD":"PERCENT"))) throw new Error("invalid comparison formula");
  }
  return company=>{
    for(const [id,periods] of Object.entries(company)){
      const definition=definitions[id];
      if(!definition||!isRecord(periods))throw new Error("invalid comparison metric");
      for(const [slot,row] of Object.entries(periods)){
        if(!(definition.basis==="FY"?/^\d{4}$/u:/^\d{4}Q[1-4]$/u).test(slot)||!legacyRowValid(row)||
            (definition.unit_kind==="PERCENT" ? !decimal(row.change_pp)||row.yoy!==null||row.negative_magnitude_change!==null||
              (row.status==="UNAVAILABLE"?row.change_pp!==null:row.status!=="CHANGE_AVAILABLE"||row.change_pp===null||row.delta!==row.change_pp) :
              row.status==="CHANGE_AVAILABLE"||row.change_pp!=null))throw new Error("invalid comparison series");
      }
    }
    return {definitions,rule_version,source_compatibility_sha256,period_end_convention,series:company};
  };
}

function loadAuxiliaryUnion(file, digest, hostParent = null) {
  const manifest = loadPinnedJson(file, digest, "auxiliary union");
  const validScope = scope => scope && Object.keys(scope).sort().join(",") ===
      "dataset_id,dataset_manifest_sha256,dataset_publication_id,financial_as_of" &&
    [scope.dataset_id, scope.dataset_publication_id].every(value => typeof value === "string" && /^[A-Za-z0-9_.-]{1,128}$/u.test(value)) &&
    /^\d{4}-\d{2}-\d{2}$/u.test(scope.financial_as_of) && /^[0-9a-f]{64}$/u.test(scope.dataset_manifest_sha256);
  const scope = {dataset_id:manifest.dataset_id, dataset_publication_id:manifest.publication_id,
    financial_as_of:manifest.financial_as_of, dataset_manifest_sha256:digest};
  const owners = manifest.auxiliary_owners;
  const delta = manifest.schema_version === "screening-governed-delta-v1";
  const scopes = [scope];
  if (delta) {
    if (!hostParent || hostParent.sha256 !== manifest.parent?.sha256) {
      throw new Error("governed delta requires an explicit byte-identical host parent pin");
    }
    const parent = loadPinnedJson(hostParent.path, hostParent.sha256, "governed delta auxiliary parent");
    if (parent.schema_version !== "screening-cohort-union-v1" || parent.config?.expose_auxiliary_owners !== true ||
        parent.financial_as_of !== manifest.financial_as_of ||
        JSON.stringify(parent.configured_ciks) !== JSON.stringify(manifest.configured_ciks) ||
        JSON.stringify(parent.auxiliary_owners) !== JSON.stringify(owners)) {
      throw new Error("governed delta auxiliary ownership differs from exact parent");
    }
    const parentScope = {dataset_id:parent.dataset_id, dataset_publication_id:parent.publication_id,
      financial_as_of:parent.financial_as_of, dataset_manifest_sha256:hostParent.sha256};
    if (!validScope(parentScope)) throw new Error("invalid auxiliary parent scope");
    scopes.push(parentScope);
  }
  const composed = manifest.schema_version === "screening-cohort-union-v2";
  if (composed) {
    if (!Array.isArray(manifest.auxiliary_contexts)) throw new Error("composed auxiliary contexts are absent");
    for (const context of manifest.auxiliary_contexts) {
      if (!context || !validScope(context.scope) || context.scope.financial_as_of !== scope.financial_as_of ||
          !Array.isArray(context.ciks) || !context.ciks.length || new Set(context.ciks).size !== context.ciks.length ||
          context.ciks.some(cik => !Object.hasOwn(owners || {}, cik))) throw new Error("invalid composed auxiliary ancestor scope");
      scopes.push({...context.scope, ciks:context.ciks});
    }
  }
  if (!delta && hostParent) throw new Error("host parent pin is only valid for a governed delta");
  if ((!delta && (!["screening-cohort-union-v1", "screening-cohort-union-v2"].includes(manifest.schema_version) || manifest.config?.expose_auxiliary_owners !== true)) ||
      !validScope(scope) || !owners || typeof owners !== "object" || Array.isArray(owners) ||
      !Array.isArray(manifest.configured_ciks) || !manifest.configured_ciks.length ||
      new Set(manifest.configured_ciks).size !== manifest.configured_ciks.length ||
      JSON.stringify(Object.keys(owners).sort()) !== JSON.stringify([...manifest.configured_ciks].sort()) ||
      Object.entries(owners).some(([cik, owner]) => !/^\d{10}$/u.test(cik) || !validScope(owner) || owner.financial_as_of !== scope.financial_as_of)) {
    throw new Error("invalid explicit auxiliary union owner scope");
  }
  return {scope, ...((delta || composed) ? {scopes:scopes.map(({ciks, ...identity}) => identity),
    contextCiks:scopes.map(item => item.ciks || manifest.configured_ciks)} : {}), owners:new Map(Object.entries(owners))};
}
function sameAssetScope(left, right) {
  return ["dataset_id","dataset_publication_id","financial_as_of","dataset_manifest_sha256"].every(key => left?.[key] === right?.[key]);
}

function serveRevenueBreakdowns(bundle, request, response, auxiliary = null) {
  return serveProfileAsset(bundle, request, response, "매출 구성", auxiliary);
}
function serveFinancialGrowth(bundle, request, response, auxiliary = null) {
  if (request.method === "GET" && request.url === "/api/financial-growth") {
    const contexts = auxiliary && bundle ? (auxiliary.scopes || [auxiliary.scope]).map((request_scope, index) => ({request_scope, source_scope:bundle.scope,
      available_ciks:[...auxiliary.owners].filter(([cik, owner]) => sameAssetScope(owner, bundle.scope) && bundle.byCik.has(cik) && (!auxiliary.contextCiks || auxiliary.contextCiks[index].includes(cik))).map(([cik]) => cik)})) : [];
    writeJson(response, 200, { configured: Boolean(bundle), ...bundle?.scope,
      ...(auxiliary ? {owner_contexts:contexts} : {}) });
    return;
  }
  return serveProfileAsset(bundle, request, response, "재무 전년 대비", auxiliary);
}
function serveProfileAsset(bundle, request, response, label, auxiliary = null) {
  if (request.method !== "GET") {
    writeJson(response, 405, { error: `${label} 자료는 조회만 할 수 있습니다.` });
    return;
  }
  if (!bundle) {
    writeJson(response, 503, { error: `${label} 자료가 준비되지 않았습니다.` });
    return;
  }
  const query = new URL(request.url, "http://127.0.0.1").searchParams;
  const keys = ["dataset_id", "dataset_publication_id", "financial_as_of", "cik"];
  if ([...query].length !== keys.length || keys.some(key => query.getAll(key).length !== 1) ||
      !/^\d{10}$/u.test(query.get("cik"))) {
    writeJson(response, 400, { error: `${label} 조회 범위를 확인해 주세요.` });
    return;
  }
  let delegated = false;
  let requestScope = null;
  if (keys.slice(0, 3).some(key => query.get(key) !== bundle.scope[key])) {
    const owner = auxiliary?.owners.get(query.get("cik"));
    requestScope = (auxiliary?.scopes || [auxiliary?.scope]).find((scope, index) =>
      scope && keys.slice(0, 3).every(key => query.get(key) === scope[key]) &&
      (!auxiliary.contextCiks || auxiliary.contextCiks[index].includes(query.get("cik"))));
    if (!requestScope || !sameAssetScope(owner, bundle.scope)) {
      writeJson(response, 409, { error: `선택한 기업 발행물에는 ${label} 자료가 준비되지 않았습니다.` });
      return;
    }
    delegated = true;
  }
  let body = bundle.byCik.get(query.get("cik"));
  if (!body) {
    writeJson(response, 404, { error: `이 기업의 ${label} 자료가 준비되지 않았습니다.` });
    return;
  }
  if (delegated) {
    body = Buffer.from(JSON.stringify({schema_version:"screening-auxiliary-owner-response-v1",
      request_scope:{...requestScope,cik:query.get("cik")}, source_scope:auxiliary.owners.get(query.get("cik")),
      owner_proof:{cik:query.get("cik"),union_manifest_sha256:requestScope.dataset_manifest_sha256,
        source_manifest_sha256:bundle.scope.dataset_manifest_sha256}, data:JSON.parse(body.toString("utf8"))}));
  }
  response.writeHead(200, {
    "cache-control": "no-store",
    "content-length": String(body.length),
    "content-type": "application/json; charset=utf-8",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

// A separate child owns lifecycle state. Its failures never terminate the financial relay.
function startHistoryWorker(options) {
  const child = childProcess.spawn(options.wsl, [
    "-d", options.distribution, "--exec", "/usr/bin/env", `PYTHONPATH=${options.sourceRoot}`,
    options.linuxPython, options.historyWorker, "--journal-store", options.journalStore,
  ], { stdio: ["pipe", "pipe", "inherit"], windowsHide: true });
  const pending = new Map();
  let sequence = 0, dead = false;
  const failAll = () => {
    dead = true;
    for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error("history worker is unavailable")); }
    pending.clear();
  };
  child.on("error", failAll);
  child.on("exit", failAll);
  child.stdin.on("error", failAll);
  readline.createInterface({ input: child.stdout, crlfDelay: Infinity }).on("line", line => {
    if (line.length > MAX_RESPONSE_BODY * 2) { failAll(); child.kill(); return; }
    let result;
    try { result = JSON.parse(line); } catch { failAll(); child.kill(); return; }
    const item = pending.get(result?.id);
    if (!item) return;
    pending.delete(result.id); clearTimeout(item.timer);
    try {
      if (!Number.isInteger(result.status) || result.status < 200 || result.status > 599 ||
          typeof result.body_base64 !== "string" || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(result.body_base64)) {
        throw new Error("invalid history worker response");
      }
      const bytes = Buffer.from(result.body_base64, "base64");
      if (bytes.length > MAX_RESPONSE_BODY) throw new Error("history worker response exceeds limit");
      item.resolve({ status: result.status, body: JSON.parse(bytes.toString("utf8")) });
    } catch (error) { item.reject(error); }
  });
  return {
    child,
    request(message) {
      if (dead) return Promise.reject(new Error("history worker is unavailable"));
      return new Promise((resolve, reject) => {
        const id = `history-${++sequence}`;
        const timer = setTimeout(() => {
          pending.delete(id);
          const error = new Error("history worker timed out"); error.status = 504; reject(error);
        }, REQUEST_TIMEOUT_MS);
        pending.set(id, { resolve, reject, timer });
        child.stdin.write(`${JSON.stringify({ ...message, id })}\n`, error => { if (error) failAll(); });
      });
    },
    stop() { failAll(); child.kill(); },
  };
}
function historyGuardRequired(method, route) {
  const pathname = route.split("?", 1)[0];
  return (method === "POST" && ["/api/results", "/api/runs"].includes(pathname)) ||
    /^\/api\/runs\/[^/]+(?:\/trace|\/exports)?$/u.test(pathname) ||
    /^\/api\/saved-conditions\/[^/]+$/u.test(pathname) || pathname === "/api/run-comparison";
}

function startBridge(options) {
  // Both files must load before listening or starting the relay. HTTP never names a file.
  const bundle = options.assetsRoot ? loadDisplayAssets(options.assetsRoot) : null;
  const breakdowns = options.revenueBreakdowns
    ? loadRevenueBreakdowns(options.revenueBreakdowns, options.revenueBreakdownsSha256) : null;
  const growth = options.financialGrowth ? loadFinancialGrowth(options.financialGrowth, options.financialGrowthSha256) : null;
  const auxiliary = options.auxiliaryUnion ? loadAuxiliaryUnion(options.auxiliaryUnion, options.auxiliaryUnionSha256, options.auxiliaryUnionParent || null) : null;
  const relay = childProcess.spawn(
    options.wsl,
    [
      "-d", options.distribution, "--exec", "/usr/bin/env", `PYTHONPATH=${options.sourceRoot}`,
      options.linuxPython, "-m", "sec_xbrl.screening.bridge",
      "--backend-port", String(options.backendPort),
    ],
    { stdio: ["pipe", "pipe", "inherit"], windowsHide: true },
  );
  const history = options.historyWorker ? startHistoryWorker(options) : null;
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
    const requestPath = (request.url || "").split("?", 1)[0];
    if (requestPath === "/api/revenue-breakdowns") {
      serveRevenueBreakdowns(breakdowns, request, response, auxiliary);
      request.resume();
      return;
    }
    if (requestPath === "/api/financial-growth") {
      serveFinancialGrowth(growth, request, response, auxiliary);
      request.resume();
      return;
    }
    const asset = bundle && bundle.assets.get(requestPath);
    if (asset) {
      if (method !== "GET") {
        writeJson(response, 405, { error: "display assets require GET" });
      } else {
        response.writeHead(200, {
          "content-type": asset.type,
          "content-length": String(asset.body.length),
          "cache-control": "no-store",
          "x-content-type-options": "nosniff",
        });
        response.end(asset.body);
      }
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
    request.on("end", async () => {
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
      const route = (request.url || "").split("?", 1)[0];
      const historyNamespace = route === "/api/history" || route.startsWith("/api/history/");
      const listKey = method === "GET" ? ({ "/api/screen-revisions": "revisions", "/api/runs": "runs", "/api/decisions": "decisions" })[route] : null;
      if (historyNamespace && !history) {
        writeJson(response, route === "/api/history/capabilities" && method === "GET" ? 200 : 503,
          { configured: false, available: false, error: "history lifecycle is not configured" });
        return;
      }
      if (history && (historyNamespace || listKey || (method === "POST" && route === "/api/decisions") || historyGuardRequired(method, request.url))) {
        try {
          const result = await history.request(listKey ? { ...message, method: "GET", path: "/api/history", body_base64: "" } :
            { ...message, check_only: !historyNamespace && route !== "/api/decisions" });
          if (listKey || historyNamespace || route === "/api/decisions" || result.status >= 400) {
            writeJson(response, result.status, listKey && result.status < 400 ? result.body[listKey] : result.body);
            return;
          }
        } catch (error) {
          writeJson(response, error.status || 503, { configured: true, available: false, error: "이력 연결을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요." });
          return;
        }
      }
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
    if (bundle) {
      process.stdout.write(`screening display assets: ${JSON.stringify({
        root: bundle.directory,
        sha256: Object.fromEntries([...bundle.assets].map(([route, asset]) => [route, asset.sha256])),
      })}\n`);
    }
  });

  const stop = () => {
    if (stopping) return;
    stopping = true;
    completePending(503, "local bridge is stopping");
    server.close();
    relay.kill();
    history?.stop();
  };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  return { relay, server, history };
}

if (require.main === module) {
  try {
    startBridge(parseArgs(process.argv.slice(2)));
  } catch (error) {
    fail(error instanceof Error ? error.message : "invalid bridge arguments");
  }
}

module.exports = { loadAuxiliaryUnion, allowedPath, parseArgs, startBridge, loadDisplayAssets, loadRevenueBreakdowns, serveRevenueBreakdowns, loadFinancialGrowth, serveFinancialGrowth, startHistoryWorker, historyGuardRequired };
