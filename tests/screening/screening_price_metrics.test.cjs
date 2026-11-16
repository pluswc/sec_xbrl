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
 const f=vm.runInNewContext(formatting+snippet+"\n({state:priceWorksheet,priceExecute,priceInvalidate,priceValue,priceSave,priceReopen,priceQuery,priceScopeMatchesCurrent,priceRowsMarkup,priceShowEvidence,priceDisplayResult,priceDefinitionLabel,priceExport})",env);
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

test("company financial dates distinguish verified-through, selection and the legacy view",()=>{
 const {f,host}=fixture();
 const data={...result(),price_as_of:"2026-11-13",requested_as_of:"2026-11-16",staleness_calendar_days:3,dataset_scope:scope,
  definitions:{per:{label:"PER",family:"VALUATION"}},company_financial_readiness:{"0000000001":{financial_report_date:"2026-09-30",financial_anchor:"2026-10-01",source_selection_as_of:"2026-10-25",verified_through:"2026-11-13"}}};
 data.rows[0].as_of="2026-11-13";
 f.priceDisplayResult(data);
 assert.match(host("#price-context").textContent,/가격 기준 2026-11-13 · 기업별 재무 확인 2026-11-13 \(기존 금융 화면 2026-10-25\)/);
 assert.match(host("#price-query-result").innerHTML,/재무기간 말 2026-09-30 · 공시 선택 기준 2026-10-25 · 재무 확인 2026-11-13/);
 assert.doesNotMatch(host("#price-query-result").innerHTML,/재무기간 말 2026-10-01/);
 data.definitions.per.family="PRICE_RETURN";f.priceDisplayResult(data);
 assert.doesNotMatch(host("#price-query-result").innerHTML,/재무기간 말/);
});

test("past valuation series rows keep their own evidence dates without the current anchor caption",()=>{
 const {f}=fixture();
 const data={...result("29.22"),mode:"series",price_as_of:"2026-11-13",definitions:{per:{label:"PER",family:"VALUATION"}},
  company_financial_readiness:{"0000000001":{financial_report_date:"2026-09-30",source_selection_as_of:"2026-11-13",verified_through:"2026-11-13"}}};
 const past={...data.rows[0],as_of:"2026-10-23",share_measurement_date:"2026-06-30"};
 const oldMarkup=f.priceRowsMarkup({...data,rows:[past]});
 assert.match(oldMarkup,/주식 수 측정 2026-06-30/);
 assert.doesNotMatch(oldMarkup,/재무기간 말 2026-09-30|공시 선택 기준|재무 확인/);
 const current={...past,as_of:"2026-11-13",share_measurement_date:"2026-09-30",status:"UNAVAILABLE",value:null,reason:"FINANCIAL_INPUT_NOT_BOUND"};
 assert.match(f.priceRowsMarkup({...data,rows:[current]}),/재무기간 말 2026-09-30/);
 const withoutShareDate={...past};delete withoutShareDate.share_measurement_date;
 assert.match(f.priceRowsMarkup({...data,rows:[withoutShareDate]}),/재무기간은 입력 근거에서 확인/);
 assert.doesNotMatch(f.priceRowsMarkup({...data,rows:[withoutShareDate]}),/재무기간 말 2026-09-30/);
});

test("reopened source dates never inherit active newer company readiness",async()=>{
 const saved={kind:"RESULT",operation:"query",request:{metric_ids:["per"]},title:"Old",note:"original",publication_id:"A",
  result:{...result("10","A"),price_as_of:"2026-10-23",requested_as_of:"2026-11-16",staleness_calendar_days:24}};
 const {f,host}=fixture({api:async()=>saved});
 f.state.capability.company_financial_readiness={"0000000001":{verified_through:"2026-11-13",financial_report_date:"2026-09-30",source_selection_as_of:"2026-11-13"}};
 await f.priceReopen("saved-A");
 assert.match(host("#price-context").textContent,/실제 거래일 2026-10-23/);
 assert.doesNotMatch(host("#price-context").textContent,/기업별 재무 확인 2026-11-13/);
 assert.doesNotMatch(host("#price-query-result").innerHTML,/재무 확인 2026-11-13/);
});

test("old export schema stays exact while only new readiness publications add source context",()=>{
 let exported;
 const {f,host}=fixture({Blob:class {constructor(parts){exported=JSON.parse(parts.join(""))}},
  URL:{createObjectURL:()=>"blob:local",revokeObjectURL:()=>{}},document:{createElement:()=>({click(){}})}});
 const old=result("10","A");f.state.operation="query";f.state.request={metric_ids:["per"]};host("#price-note").value="memo";
 f.priceDisplayResult(old);f.priceExport();
 assert.equal(JSON.stringify(exported),JSON.stringify({schema_version:"price-worksheet-export-v1",operation:"query",request:{metric_ids:["per"]},result:old,definition_context:old.definitions,note:"memo"}));
 const fresh={...result("20","B"),price_as_of:"2026-11-13",requested_as_of:"2026-11-16",staleness_calendar_days:3,
  company_financial_readiness:{"0000000001":{source_selection_as_of:"2026-10-25",verified_through:"2026-11-13"}}};
 f.priceDisplayResult(fresh);f.priceExport();
 assert.equal(exported.source_context.price_as_of,"2026-11-13");
 assert.equal(exported.source_context.company_financial_readiness["0000000001"].source_selection_as_of,"2026-10-25");
 assert(!("rows" in exported.source_context));
});

