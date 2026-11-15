"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),test=require("node:test");
const bridge=require("../../examples/screening/windows-loopback-bridge.cjs");
const source=fs.readFileSync(path.join(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
const snippet=source.slice(source.indexOf("// Prepared daily price worksheet."),source.indexOf('if(typeof document!=="undefined"&&document.querySelector(".task-nav"))'));
const scope={dataset_id:"prepared109",dataset_publication_id:"pub109",financial_as_of:"2026-10-25",dataset_manifest_sha256:"a".repeat(64)};
function fixture(extra={}){
 const hosts=new Map();const host=id=>{if(!hosts.has(id))hosts.set(id,{textContent:"",innerHTML:"",disabled:false,value:"",selectedOptions:[{value:"per"}]});return hosts.get(id)};
 const env={URLSearchParams,Map,Set,JSON,console,Math,Number,BigInt,Object,String,Array,Error,Promise,setTimeout,clearTimeout,
  $:host,$$:()=>[],esc:v=>String(v??""),compactFinancialDate:v=>v,inclusiveEnd:v=>v,
  S:{explorerSelected:new Set()},explorerDataset:()=>({...scope,publication_id:scope.dataset_publication_id,auxiliary_manifest_sha256:scope.dataset_manifest_sha256}),
  ...extra};
 const formatting=source.slice(source.indexOf("function formatDecimal("),source.indexOf("function displayValue("));
 const f=vm.runInNewContext(formatting+snippet+"\n({state:priceWorksheet,priceExecute,priceInvalidate,priceValue,priceSave,priceReopen,priceQuery,priceScopeMatchesCurrent,priceRowsMarkup,priceShowEvidence,priceDisplayResult,priceDefinitionLabel})",env);
 f.state.capability={definitions:{per:{metric_id:"per",label:"PER",unit:"MULTIPLE"}},companies:[{cik:"0000000001",ticker:"ONE"}],dataset_scope:scope};
 return {f,host};
}
function result(value="20",publication="old"){return {publication_id:publication,mode:"latest",definitions:{per:{label:"PER"}},rows:[{metric_id:"per",cik:"0000000001",as_of:"2026-10-23",value,status:"AVAILABLE",unit:"MULTIPLE"}],unavailable_ranges:[]}}

test("late request cannot repaint edited company/metric scope",async()=>{
 let resolve;const {f,host}=fixture({api:()=>new Promise(r=>resolve=r)});
 const pending=f.priceExecute("query",{mode:"latest",metric_ids:["per"]});
 f.priceInvalidate();resolve(result());await pending;
 assert.equal(f.state.result,null);assert.equal(host("#price-save-result").disabled,true);
 assert.match(host("#price-draft-state").textContent,/조건이 바뀌었습니다/);
});

test("preview has no save; explicit result keeps exact backend request and note",async()=>{
 const calls=[];const {f,host}=fixture({api:async(url,options)=>{calls.push([url,options&&JSON.parse(options.body)]);return url.endsWith("/saves")?(options?{id:"saved"}:{saves:[]}):result()}});
 const request={mode:"latest",metric_ids:["per"],ciks:["0000000001"]};
 await f.priceExecute("query",request);assert.equal(calls.length,1);
 host("#price-save-title").value="Research";host("#price-note").value="Exact source memo";
 await f.priceSave("RESULT");assert.equal(calls[1][0],"/api/price-metrics/saves");
 assert.equal(calls[1][1].kind,"RESULT");assert.equal(calls[1][1].note,"Exact source memo");assert.equal(JSON.stringify(calls[1][1].request),JSON.stringify(request));
 f.priceInvalidate();await assert.rejects(()=>f.priceSave("RESULT"),/먼저 시험 실행/);
});

test("reopen displays original condition preview readonly without evaluating active publication",async()=>{
 const calls=[];const saved={kind:"CONDITION",operation:"screen",request:{conditions:[]},title:"Old",note:"old memo",publication_id:"A",result:null,original_condition_preview:result("10","A")};
 const {f,host}=fixture({api:async url=>{calls.push(url);return saved}});
 await f.priceReopen("price-save-1");assert.equal(calls.length,1);assert.equal(f.state.readonly,true);
 assert.equal(f.state.result.publication_id,"A");assert.equal(host("#price-save-result").disabled,true);assert.match(host("#price-draft-state").textContent,/읽기 전용/);
 assert.match(host("#price-query-result").innerHTML,/10.00배/);
});

test("price formatting uses million currency amounts, per-share bands and explained missing",()=>{
 const {f}=fixture();assert.match(f.priceValue({status:"AVAILABLE",unit:"CURRENCY",currency:"USD",value:"3895535842529.296875"}),/3,895,536 백만 USD/);
 assert.match(f.priceValue({status:"AVAILABLE",unit:"CURRENCY_PER_SHARE",currency:"USD",value:"179.5"}),/179.50 USD\/주/);
 assert.match(f.priceValue({status:"UNAVAILABLE",reason:"EPS_NONPOSITIVE"}),/EPS가 0 이하/);
 assert(f.priceScopeMatchesCurrent());f.state.capability.dataset_scope={...scope,dataset_publication_id:"other"};assert(!f.priceScopeMatchesCurrent());
});

test("comparison and daily series enforce meaningful selected-company counts",async()=>{
 const {f}=fixture();await assert.rejects(()=>f.priceQuery("comparison"),/2~4개/);await assert.rejects(()=>f.priceQuery("series"),/한 기업/);
});

test("optional isolated price worker requires exact source, manifest and separate journal",()=>{
 const base=["--distribution","Ubuntu","--linux-python","/project/.venv/bin/python","--source-root","/qualified-d1e/src","--backend-port","19078","--frontend-port","18887"];
 assert(!bridge.parseArgs(base).priceMetrics);
 assert.throws(()=>bridge.parseArgs([...base,"--price-metrics-manifest","/work/prices/manifest.json"]),/price metrics/);
 const options=bridge.parseArgs([...base,"--price-metrics-manifest","/work/prices/manifest.json","--price-metrics-sha256","a".repeat(64),"--price-metrics-journal","/work/prices/new-journal.sqlite","--price-source-root","/new-source/src"]);
 assert.equal(options.sourceRoot,"/qualified-d1e/src");assert.equal(options.priceMetrics.sourceRoot,"/new-source/src");assert(bridge.allowedPath("/api/price-metrics/saves/price-save-abc"));
});

test("reopened A evidence carries A transport context and renders A definitions and quote",async()=>{
 const a=result("50","A"),defs={per:{metric_id:"per",label:"Original A PER",formula:"A declared formula"}};a.definitions=defs;
 let evidenceRequest;
 const {f,host}=fixture({api:async(url,options)=>{
  if(!options)return {kind:"RESULT",operation:"query",request:{metric_ids:["per"]},title:"SavedA",note:"old",publication_id:"A",result:a,evidence_context:"context-A",definition_context:defs};
  evidenceRequest=JSON.parse(options.body);return {publication_id:"A",evidence_context:"context-A",definitions:defs,row:{metric_id:"per"},financial_inputs:[],price_inputs:[{as_traded_close:"100",currency:"USD",trade_date:"2026-10-23"}],expected_sessions:["2026-10-23"]};
 }});
 f.state.capability.definitions.per={label:"Active B PER",formula:"B declared formula"};
 await f.priceReopen("saved-A");await f.priceShowEvidence("0000000001","old-A-id");
 assert.equal(evidenceRequest.evidence_context,"context-A");assert.equal(Object.keys(evidenceRequest).sort().join(","),"cik,evidence_context,observation_id");
 assert.match(host("#price-evidence-content").innerHTML,/Original A PER/);assert.match(host("#price-evidence-content").innerHTML,/A declared formula/);
 assert.doesNotMatch(host("#price-evidence-content").innerHTML,/Active B|B declared/);assert.match(host("#price-evidence-content").innerHTML,/100.00 USD/);
});

test("late evidence from A cannot repaint a new B result context",async()=>{
 let resolveEvidence;const {f,host}=fixture({api:async(url,options)=>url.endsWith("/evidence")?new Promise(resolve=>resolveEvidence=resolve):{...result("100","B"),evidence_context:"context-B"}});
 f.priceDisplayResult({...result("50","A"),evidence_context:"context-A"});
 const old=f.priceShowEvidence("0000000001","A-id");await f.priceExecute("query",{metric_ids:["per"]});
 resolveEvidence({publication_id:"A",evidence_context:"context-A",definitions:{per:{label:"Late A"}},row:{metric_id:"per"},financial_inputs:[],price_inputs:[]});await old;
 assert.equal(f.state.evidenceContext,"context-B");assert.equal(host("#price-evidence").hidden,true);assert.doesNotMatch(host("#price-evidence-content").innerHTML,/Late A/);
});

test("latest evidence click owns the panel and source mismatches fail visibly",async()=>{
 const pending=[];const {f,host}=fixture({api:()=>new Promise(resolve=>pending.push(resolve))});
 f.priceDisplayResult({...result("50","A"),evidence_context:"context-A"});
 const first=f.priceShowEvidence("0000000001","first"),second=f.priceShowEvidence("0000000001","second");
 const payload=label=>({publication_id:"A",evidence_context:"context-A",definitions:{per:{label,formula:label}},row:{metric_id:"per"},financial_inputs:[],price_inputs:[]});
 pending[1](payload("Second selection"));await second;pending[0](payload("First stale selection"));await first;
 assert.match(host("#price-evidence-content").innerHTML,/Second selection/);assert.doesNotMatch(host("#price-evidence-content").innerHTML,/First stale/);
 const mismatch=f.priceShowEvidence("0000000001","bad");pending[2]({...payload("Wrong source"),publication_id:"B"});await assert.rejects(()=>mismatch,/원 자료가 다릅니다/);
 assert.match(f.priceDefinitionLabel({label:"EV_EBITDA",definition_version:"price-related-metrics-v1:historical_ev_ebitda_percentiles_3y"},"historical_ev_ebitda_percentiles_3y"),/영업이익\+D&A proxy/);
});
