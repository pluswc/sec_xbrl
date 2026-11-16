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
 const f=vm.runInNewContext(formatting+snippet+"\n({state:priceWorksheet,priceExecute,priceInvalidate,priceValue,priceSave,priceReopen,priceQuery,priceScopeMatchesCurrent,priceRowsMarkup,priceShowEvidence,priceDisplayResult,priceDefinitionLabel,priceExport,priceTimelineMarkup,priceTimelineReadout,priceTimelineQuery,priceTimelineBind})",env);
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

function timelineResult(){
 const ratio=(day,value)=>({metric_id:"pbr_bps",observation_id:"ratio-"+day,cik:"1",status:value===null?"UNAVAILABLE":"AVAILABLE",value,reason:value===null?"MISSING":null});
 return {publication_id:"pinned",mode:"timeline",company:{cik:"1",ticker:"REAL"},diagnostic:true,
  timeline_parameters:{metric:"pbr_bps",multiples:["2"],view_years:3,window:"252s"},definitions:{},rows:[],
  points:["2026-01-01","2026-01-02","2026-01-03"].map((day,i)=>({as_of:day,close:String(10+i),currency:"USD",
   ratio:ratio(day,i===1?null:String(2+i)),reason:i===1?"MISSING":null,
   denominator:{observation_id:i===2?"new":"old",value:"5",currency:"USD",known_on:day,period_end:day},
   bands:[{user_multiple:"2",value:i===1?null:"10",status:i===1?"UNAVAILABLE":"AVAILABLE",reason:"MISSING"}],
   distribution:{status:"UNAVAILABLE",reason:"INSUFFICIENT",valid_sessions:i,expected_sessions:252,minimum_eligible_sessions:252,percentiles:{},window_start:day,window_end:day}}))};
}

test("timeline markup retains real units, diagnostic status and missing ribbons",()=>{
 const {f}=fixture();const html=f.priceTimelineMarkup(timelineResult());
 assert.match(html,/REAL/);assert.match(html,/백테스트 부적격/);assert.match(html,/252거래일 이동창/);
 assert.match(html,/USD\/주/);assert.match(html,/공유 거래일/);assert.doesNotMatch(html,/class="timeline-ribbon/);
 assert.match(html,/timeline-denominator-event/);
});

test("one date cursor synchronizes both plots and missing counts/readiness stay visible",()=>{
 const cursors=[new Map(),new Map()];
 const {f,host}=fixture({$$:selector=>selector==="[data-timeline-cursor]"?cursors.map(c=>({setAttribute:(k,v)=>c.set(k,v)})):[]});
 f.state.result=timelineResult();f.priceTimelineReadout(1);
 assert.equal(cursors[0].get("x1"),504);assert.equal(cursors[1].get("x1"),504);
 assert.equal(host("#price-timeline-date").value,"1");assert.match(host("#price-timeline-readout").innerHTML,/1 \/ 252 · 252/);
 assert.match(host("#price-timeline-readout").innerHTML,/2026-01-02/);
 f.priceTimelineReadout(-20);assert.equal(f.state.timelineIndex,0);
 f.priceTimelineReadout(500);assert.equal(f.state.timelineIndex,2);
});

test("timeline refuses multi-company selection without choosing its first company",()=>{
 const {f,host}=fixture();f.state.selected=new Set(["1","2"]);f.priceTimelineQuery();
 assert.match(host("#price-feedback").textContent,/한 기업/);assert.equal(f.state.result,null);
});

test("keyboard range and pointer share the same readout function",()=>{
 let pointer;const cursors=[];
 const svg={getBoundingClientRect:()=>({left:0,width:1000}),set onpointermove(fn){pointer=fn}};
 const {f,host}=fixture({$$:s=>s==="[data-timeline-plot]"?[svg]:cursors});
 f.state.result=timelineResult();f.priceTimelineBind();
 host("#price-timeline-date").oninput({target:{value:"0"}});assert.equal(f.state.timelineIndex,0);
 pointer({clientX:504});assert.equal(f.state.timelineIndex,1);
});

test("stale timeline response cannot repaint newer company selection",async()=>{
 let resolve;const {f}=fixture({api:()=>new Promise(r=>resolve=r)});
 const pending=f.priceExecute("timeline",{cik:"1"});f.priceInvalidate();resolve(timelineResult());await pending;
 assert.equal(f.state.result,null);
});


test("multi-megabyte worker responses validate linearly with strict size/alphabet/padding",()=>{
 const payload=Buffer.from(JSON.stringify({points:"x".repeat(5*1024*1024)})).toString("base64");
 assert.equal(bridge.validWorkerBase64(payload),true);
 const mid=Math.floor(payload.length/2);
 assert.equal(bridge.validWorkerBase64(payload.slice(0,mid)+"!"+payload.slice(mid+1)),false);
 for(const bad of ["A===","AA=A","AAA","====","AA==AAAA","AA\n=","éééé"])
  assert.equal(bridge.validWorkerBase64(bad),false,bad);
 for(const good of ["","AA==","AAA=","AAAA"])assert.equal(bridge.validWorkerBase64(good),true,good);
 assert.equal(bridge.validWorkerBase64(Buffer.alloc(32*1024*1024).toString("base64")),true);
 assert.equal(bridge.validWorkerBase64(Buffer.alloc(32*1024*1024+1).toString("base64")),false);
});


test("fully unavailable lower timeline has an explained empty plot, no invented numeric axis",()=>{
 const {f}=fixture();const result=timelineResult();
 result.points.forEach(p=>{p.ratio.value=null;p.ratio.status="UNAVAILABLE";p.bands=[]});
 const html=f.priceTimelineMarkup(result);
 assert.match(html,/실제 배수·이동 분포 미준비/);
 const lower=html.slice(html.indexOf("실제 PBR · BPS와 이동 분포"));
 assert.doesNotMatch(lower,/<text x="8" y="48">1/);
});


test("successful explicit timeline scrolls analysis into view and provides conditions return",async()=>{
 let scrolls=0;const {f,host}=fixture({api:async()=>timelineResult()});
 host("#price-analysis-heading").scrollIntoView=()=>scrolls++;
 await f.priceExecute("timeline",{cik:"1"});
 assert.equal(scrolls,1);assert.match(host("#price-query-result").innerHTML,/href="#price-timeline-controls"/);
});


test("static timeline ledger resets inherited full-height sidebar and stacking rules",()=>{
 const css=fs.readFileSync(path.join(__dirname,"../../examples/screening/display-assets/app.css"),"utf8");
 const ledger=css.match(/\.timeline-layout \.timeline-readout\{([^}]+)\}/u)?.[1];
 assert(ledger);
 for(const property of ["position:static", "height:auto", "max-height:none", "min-height:0", "z-index:auto", "overflow:visible"])
  assert(ledger.split(";").includes(property),property);
});