test("current EPS evaluation is labelled separately from quote and past daily readiness",()=>{
 const {f,host}=fixture();
 const evaluation={mode:"CURRENT_EVALUATION_WITH_LAGGED_QUOTE",evaluation_as_of:"2026-11-16",quote_session:"2026-11-13",backtest_eligible:false};
 const current={...result("26","B"),price_as_of:"2026-11-13",requested_as_of:"2026-11-16",staleness_calendar_days:3,current_eps_evaluation:evaluation};
 current.rows[0]={...current.rows[0],as_of:"2026-11-13",current_eps_evaluation:evaluation};
 f.priceDisplayResult(current);
 assert.match(host("#price-context").textContent,/현재 EPS 평가 2026-11-16 \/ 종가 2026-11-13/);
 assert.match(host("#price-query-result").innerHTML,/직접 4분기 EPS 합계/);
 assert.match(host("#price-query-result").innerHTML,/과거 준비 시점 검증 아님/);
 const past={...current,mode:"series",rows:[{...result().rows[0],as_of:"2026-11-13",status:"UNAVAILABLE",value:null,reason:"INPUT_AFTER_PRICE_AS_OF"}]};
 f.priceDisplayResult(past);
 assert.doesNotMatch(host("#price-query-result").innerHTML,/직접 4분기 EPS 합계/);
 assert.match(host("#price-context").textContent,/과거 시계열은 당시 준비 기준/);
});

test("reopened current EPS evidence preserves original evaluation, four direct sources and HON hold",async()=>{
 let exported;
 const evaluation={evaluation_as_of:"2026-11-16",quote_session:"2026-11-13"};
 const original={...result("26","B"),current_eps_evaluation:evaluation};
 const {f,host}=fixture({Blob:class {constructor(parts){exported=JSON.parse(parts.join(""))}},URL:{createObjectURL:()=>"blob:x",revokeObjectURL:()=>{}},document:{createElement:()=>({click(){}})},
  api:async(url,options)=>options?{publication_id:"B",evidence_context:"B-context",definitions:{per:{label:"PER"}},
   row:{metric_id:"per",current_eps_evaluation:evaluation},financial_inputs:[{role:"diluted_eps_12m",source_kind:"GOVERNED_DIRECT_QTD_TTM",value:"19.16",known_on:"2026-10-28",ready_on:"2026-11-16",ready_at:"2026-11-16T08:00:00Z",period_start:"2025-10-01",period_end:"2026-10-01"}],
   reported_quarter_sources:{q4:{input_ref:{kind:"OFFICIAL_REPORTED_HTML_TABLE"},reported_comparison_record:{start:"2026-04-01",end:"2026-07-01",value:"4.81"}}},
   eps_diagnostic:{reason:"PER_SHARE_BASIS_MISMATCH"},diagnostic_evidence:[{affected_original_quarters:[{start:"2025-10-01",end:"2026-01-01"},{start:"2026-01-01",end:"2026-04-01"}]}]}:
   {kind:"RESULT",operation:"query",request:{metric_ids:["per"]},title:"B",note:"original",publication_id:"B",result:original,evidence_context:"B-context",source_context:{price_as_of:"2026-11-13",requested_as_of:"2026-11-16",staleness_calendar_days:3,current_eps_evaluation:evaluation}}});
 f.state.capability.current_eps_evaluation={evaluation_as_of:"2026-11-20",quote_session:"2026-11-19"};
 await f.priceReopen("B-save");await f.priceShowEvidence("0000000001","B-per");
 assert.match(host("#price-context").textContent,/2026-11-16 \/ 종가 2026-11-13/);assert.doesNotMatch(host("#price-context").textContent,/2026-11-20/);
 assert.match(host("#price-evidence-content").innerHTML,/공식 실적표 · GAAP 희석 EPS/);assert.match(host("#price-evidence-content").innerHTML,/4.81/);
 assert.match(host("#price-evidence-content").innerHTML,/분기 EPS의 주당 기준이 다릅니다/);assert.match(host("#price-evidence-content").innerHTML,/2025-10-01–2026-01-01/);
 f.priceExport();assert.equal(exported.source_context.current_eps_evaluation.evaluation_as_of,"2026-11-16");
});
