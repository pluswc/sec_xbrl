"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const test=require("node:test");
const source=fs.readFileSync(path.resolve(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
function node(value=""){
  return{value,hidden:false,innerHTML:"",textContent:"",options:[],selectedOptions:[],classList:{toggle(){}},setAttribute(){},replaceChildren(){this.innerHTML="";this.textContent=""},focus(){},scrollIntoView(){},closest(){return node()},remove(){}};
}
function harness(respond){
  const nodes=new Map(),calls=[],profileButtons=[];
  const get=selector=>{if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector)};
  for(const selector of ["#explorer-sort","#explorer-direction","#explorer-preset"]){const element=get(selector);element.value=selector.endsWith("sort")?"company":selector.endsWith("direction")?"asc":"CORE"}
  get("#comparison-metrics").selectedOptions=[{value:"quarter_revenue"}];
  const context=vm.createContext({URLSearchParams,location:{search:""},Node:{TEXT_NODE:3},document:{querySelector:get,querySelectorAll:selector=>selector==="[data-profile-cik]"?profileButtons:[]},fetch:async(url)=>{calls.push(url);const value=await respond(url);return{ok:true,json:async()=>value}}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  const app=vm.runInContext("({state:explorerBasis,S,switchExplorerBasis,chooseExplorerPeriod,preparedExplorerObservation,compareExplorerDecimals,filterSortExplorerRows,cachedExplorerSnapshot,loadExplorer,invalidateExplorerDetails,openAnnualProfile,openProfile,closeProfile,showView,showCompanyProfile,loadRevenueBreakdowns,renderComparison,renderProfileTrend,interimMetricIds,ensureExplorerInventory,batchView,applyBatchChoice,screeningPeriodPolicy,availabilityCaption})",context);
  app.S.defaultDataset={dataset_id:"current50"};app.S.explorerYear=2024;
  return{...app,get,calls,context,profileButtons};
}
const core=["revenue","revenue_yoy","operating_margin","net_income","cfo","standardized_fcf","current_ratio","liabilities_to_assets"];
const quarterIds=[...core,...Array.from({length:24},(_,i)=>`extra${i}`)].map(id=>"quarter_"+id);
const ttmIds=["revenue","operating_income","net_income","cfo","standardized_fcf","gross_margin","operating_margin","net_margin","fcf_margin"].map(id=>"ttm_"+id);
const definitions=[...quarterIds,...ttmIds].map(metric_id=>({metric_id,label:metric_id,observation_basis:metric_id.startsWith("ttm_")?"TTM":"QTD_3M",unit_kind:"MONEY",unit:"USD",category:"OTHER_REPORTED"}));
function observation(value,extra={}){return{availability_status:"AVAILABLE",value,calendar_year:2026,calendar_quarter:2,fiscal_year:2026,fiscal_quarter:"Q3",period_start:"2026-03-29",period_end:"2026-06-28",...extra}}
function row(cik,value,name=cik){return{company:{cik,name,ticker:name,sic_description:"Semiconductors"},metrics:Object.fromEntries(definitions.map(metric=>[metric.metric_id,observation(value)]))}}
function snapshot(quarter=2){return{calendar_year:2026,calendar_quarter:quarter,financial_as_of:"2026-10-25",metrics:definitions,rows:[row("1","9007199254740993","Alpha"),row("2","9007199254740992","Beta")]}}
const inventory={spine:[{calendar_year:2026,calendar_quarter:2},{calendar_year:2026,calendar_quarter:3}],rows:[{cik:"1",calendar_year:2026,calendar_quarter:2,bucket_status:"PERIOD_AVAILABLE"},{cik:"2",calendar_year:2026,calendar_quarter:2,bucket_status:"PERIOD_AVAILABLE"},{cik:"1",calendar_year:2026,calendar_quarter:3,bucket_status:"PERIOD_AVAILABLE"},{cik:"2",calendar_year:2026,calendar_quarter:3,bucket_status:"NO_FILING_AS_OF_CUTOFF"}]};
function prepared(h){h.state.inventoryKey="current50";h.state.inventoryPromise=Promise.resolve(inventory);h.state.periods.QUARTERLY="2026Q2";h.state.periods.TTM="2026Q2";h.state.basis="QUARTERLY"}
function deferred(){let resolve,reject;const promise=new Promise((done,fail)=>{resolve=done;reject=fail});return{promise,resolve,reject}}

test("choose latest fully prepared bucket, or latest partial without hardcoded dates",()=>{
  const h=harness(()=>{});assert.equal(h.chooseExplorerPeriod(inventory).selected.calendar_quarter,2);
  const partial=structuredClone(inventory);partial.rows=partial.rows.filter(item=>!(item.cik==="2"&&item.calendar_quarter===2));
  assert.equal(h.chooseExplorerPeriod(partial).selected.calendar_quarter,3);
  assert.equal(h.chooseExplorerPeriod({spine:[],rows:[]}).selected,undefined);
});

test("filter and exact sorting retain all missing/block rows last in either direction",()=>{
  const h=harness(()=>{}),rows=[row("1","9007199254740993","Beta"),row("2","9007199254740992","Alpha"),row("3",null,"Gamma"),row("4","999999999999999999999","Delta")];
  rows[3].metrics.quarter_revenue.quality_blocking=true;
  assert.deepEqual(Array.from(h.filterSortExplorerRows(rows,"","quarter_revenue","asc"),item=>item.company.cik),["2","1","4","3"]);
  assert.deepEqual(Array.from(h.filterSortExplorerRows(rows,"","quarter_revenue","desc"),item=>item.company.cik),["1","2","4","3"]);
  assert.equal(h.filterSortExplorerRows(rows,"semiconductors","company","asc").length,4);
  assert.equal(h.compareExplorerDecimals("-1.0000000000000001","-1.0000000000000002")>0,true);
  assert.equal(h.preparedExplorerObservation(observation("0")).value,"0");
  assert.equal(h.preparedExplorerObservation(observation("1",{availability_status:"UNAVAILABLE"})).value,null);
  assert.equal(rows[3].metrics.quarter_revenue.value,"999999999999999999999");
});

test("one bucket snapshot serves query/sort/preset and quarter-to-TTM with separate annual state",async()=>{
  const h=harness(url=>{const q=new URLSearchParams(url.split("?")[1]),value=snapshot(Number(q.get("calendar_quarter"))||2);value.calendar_year=Number(q.get("calendar_year"))||2026;return value});prepared(h);const annualCatalog={metrics:[{metric_id:"revenue"}]};h.S.explorerCatalog=annualCatalog;
  await h.loadExplorer();assert.equal(h.state.metrics.length,32);
  h.get("#explorer-query").value="alpha";await h.loadExplorer();
  h.get("#explorer-query").value="";h.get("#explorer-sort").value="quarter_revenue";await h.loadExplorer();
  h.state.basis="TTM";h.invalidateExplorerDetails();h.get("#explorer-preset").value="ALL";await h.loadExplorer();
  assert.equal(h.state.metrics.length,9);assert.equal(h.calls.length,1);assert.equal(h.S.explorerYear,2024);assert.equal(h.S.explorerCatalog,annualCatalog);
  for(const [preset,count] of [["CORE",5],["GROWTH_PROFIT",6],["CASH_STABILITY",3],["ALL",9]]){h.get("#explorer-preset").value=preset;assert.equal(h.interimMetricIds().length,count)}
  await h.cachedExplorerSnapshot("current50","2025Q4");await h.cachedExplorerSnapshot("current50","2025Q3").catch(()=>{});
  assert(h.state.snapshots.size<=2);
});

test("stale quarter responses never overwrite a later basis/bucket",async()=>{
  const a=deferred(),b=deferred(),h=harness(url=>url.includes("calendar_quarter=2")?a.promise:b.promise);prepared(h);
  const first=h.loadExplorer();await Promise.resolve();
  h.state.basis="TTM";h.state.periods.TTM="2026Q3";h.invalidateExplorerDetails();h.get("#explorer-preset").value="ALL";
  const second=h.loadExplorer();await Promise.resolve();b.resolve(snapshot(3));await second;a.resolve(snapshot(2));await first;
  assert.equal(h.state.snapshot.calendar_quarter,3);assert.match(h.get("#explorer-count").textContent,/2026Q3 TTM/);
});

test("annual profile and interim comparison responses cannot cross changed contexts",async()=>{
  const pending=deferred(),h=harness(()=>pending.promise);h.S.profile={sentinel:true};
  const profile=h.openAnnualProfile("1",{});h.state.basis="TTM";h.invalidateExplorerDetails();pending.resolve({});await profile;
  assert.equal(h.S.profile.sentinel,true);
  const comparison=deferred(),c=harness(()=>comparison.promise);prepared(c);c.S.explorerSelected=new Set(["1","2"]);
  const request=c.renderComparison();c.state.basis="TTM";c.invalidateExplorerDetails();comparison.resolve({});await request;
  assert.equal(c.get("#comparison-result").innerHTML,"");assert.equal(c.get("#comparison-panel").hidden,true);
});

test("inline profile returns focus to the current company row or search after a rerender",()=>{
  const h=harness(()=>{});
  const row=node(),trigger=node(),focus=[];
  trigger.dataset={profileCik:"1"};
  trigger.closest=()=>row;
  trigger.focus=()=>focus.push("company");
  trigger.setAttribute=(key,value)=>{if(key==="aria-expanded")trigger.expanded=value};
  h.get("#explorer-query").focus=()=>focus.push("search");
  h.get("#company-profile").focus=()=>focus.push("profile");
  h.S.profile={company:{cik:"1"}};
  h.profileButtons.push(trigger);
  h.showCompanyProfile();
  assert.equal(trigger.expanded,"true");
  h.closeProfile();
  assert.equal(trigger.expanded,"false");
  h.showCompanyProfile();
  h.profileButtons.pop();
  h.closeProfile();
  assert.deepEqual(focus,["profile","company","profile","search"]);
});

test("leaving explorer closes the inline profile and drops its pending revenue response",async()=>{
  const pending=deferred(),h=harness(()=>pending.promise);
  h.S.defaultDataset.publication_id="publication";
  h.S.profile={company:{cik:"1"},financial_as_of:"2026-10-25"};
  const request=h.loadRevenueBreakdowns();
  assert.equal(h.calls.length,1);
  h.showView("library");
  pending.resolve({dataset_id:"current50",dataset_publication_id:"publication",financial_as_of:"2026-10-25",cik:"1",schema_version:"screening-revenue-breakdowns-v1"});
  await request;
  assert.equal(h.get("#company-profile").hidden,true);
  assert.equal(h.get("#profile-revenue-breakdowns").hidden,true);
  assert.equal(h.get("#revenue-breakdown-content").hidden,true);
  assert.equal(h.get("#revenue-breakdown-status").textContent,"");
});

test("comparison validates each metric through existing endpoint and prints actual/fiscal scopes",async()=>{
  const h=harness(url=>{const metric_id=new URLSearchParams(url.split("?")[1]).get("metric_id");return{calendar_year:2026,calendar_quarter:2,metric_id,rows:[{company:{cik:"1",name:"Alpha",ticker:"A"},observation:observation("109417000000")},{company:{cik:"2",name:"Beta",ticker:"B"},observation:observation(null,{availability_status:"UNAVAILABLE"})}]}});
  prepared(h);h.state.metrics=definitions.slice(0,32);h.S.explorerSelected=new Set(["1","2"]);await h.renderComparison();
  assert.equal(h.calls.length,1);assert.match(h.calls[0],/quarter-comparison/);assert.match(h.get("#comparison-result").innerHTML,/109,417.0/);assert.match(h.get("#comparison-result").innerHTML,/FY2026 Q3/);assert.match(h.get("#comparison-result").innerHTML,/class="missing"/);
});


test("fixed comparison shows quarter dates once with explicit exceptions, instant basis and zero",async()=>{
  const ids=["quarter_revenue","quarter_cfo","quarter_net_income","quarter_debt","quarter_capex"];
  const h=harness(url=>{
    const id=new URLSearchParams(url.split("?")[1]).get("metric_id");
    const companies=[{cik:"1",name:"Alpha",ticker:"A"},{cik:"2",name:"Beta",ticker:"B"}];
    return {calendar_year:2026,calendar_quarter:2,metric_id:id,rows:companies.map((company,index)=>{
      let item=observation("1000000");
      if(id==="quarter_net_income"&&index===0)item=observation("0",{period_start:"2026-04-01"});
      if(id==="quarter_debt")item=observation("1000000",{period_class:"INSTANT",period_start:null,period_end:index===0?"2026-06-28":"2026-06-27"});
      if(id==="quarter_capex")item=observation(null,{availability_status:"UNAVAILABLE",reason:"REQUIRED_ITEM_NOT_IN_PREPARED_DATA"});
      return {company,observation:item};
    })};
  });
  prepared(h);h.S.explorerSelected=new Set(["1","2"]);
  h.state.metrics=ids.map(metric_id=>({metric_id,label:metric_id,unit_kind:"MONEY",unit:"USD",observation_basis:metric_id==="quarter_debt"?"INSTANT":"QTD_3M"}));
  h.get("#comparison-metrics").selectedOptions=ids.map(value=>({value}));
  await h.renderComparison();
  const [heading,body]=h.get("#comparison-result").innerHTML.split("<tbody>");
  assert.match(heading,/Alpha · A/);
  assert.equal((heading.match(/분기 2026-03-29 ~ 2026-06-27/g)||[]).length,2);
  assert.doesNotMatch(body,/2026-03-29/);
  assert.equal((body.match(/class="comparison-period-exception"/g)||[]).length,2);
  assert.match(body,/0\.0[\s\S]*분기 2026-04-01 ~ 2026-06-27/);
  assert.match(body,/기말 기준[\s\S]*기준일 2026-06-26/);
  assert.match(body,/aria-label="자료 없음: 준비 자료에서 항목을 확인할 수 없음"/);
});

test("latest TTM comparison uses TTM spans, anchor-only dates and no conflicted date",async()=>{
  const id="ttm_revenue",anchor={...observation(null,{period_end:"2026-07-01"}),bucket_status:"PERIOD_AVAILABLE"};
  const h=harness(()=>({period_scope:"LATEST_COMPANY",metric_id:id,rows:[
    {company:{cik:"1",name:"Alpha"},period:anchor,observation:observation("1200000",{period_class:"TTM",period_start:"2025-07-01",period_end:"2026-07-01"})},
    {company:{cik:"2",name:"Beta"},period:anchor,observation:observation(null,{availability_status:"UNAVAILABLE",reason:"INPUTS_NOT_COMPATIBLE"})},
    {company:{cik:"3",name:"Gamma"},period:{...anchor,bucket_status:"PERIOD_CONFLICT",period_end:"2026-06-20"},observation:null},
  ]}));
  prepared(h);h.state.basis="TTM";h.state.periods.TTM="LATEST";
  h.state.metrics=definitions.filter(metric=>metric.metric_id===id);h.S.explorerSelected=new Set(["1","2","3"]);
  h.get("#comparison-metrics").selectedOptions=[{value:id}];
  await h.renderComparison();
  const [heading,body]=h.get("#comparison-result").innerHTML.split("<tbody>");
  assert.match(h.calls[0],/latest=true/);
  assert.match(heading,/TTM 2025-07-01 ~ 2026-06-30/);
  assert.match(heading,/기준 종료일 2026-06-30/);
  assert.match(heading,/Gamma<small[^>]+>실제 기간 확인 불가/);
  assert.doesNotMatch(heading,/2026-03-29|2026-06-19/);
  assert.doesNotMatch(body,/comparison-period-exception/);
  assert.match(body,/aria-label="자료 없음: 분기 합계 조건을 충족하지 않음"/);
});

test("annual comparison honors legacy context-end conventions and displays a differing instant",async()=>{
  const id="debt",metric={metric_id:id,label:"부채",period_class:"INSTANT",unit_kind:"MONEY",unit:"USD"};
  const h=harness(()=>({selected_fiscal_year:2024,date_limitation:"기간 주의",companies:[{cik:"1",name:"Alpha"},{cik:"2",name:"Beta"},{cik:"3",name:"Gamma"}],
    actual_periods:{
      "1":{period_start:"2024-01-01",context_end_date:"2024-12-31"},
      "2":{period_start:"2024-01-01",period_end:"2025-01-01"},
      "3":{period_start:"2024-01-01",context_end_date:"2025-01-01",context_end_convention:"SOURCE_CONTEXT_END_EXCLUSIVE"},
    },
    rows:[{metric,values:{"1":observation("0",{period_end:"2025-01-01",period_class:"INSTANT",fiscal_year:2024,fiscal_quarter:null}),"2":observation("1",{period_end:"2024-12-29",period_class:"INSTANT",fiscal_year:2024,fiscal_quarter:null})}}]}));
  h.S.explorerSelected=new Set(["1","2","3"]);h.get("#comparison-metrics").selectedOptions=[{value:id}];
  await h.renderComparison();
  const [heading,body]=h.get("#comparison-result").innerHTML.split("<tbody>");
  assert.equal((heading.match(/연간 2024-01-01 ~ 2024-12-31/g)||[]).length,3);
  assert.equal((body.match(/class="comparison-period-exception"/g)||[]).length,1);
  assert.match(body,/기준일 2024-12-28/);
});

test("unsupported quarter inventory disables interim modes with a local explanation",async()=>{
  const h=harness(()=>{throw new Error("not supported")});
  h.get("#explorer-basis").options=[{value:"ANNUAL"},{value:"QUARTERLY"},{value:"TTM"}];
  assert.equal(await h.ensureExplorerInventory(),null);
  assert.equal(h.state.basis,"ANNUAL");
  assert.equal(h.get("#explorer-basis").options[0].disabled,false);
  assert.equal(h.get("#explorer-basis").options[1].disabled,true);
  assert.match(h.get("#explorer-message").textContent,/연간/);
});

test("lazy profile series rejects old metric responses and labels eight calendar buckets",async()=>{
  const first=deferred(),second=deferred(),h=harness(url=>url.includes("metric_id=quarter_revenue")?first.promise:second.promise);prepared(h);
  h.state.profileBasis="QUARTERLY";h.state.profileKey="current50:QUARTERLY:2026Q2";
  h.S.profile={company:{cik:"1"},groups:[{metrics:definitions.slice(0,32).map(definition=>({definition}))}],series:{}};
  h.get("#profile-metric").value="quarter_revenue";const a=h.renderProfileTrend();
  h.get("#profile-metric").value="quarter_cfo";const b=h.renderProfileTrend();
  second.resolve({observations:Array.from({length:8},(_,index)=>observation(index===7?null:"40",{calendar_year:2025+Math.floor(index/4),calendar_quarter:index%4+1}))});await b;
  const current=h.get("#profile-series").innerHTML;
  first.resolve({observations:[observation("999")]});await a;
  assert.equal(h.get("#profile-series").innerHTML,current);
  assert.equal(h.S.profile.series.quarter_revenue,undefined);
  assert.equal((h.get("#profile-series").innerHTML.match(/<tr>/g)||[]).length,9);
  assert.equal((h.get("#profile-chart").innerHTML.match(/class="value-label"/g)||[]).length,2);
  assert.match(h.get("#profile-chart").innerHTML,/<tspan[^>]*>Q/);
  assert.match(h.get("#profile-series").innerHTML,/FY2026 Q3/);
});


test("late annual detail failures stay out of the new explorer context",async()=>{
  const a=deferred(),h=harness(()=>a.promise);
  const request=h.openProfile("1",{});h.state.basis="TTM";h.invalidateExplorerDetails();
  a.reject(new Error("old annual profile failure"));await request;
  assert.equal(h.get("#explorer-message").textContent,"");
  const b=deferred(),c=harness(()=>b.promise);c.S.explorerSelected=new Set(["1","2"]);
  c.get("#comparison-metrics").selectedOptions=[{value:"revenue"}];
  const comparison=c.renderComparison();c.state.basis="QUARTERLY";c.invalidateExplorerDetails();
  b.reject(new Error("old annual comparison failure"));await comparison;
  assert.equal(c.get("#comparison-result").innerHTML,"");
});


for(const order of ["old-first","new-first"])test(`basis switch continuation cannot override a newer same-basis period (${order})`,async()=>{
  const q2=deferred(),q3=deferred(),h=harness(url=>url.includes("calendar_quarter=2")?q2.promise:q3.promise);prepared(h);
  h.state.basis="TTM";h.state.snapshot=snapshot(2);h.state.metrics=definitions.slice(32);
  h.state.views.QUARTERLY.sort="quarter_revenue";
  h.get("#explorer-sort").options=[{value:"company"},{value:"quarter_revenue"}];
  h.get("#explorer-basis").value="QUARTERLY";
  const switching=h.switchExplorerBasis();
  for(let turn=0;turn<20&&!h.calls.some(url=>url.includes("calendar_quarter=2"));turn++)await Promise.resolve();
  assert(h.calls.some(url=>url.includes("calendar_quarter=2")),"Q2 must already be in flight before selecting Q3");
  h.state.periods.QUARTERLY="2026Q3";h.invalidateExplorerDetails();
  h.get("#explorer-sort").value="company";const latest=h.loadExplorer();await Promise.resolve();
  if(order==="old-first"){
    q2.resolve(snapshot(2));await switching;
    assert.match(h.get("#explorer-body").innerHTML,/불러오는 중/);
    assert.equal(h.get("#explorer-sort").value,"company");
    q3.resolve(snapshot(3));await latest;
  }else{
    q3.resolve(snapshot(3));await latest;
    q2.resolve(snapshot(2));await switching;
  }
  assert.equal(h.get("#explorer-sort").value,"company");
  assert.equal(h.state.readyKey,"current50:QUARTERLY:2026Q3");
  assert.match(h.get("#explorer-count").textContent,/2026Q3 분기/);
});

test("failed basis load leaves the error and never rerenders retained quarterly data as TTM",async()=>{
  const h=harness(()=>{throw new Error("synthetic network failure")});prepared(h);
  h.state.snapshot=snapshot(2);h.state.metrics=definitions.slice(0,32);h.state.readyKey="current50:QUARTERLY:2026Q2";
  h.get("#explorer-basis").value="TTM";
  await h.switchExplorerBasis();
  assert.equal(h.state.readyKey,null);
  assert.match(h.get("#explorer-message").textContent,/synthetic network failure/);
  assert.match(h.get("#explorer-body").innerHTML,/표시할 수 없습니다/);
  assert.doesNotMatch(h.get("#explorer-body").innerHTML,/Alpha/);
  assert.doesNotMatch(h.get("#explorer-head").innerHTML,/quarter_revenue/);
});


test("unverified actual batch does not issue a prepared simulation request or enable a new condition",async()=>{
  const h=harness(()=>{throw new Error("no verified batch was eligible on the selected date")});
  h.batchView.enabled=true;h.get("#batch-mode").value="ACTUAL";
  await h.applyBatchChoice();
  assert.equal(h.calls.length,1);assert.match(h.calls[0],/mode=ACTUAL&lag=0/);
  assert.equal(h.batchView.snapshot,null);assert.equal(h.get("#batch-use-screen").disabled,true);
  assert.match(h.get("#batch-status").textContent,/확인된 실제 배치가 없습니다/);
});

test("latest query and saved policy use anchored data, while fixed quarter remains selectable",async()=>{
  const h=harness(()=>({...snapshot(),period_scope:"LATEST_COMPANY"}));
  const value=await h.cachedExplorerSnapshot("current50","LATEST");
  assert.equal(value.period_scope,"LATEST_COMPANY");assert.match(h.calls[0],/latest=true/);
  const pinned={mode:"ACTUAL",dataset_id:"current50",publication_id:"p",financial_as_of:"2026-10-25",ready_at:"2026-11-06T19:00:00Z",decision_date:"2026-11-06",lag:0};
  h.S.screenAvailability=pinned;h.get("#dataset").value="current50";
  h.get("#frequency").value="QUARTERLY";h.get("#period-mode").value="LATEST_COMPANY_QUARTER_V1";
  const policy=h.screeningPeriodPolicy();assert.equal(policy.mode,"LATEST_COMPANY_QUARTER_V1");
  assert.deepEqual(JSON.parse(JSON.stringify(policy.availability)),pinned);assert.match(h.availabilityCaption(pinned),/확보 기록 기준/);
  h.get("#period-mode").value="FIXED_CALENDAR_QUARTER_END";h.get("#calendar-quarter").value="2026Q2";
  const fixed=h.screeningPeriodPolicy();assert.equal(fixed.calendar_quarter,2);assert.equal(fixed.availability.publication_id,"p");
  h.S.screenAvailability=null;assert.equal(h.screeningPeriodPolicy().availability,undefined);
  h.S.screenAvailability=pinned;
  h.get("#period-mode").value="LATEST_COMPANY_QUARTER_V1";h.get("#dataset").value="different";
  assert.throws(()=>h.screeningPeriodPolicy(),/조회 배치/);
});


test("applied source stays distinct from draft and lookup failure retains the prior matrix",async()=>{
  const pinned={mode:"ACTUAL",dataset_id:"current50",publication_id:"p",financial_as_of:"2026-10-25",ready_at:"2026-11-06T19:00:00Z",decision_date:"2026-11-06",lag:0};
  const h=harness(()=>{throw new Error("no verified batch was eligible on the selected date")});
  h.batchView.enabled=true;h.batchView.snapshot=pinned;
  h.get("#batch-mode").value="ACTUAL";h.get("#batch-date").value="2026-11-07";h.get("#batch-lag").value="1";
  h.get("#batch-applied-summary").textContent=h.availabilityCaption(pinned);
  h.get("#explorer-body").innerHTML="<tr>직전 적용 자료</tr>";
  const prior=h.get("#batch-applied-summary").textContent;
  await h.applyBatchChoice({focus:true});
  assert.match(h.calls[0],/decision_date=2026-11-07&lag=1/);
  assert.equal(h.get("#batch-applied-summary").textContent,prior);
  assert.equal(h.get("#explorer-body").innerHTML,"<tr>직전 적용 자료</tr>");
  assert.equal(h.batchView.snapshot,pinned);assert.equal(h.get("#batch-editor").open,true);
  assert.match(h.get("#batch-status").textContent,/자료 기준을 유지/);
});

test("source selection folds only after a ready matrix and distinguishes a later table failure",async()=>{
  const pinned={mode:"PREPARED_SIMULATION",dataset_id:"current50",publication_id:"p",financial_as_of:"2026-10-25"};
  const h=harness(()=>pinned);
  h.batchView.enabled=true;h.batchView.datasets=[{dataset_id:"current50",publication_id:"p"}];
  h.get("#batch-mode").value="PREPARED_SIMULATION";h.get("#batch-dataset").value="current50";
  vm.runInContext("loadExplorer = async()=>{explorerBasis.readyKey=explorerContextKey()}; ensureExplorerInventory=()=>null",h.context);
  await h.applyBatchChoice();
  assert.equal(h.get("#batch-editor").open,false);
  assert.equal(h.get("#batch-applied-summary").textContent,"적용 중 · 준비된 자료로 가정");
  assert.match(h.get("#batch-applied-meta").textContent,/2026-10-25.*실제 확보 이력 미반영/);
  assert.equal(h.get("#batch-use-screen").hidden,false);
  assert.equal(h.get("#batch-status").textContent,"");
  vm.runInContext("loadExplorer = async()=>{explorerBasis.readyKey=null}",h.context);
  await h.applyBatchChoice();
  assert.equal(h.get("#batch-editor").open,true);
  assert.match(h.get("#batch-status").textContent,/기업표를 불러오지 못했습니다/);
  assert.doesNotMatch(h.get("#batch-status").textContent,/유지/);
});
