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

test("financial board ratios use multiples in the exact value and accessible label",()=>{
  const h=harness(()=>{});
  const markup=vm.runInContext('profileBoardValue("1.255",{unit_kind:"RATIO",unit:"1"},"",true)',h.context);
  assert.match(markup,/title="1\.255 배"/);
  assert.match(markup,/aria-label="1\.26 배"/);
  assert.match(markup,/공표값 1\.255 배/);
  assert.doesNotMatch(markup,/%/);
});

test("financial profile board requests only selected definitions, reuses ordering and discards a closed reply",async()=>{
  const pending=new Map();
  const h=harness(url=>{
    if(url==="/api/financial-growth")return {configured:false};
    const id=new URLSearchParams(url.split("?")[1]).get("metric_id");
    const request=deferred();pending.set(id,request);return request.promise;
  });
  prepared(h);
  h.state.profileBasis="QUARTERLY";
  h.S.defaultDataset.publication_id="P";
  const asOf="2026-10-25",company={cik:"1"},quarter=inventory.spine[0];
  h.S.profile={company,financial_as_of:asOf};
  const defs=[
    {metric_id:"quarter_revenue",unit_kind:"MONEY",unit:"USD"},
    {metric_id:"quarter_revenue_yoy",unit_kind:"PERCENT",unit:"PERCENT"},
    {metric_id:"quarter_cfo",unit_kind:"MONEY",unit:"USD"},
    {metric_id:"quarter_cfo_yoy",unit_kind:"PERCENT",unit:"PERCENT"},
  ].map(definition=>({...definition,observation_basis:"QTD_3M",definition_version:"v1"}));
  h.context.boardFixture={defs,company,asOf,quarter};
  const {model,update,change,points,growth}=vm.runInContext(`(()=>{
    renderFinancialProfileBoard=()=>{};
    const {defs,company,asOf,quarter}=boardFixture;
    const definitions=new Map(defs.map(definition=>[definition.metric_id,definition]));
    const selection=createProfileBoard(["quarter_revenue","quarter_cfo"]);
    const context={basis:"QUARTERLY",end:"2026Q2",dataset:"current50",publication:"P",financialAsOf:asOf,
      companies:[company],spine:[quarter]};
    const model={profile:S.profile,definitions,selection,context,slots:companyTrendSlots(context,[]),series:new Map(),key:explorerContextKey()};
    financialProfileBoard=model;
    return {model,update:updateFinancialProfileBoard,change:changeProfileBoard,points:financialProfilePoints,growth:financialProfileGrowth};
  })()`,h.context);
  assert.equal(growth("quarter_cfo",model.definitions),null);
  assert.equal(growth("quarter_revenue",model.definitions).metric_id,"quarter_revenue_yoy");
  update(model);
  assert.deepEqual([...pending.keys()],["quarter_revenue","quarter_revenue_yoy","quarter_cfo"]);
  change(model.selection,"quarter_cfo","up");update(model);
  assert.equal(h.calls.length,4);
  const resolve=id=>{
    const definition=model.definitions.get(id);
    pending.get(id).resolve({metric:definition,observations:[{
      ...observation("0"),metric_id:id,cik:"1",unit:definition.unit,selection_as_of_date:asOf,
      period_class:"QTD_3M",end_convention:"EXCLUSIVE",definition_version:"v1",
    }]});
  };
  resolve("quarter_revenue");resolve("quarter_revenue_yoy");
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(points(model,defs[0])[0].value,"0");
  assert.equal(points(model,defs[1])[0].value,"0");
  h.closeProfile();resolve("quarter_cfo");
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(model.series.get("quarter_cfo").loading,true);
  assert.equal(h.calls.length,4);
});

test("growth sidecar drops stale company replies and reuses verified bytes for the same scope",async()=>{
  const response=deferred();
  const scope={dataset_id:"current50",dataset_publication_id:"P",financial_as_of:"2026-10-25",cik:"1"};
  const h=harness(url=>url==="/api/financial-growth"?{configured:true,...scope}:response.promise);
  h.S.profile={company:{cik:"1"}};
  const setModel=()=>vm.runInContext(`(()=>{
    renderFinancialProfileBoard=()=>{};
    const model={profile:S.profile,context:{dataset:"current50",publication:"P",financialAsOf:"2026-10-25"},
      definitions:new Map([["cfo",{unit_kind:"MONEY"}]]),selection:{order:["cfo"]},slots:[{}],key:explorerContextKey()};
    financialProfileBoard=model;
    requestFinancialGrowth(model);
    return model;
  })()`,h.context);
  const old=setModel();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.calls.length,2);
  h.closeProfile();
  response.resolve({schema_version:"screening-financial-growth-v1",rule_version:"signed-prepared-financial-yoy-v1",
    ...scope,period_end_convention:"EXCLUSIVE",definitions:{},series:{}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(old.growth.loading,true);
  h.get("#company-profile").hidden=false;
  const reopened=setModel();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(reopened.growth.data.cik,"1");
  assert.equal(h.calls.length,2);
});

test("financial growth uses exact current amount and dates and reports sign states without numeric bars",()=>{
  const h=harness(()=>{});
  const {points,evidence,statuses}=vm.runInContext('({points:financialGrowthPoints,evidence:financialGrowthEvidence,statuses:financialGrowthPeriodStatuses})',h.context);
  const level={value:"1e3",period_start:"2025-01-01",period_end:"2026-01-01",fiscal_year:2025,observation_id:"new"};
  const row={current:{...level,value:"1000"},prior:{...level,value:"-50",observation_id:"old"},yoy:null,
    status:"POSITIVE_TURN",delta:"1050",basis_assurance:"ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"};
  const definition={metric_id:"cfo",definition_version:"v1"};
  const model={context:{basis:"ANNUAL"},slots:[{key:2025,label:"FY2025"}],growth:{data:{
    definitions:{cfo:{basis:"FY",definition_version:"v1"}},series:{cfo:{2025:row}},
  }}};
  const [turn]=points(model,definition,[{value:level.value,row:level}]);
  assert.equal(turn.value,null);
  assert.match(evidence(turn,true),/영업현금 순유입 전환.*1050 USD.*관측 old.*재작성 기준 검증 없음/s);
  assert.match(statuses([turn],model.slots,0),/aria-pressed="true".*FY2025.*영업현금 순유입 전환/s);
  const [mismatch]=points(model,definition,[{value:"1001",row:level}]);
  assert.equal(mismatch.evidence,undefined);
  assert.match(mismatch.reason,/금액 또는 실제 기간/);
  const [dateMismatch]=points(model,definition,[{value:level.value,row:{...level,period_end:"2026-01-02"}}]);
  assert.equal(dateMismatch.evidence,undefined);
  const [idMismatch]=points(model,definition,[{value:level.value,row:{...level,observation_id:"another-source"}}]);
  assert.equal(idMismatch.evidence,undefined);
});

test("negative expansion summary shows direction and magnitude while evidence retains the signed rate",()=>{
  const h=harness(()=>{});
  const evidence=vm.runInContext("financialGrowthEvidence",h.context);
  const reference={observation_id:"id",value:"-10",period_start:"2025-01-01",period_end:"2026-01-01"};
  const point={status:"영업손실 확대",evidence:{status:"NEGATIVE_MAGNITUDE_EXPANDED",
    negative_magnitude_change:"-941.860465",delta:"-2835000000",current:reference,prior:reference}};
  const summary=evidence(point);
  assert.match(summary,/영업손실 확대.*확대 규모 .*941\.9.* %/s);
  assert.doesNotMatch(summary,/-941\.86/);
  assert.match(evidence(point,true),/음수 규모 축소율 -941\.860465 %.*전년 절댓값 − 현재 절댓값/);
  point.status="영업현금 순유출 축소";
  point.evidence.status="NEGATIVE_MAGNITUDE_REDUCED";
  point.evidence.negative_magnitude_change="38.06";
  assert.match(evidence(point),/축소 규모 .*38\.1.* %/s);
});

test("board axes adapt to displayed sign ranges and columns retain a zero baseline",()=>{
  const h=harness(()=>{});
  const {domain,plot,tick,rate}=vm.runInContext('({domain:profileBoardDomain,plot:profileBoardPlot,tick:profileBoardTick,rate:BOARD_RATE})',h.context);
  assert(domain([98,101],false,"PERCENT").lower>0);
  assert(domain([-101,-98],false,"PERCENT").upper<0);
  assert.equal(domain([98,101],true,"PERCENT").lower,0);
  assert.equal(domain([-101,-98],true,"PERCENT").upper,0);
  assert(domain([-1,2],false,"PERCENT").ticks.includes(0));
  for(const value of [0,1,-1,1e-14]){
    const result=domain([value],false,"PERCENT");
    assert(result.lower<value&&value<result.upper);
    assert(Number.isFinite(result.step));
  }
  assert.equal(tick(0.00001,0.00001,{unit_kind:"PERCENT"}),tick(0.00002,0.00001,{unit_kind:"PERCENT"}));
  const chart={periods:[{label:"first"},{label:"second"},{label:"third"},{label:"fourth"}],
    series:[{color:0,label:rate.label,points:[{value:"3"},{value:"-2",connect:true},{value:null},{value:"0"}]}],
    definition:{unit_kind:"PERCENT"},label:"전년비"};
  const columns=plot({...chart,type:"COLUMN"});
  assert.match(columns,/board-grid board-zero/);
  assert.match(columns,/board-column-positive/);
  assert.match(columns,/board-column-negative/);
  assert.match(columns,/board-column-zero/);
  assert.match(columns,/<title>전년비 · first · 3 %<\/title>/);
  assert.doesNotMatch(columns,/class="board-line"|third ·/);
  assert.doesNotMatch(plot({...chart,type:"DOT"}),/class="board-line"/);
  assert.match(plot({...chart,type:"LINE"}),/class="board-line"/);
  const truncated=plot({...chart,type:"DOT",series:[{color:0,label:"Operating income",points:[{value:"101"}]}]});
  assert.match(truncated,/0 생략/);
});

test("comparison validates each metric through existing endpoint and prints actual/fiscal scopes",async()=>{
  const h=harness(url=>{const metric_id=new URLSearchParams(url.split("?")[1]).get("metric_id");return{calendar_year:2026,calendar_quarter:2,metric_id,rows:[{company:{cik:"1",name:"Alpha",ticker:"A"},observation:observation("109417000000")},{company:{cik:"2",name:"Beta",ticker:"B"},observation:observation(null,{availability_status:"UNAVAILABLE"})}]}});
  prepared(h);h.state.metrics=definitions.slice(0,32);h.S.explorerSelected=new Set(["1","2"]);await h.renderComparison();
  assert.equal(h.calls.length,1);assert.match(h.calls[0],/quarter-comparison/);assert.match(h.get("#comparison-result").innerHTML,/109,417/);assert.match(h.get("#comparison-result").innerHTML,/FY2026 Q3/);assert.match(h.get("#comparison-result").innerHTML,/class="missing"/);
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
  assert.equal((heading.match(/title="분기 2026-03-29 ~ 2026-06-27/g)||[]).length,2);
  assert.doesNotMatch(body,/2026-03-29/);
  assert.equal((body.match(/class="comparison-period-exception"/g)||[]).length,2);
  assert.match(body,/0[\s\S]*분기 2026-04-01 ~ 2026-06-27/);
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
  assert.match(heading,/Gamma<small[^>]+>[\s\S]*?실제 기간 확인 불가/);
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
  assert.equal((heading.match(/title="연간 2024-01-01 ~ 2024-12-31/g)||[]).length,3);
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

test("catalog comparison renders prepared percentage points and generic money states without browser arithmetic",()=>{
  const h=harness(()=>{});
  const {points,eligible,value,pp,status,evidence}=vm.runInContext('({points:financialGrowthPoints,eligible:financialComparisonEligible,value:profileBoardValue,pp:BOARD_PP,status:financialGrowthStatus,evidence:financialGrowthEvidence})',h.context);
  assert(eligible({unit_kind:"MONEY"}));assert(eligible({unit_kind:"PERCENT"}));assert(!eligible({unit_kind:"RATIO"}));
  const definition={metric_id:"current_ratio",unit_kind:"PERCENT",definition_version:"v1"};
  const row={value:"120.125",period_start:null,period_end:"2025-01-01",fiscal_year:2024};
  const model={context:{basis:"ANNUAL"},slots:[{key:"2024"}],growth:{data:{rule_version:"catalog-prepared-financial-comparison-v2",
    definitions:{current_ratio:{basis:"FY",definition_version:"v1",comparison_kind:"PERCENTAGE_POINT"}},
    series:{current_ratio:{2024:{status:"CHANGE_AVAILABLE",current:{...row,observation_id:"x"},change_pp:"-0.00001",yoy:null}}}}}};
  const result=points(model,definition,[{value:row.value,row}]);
  assert.equal(result[0].value,"-0.00001");
  result[0].evidence.prior={...row,value:"120.12501",observation_id:"prior"};
  result[0].formula="current - prior";
  assert.match(evidence(result[0],true),/현재 비율 − 전년 비율 · current - prior/);
  assert.doesNotMatch(evidence(result[0]),/변화 공식/);
  assert.match(value(result[0].value,pp),/aria-label="&gt;-0.1 %p"/);
  assert.match(value(result[0].value,pp),/title="-0.00001 %p"/);
  assert.equal(status("cash","NEGATIVE_TURN"),"음수 전환");
  assert.equal(status("cash","NEGATIVE_MAGNITUDE_EXPANDED"),"음수 규모 확대");
  assert.equal(points(model,definition,[{value:"120",row}])[0].value,null);
});

test("ledger preserves all metrics and missing reasons while plots share compact period labels and rounded ticks",()=>{
  const h=harness(()=>{}),{ledger,plot}=vm.runInContext('({ledger:profileMetricLedger,plot:profileBoardPlot})',h.context);
  const markup=ledger([{label:"안정성",metrics:[{definition:{metric_id:"cash",label:"현금",unit_kind:"MONEY"},observation:{value:"123456789"}},
    {definition:{metric_id:"fcf",label:"표준화 FCF",unit_kind:"MONEY"},observation:{value:null,reason_labels:["자료 부족"]}}]}]);
  assert.equal((markup.match(/class="profile-ledger-row"/g)||[]).length,2);
  assert.match(markup,/현금/);assert.match(markup,/자료 부족/);assert.doesNotMatch(markup,/profile-card/);
  const chart={periods:[{label:"FY2023"},{label:"FY2024"}],series:[{color:0,label:"정확값",points:[{value:"0.00001"},{value:"0.00002"}]}],
    definition:{unit_kind:"PERCENT"},label:"비율"};
  const full=plot(chart),compact=plot({...chart,showPeriods:false});
  assert.match(full,/viewBox="0 0 570 154"/);assert.match(compact,/viewBox="0 0 570 134"/);
  assert.doesNotMatch(compact,/class="board-x"/);assert.match(compact,/<title>정확값 · FY2024 · 0.00002 %/);
  const labels=[...full.matchAll(/class="board-y"[^>]*>([^<]+)/g)].map(match=>match[1]);
  assert.equal(labels.length,new Set(labels).size);assert.match(full,/같은 반올림 눈금/);
});

test("sortable headers are native buttons with current order and explicit next action",()=>{
  const h=harness(()=>{}),header=vm.runInContext('explorerSortHeader',h.context);
  assert.match(header("company","기업명","기업"),/scope="col" aria-sort="ascending"/);
  assert.match(header("company","기업명","기업"),/type="button"[^>]*data-explorer-sort="company"[^>]*aria-label="기업명: 내림차순 정렬"/);
  assert.match(header("quarter_revenue","매출","매출","백만 달러"),/aria-sort="none".*내림차순 정렬/s);
  h.get("#explorer-sort").value="quarter_revenue";h.get("#explorer-direction").value="desc";
  assert.match(header("quarter_revenue","매출"),/aria-sort="descending".*오름차순 정렬/s);
  assert.match(header("company","기업명"),/aria-sort="none".*오름차순 정렬/s);
  assert.match(header("quarter_revenue","매출"),/aria-hidden="true">↓/);
});

test("header sorting synchronizes interim dropdowns and retains exact missing-last rules and scope",async()=>{
  const data=snapshot();data.rows.push(row("3",null,"Missing"));
  const h=harness(()=>data);prepared(h);
  h.get("#explorer-sort").options=["company","quarter_revenue","ttm_revenue"].map(value=>({value}));
  const sort=vm.runInContext('sortExplorerByHeader',h.context);
  h.S.explorerSelected.add("1");await h.loadExplorer();
  await sort("quarter_revenue");
  assert.equal(h.get("#explorer-direction").value,"desc");
  assert.equal(h.get("#explorer-sort").value,"quarter_revenue");
  assert.equal(h.state.visibleRows.map(r=>r.company.cik).join(),"1,2,3");
  assert.match(h.get("#explorer-head").innerHTML,/aria-sort="descending"[^>]*title="quarter_revenue"/);
  await sort("quarter_revenue");
  assert.equal(h.get("#explorer-direction").value,"asc");
  assert.equal(h.state.visibleRows.map(r=>r.company.cik).join(),"2,1,3");
  await sort("company");assert.equal(h.get("#explorer-direction").value,"asc");
  await sort("company");assert.equal(h.get("#explorer-direction").value,"desc");
  assert.equal(h.state.views.QUARTERLY.sort,"company");assert.equal(h.state.views.QUARTERLY.direction,"desc");
  assert.equal(h.S.explorerSelected.has("1"),true);assert.equal(h.state.periods.QUARTERLY,"2026Q2");
  h.state.basis="TTM";await sort("ttm_revenue");
  assert.equal(h.get("#explorer-direction").value,"desc");
  assert.equal(h.state.views.TTM.sort,"ttm_revenue");assert.equal(h.calls.length,1);
  await sort("period");assert.equal(h.get("#explorer-sort").value,"ttm_revenue");
});

test("annual header sort uses the existing API and preserves query latest year and selected companies",async()=>{
  const h=harness(()=>({rows:[],fiscal_years:[{fiscal_year:2024,companies_prepared:2}],selected_fiscal_year:2024,default_fiscal_year:2024,
    company_count:2,selected_year_company_count:2,financial_as_of:"2026-10-25"}));
  h.S.explorerCatalog={metrics:core.map(metric_id=>({metric_id,label:metric_id,unit_kind:"MONEY"}))};h.S.explorerCatalogKey="current50:2024";
  h.get("#explorer-sort").options=["company",...core].map(value=>({value}));h.get("#explorer-query").value="Alpha";
  h.S.explorerSelected.add("1");h.state.latestAnnual=true;
  const sort=vm.runInContext('sortExplorerByHeader',h.context);
  await sort("net_income");await sort("net_income");
  const params=h.calls.map(url=>new URLSearchParams(url.split("?")[1]));
  assert.equal(params[0].get("sort"),"net_income");assert.equal(params[0].get("direction"),"desc");
  assert.equal(params[1].get("direction"),"asc");
  for(const query of params){assert.equal(query.get("latest"),"true");assert.equal(query.get("query"),"Alpha")}
  assert.equal(h.S.explorerSelected.has("1"),true);assert.equal(h.S.explorerYear,2024);
  assert.match(h.get("#explorer-head").innerHTML,/aria-sort="ascending"[^>]*title="net_income"/);
  assert.doesNotMatch(h.get("#explorer-head").innerHTML,/data-explorer-sort="(?:period|selection)"/);
});

test("header rerender binds click and restores only an already focused header",async()=>{
  const h=harness(()=>{});prepared(h);h.state.metrics=definitions;
  const render=vm.runInContext('renderExplorerHeaders',h.context);
  const document=vm.runInContext('document',h.context);let focused=0;
  const button={dataset:{explorerSort:"quarter_revenue"},focus(options){focused++;assert.equal(options.preventScroll,true)}};
  document.querySelectorAll=selector=>selector==='[data-explorer-sort]'?[button]:[];
  document.activeElement={dataset:{explorerSort:"quarter_revenue"}};
  render(["quarter_revenue"],"실제 기간",false);
  assert.equal(focused,1);assert.equal(typeof button.onclick,"function");
  document.activeElement=h.get("#explorer-sort");render(["quarter_revenue"],"기간",false);assert.equal(focused,1);
  // A native button supplies Enter/Space activation; no custom key listener can double-toggle it.
  assert.match(h.get("#explorer-head").innerHTML,/<button type="button" class="explorer-header-sort"/);
});

test("financial catalog groups retain separate order, limits and all custom metric access",()=>{
  const h=harness(()=>{}),{groups,change,activate}=vm.runInContext('({groups:financialBoardGroups,change:changeProfileBoard,activate:activateFinancialBoardGroup})',h.context);
  const definitions=new Map(Array.from({length:13},(_,i)=>[`m${i}`,{label:`metric ${i}`,category:i<10?"PROFITABILITY":"CASH_FLOW"}]));
  const model={groups:groups(definitions,["m0","m10"])};
  vm.runInContext('financialProfileBoardHost={};renderProfileBoardSelection=()=>{};updateFinancialProfileBoard=()=>{}',h.context);
  activate(model,"CORE");assert.equal(model.selection.order.join(),"m0,m10");
  change(model.selection,"m0","down");
  activate(model,"PROFITABILITY");assert.equal(model.selection.order.length,8);
  change(model.selection,"m9","add");assert.equal(model.selection.order.length,8);
  change(model.selection,"m0","remove");change(model.selection,"m9","add");change(model.selection,"m9","up");
  const profit=model.selection.order.join();
  activate(model,"CORE");assert.equal(model.selection.order.join(),"m10,m0");
  activate(model,"CUSTOM");assert.equal(model.groups.get("CUSTOM").options.length,13);
  change(model.selection,"m12","add");
  activate(model,"PROFITABILITY");assert.equal(model.selection.order.join(),profit);
  activate(model,"CUSTOM");assert.equal(model.selection.order.join(),"m0,m10,m12");
  assert.equal(h.get("#financial-board-group-label").textContent,"현재 그룹: 사용자 선택");
  assert.equal(model.groups.get("OTHER_REPORTED").options.length,0);
});

test("adaptive plot geometry keeps exact points and legible compact paired dimensions",()=>{
  const h=harness(()=>{}),{plot,x,width}=vm.runInContext('({plot:profileBoardPlot,x:profileBoardPeriodX,width:financialBoardPlotWidth})',h.context);
  assert.equal(x(0,8),94);assert.equal(x(7,8),542);
  for(const available of [330,760,1212,1668,2308]){
    const pixels=width({clientWidth:available});assert(pixels>=320&&pixels<650);
    const svg=plot({periods:Array.from({length:8},(_,i)=>({label:`2025Q${i%4+1}`,short:`25Q${i%4+1}`})),
      series:[{id:"item",label:"Full item",color:0,points:Array.from({length:8},(_,i)=>({value:String(i-2),connect:true}))}],
      definition:{unit_kind:"PERCENT"},label:"growth",width:pixels,height:108,type:"COLUMN"});
    assert.match(svg,new RegExp(`viewBox="0 0 ${pixels} 108"`));assert.match(svg,/class="board-adaptive"/);
    assert.doesNotMatch(svg,/NaN|Infinity/);assert.match(svg,/Full item · 2025Q1 · -2 %/);
    assert(x(7,8,pixels)<pixels);
  }
});

test("nearby context escapes labels, explains missing and revenue denominator or same-filing scope",()=>{
  const h=harness(()=>{}),{line,legend,context}=vm.runInContext('({line:profileBoardContextLine,legend:profileBoardLegend,context:revenueBoardContext})',h.context);
  const missing=line('<unsafe name>',"FY2024",null,{unit_kind:"PERCENT"},"검토 필요 <raw>","분모 설명");
  assert.match(missing,/&lt;unsafe name&gt;/);assert.match(missing,/검토 필요 &lt;raw&gt;/);assert.doesNotMatch(missing,/<unsafe/);
  assert.match(legend([{id:'"x',label:"Full long name",color:0}]),/data-board-item="&quot;x"/);
  h.context.testBoard={periods:[{label:"FY2024"}],view:{periods:[{period_start:"2024-01-01",period_end:"2025-01-01"}]},
    visible:[{id:"x",label:"Complete source label",points:{amount:[{value:"123456789",reason:"missing"}],yoy:[{value:"12.345",reason:"missing"}],share:[{value:"45.678",reason:"missing",basis:"고정 지역 범위"}]}}]};
  vm.runInContext('revenueBreakdowns.board=testBoard',h.context);
  assert.match(context("x",0,"share"),/Complete source label[\s\S]*45.7[\s\S]*비중 분모: 고정 지역 범위/);
  assert.match(context("x",0,"yoy"),/같은 공시의 전년 비교값/);
  assert.match(context(null,0,"amount"),/123456789 USD/);
});

test("chart interaction links hover and keyboard periods, pins until Escape and rejects stale context",()=>{
  const h=harness(()=>{});vm.runInContext('window={addEventListener(){}}',h.context);
  const bind=vm.runInContext('bindProfileBoardPeriod',h.context),events={},attributes=new Map();
  let active=0,key="company1",valid=true,prevented=0,stopped=0,canvasFocus=0;
  const context={hidden:true,innerHTML:""},classes=new Set();
  const item={dataset:{boardItem:"item"},classList:{toggle(name,on){on?classes.add(name):classes.delete(name)},remove(name){classes.delete(name)}}};
  const canvas={focus(){canvasFocus++},parentElement:{querySelector(){return context}},closest(selector){return selector===".board-plot-canvas"?this:selector==="[data-financial-card]"?{dataset:{financialCard:"item"}}:null}};
  const target=index=>({closest(selector){
    if(selector==="[data-board-period]")return{dataset:{boardPeriod:String(index)}};
    if(selector==="[data-board-item]")return item;
    if(selector===".board-plot-canvas")return canvas;
    if(selector==="[data-board-period],.board-plot-canvas,[data-board-item]")return this;
    return null;
  }});
  const host={addEventListener(name,handler){events[name]=handler},setAttribute(k,v){attributes.set(k,v)},removeAttribute(k){attributes.delete(k)},
    querySelectorAll(selector){return selector===".board-context"?[context]:selector==="[data-board-item]"||selector===".board-item-active"?[item]:[]},contains(){return false}};
  bind(host,index=>{active=index},()=>active,{key:()=>key,valid:()=>valid,count:()=>4,describe:(id,index)=>`${id} period${index}`});
  events.pointerover({target:target(2),pointerType:"mouse"});assert.equal(active,2);assert.equal(context.hidden,false);assert(classes.has("board-item-active"));
  events.click({target:target(2)});assert.equal(attributes.get("data-board-pinned"),"true");assert.equal(canvasFocus,1);
  events.pointerover({target:target(1),pointerType:"mouse"});assert.equal(active,2);assert.match(context.innerHTML,/period2/);
  const escape=()=>events.keydown({key:"Escape",target:canvas,preventDefault(){prevented++},stopPropagation(){stopped++}});
  escape();assert.equal(context.hidden,true);assert.equal(prevented,1);assert.equal(stopped,1);escape();assert.equal(stopped,1);
  events.keydown({key:"ArrowRight",target:canvas,preventDefault(){}});assert.equal(active,3);
  events.keydown({key:" ",target:canvas,preventDefault(){}});assert.equal(attributes.get("data-board-pinned"),"true");
  key="company2";events.pointerover({target:target(1),pointerType:"mouse"});assert.equal(active,1);
  valid=false;events.pointerover({target:target(0),pointerType:"mouse"});assert.equal(context.hidden,true);assert.equal(active,1);
});

test("pinned context and active legend or canvas survive DOM replacement with refreshed data",()=>{
  for(const kind of ["legend","canvas","close"]){
    const h=harness(()=>{});vm.runInContext('window={addEventListener(){}}',h.context);
    const bind=vm.runInContext('bindProfileBoardPeriod',h.context),document=vm.runInContext('document',h.context),events={};
    let active=1,scope="company1",order="item",version=1,dom;
    const attributes=new Map(),root={contains:node=>[dom.legend,dom.canvas,dom.close].includes(node)};
    function makeDOM(){
      const context={hidden:true,innerHTML:""},classes={toggle(){},remove(){}};
      const panel={dataset:{boardMode:"amount"},closest(){return null},querySelector(selector){return selector===".board-context"?context:selector===".board-plot-canvas"?canvas:selector==="[data-board-clear]"?close:null},querySelectorAll(){return[legend]}};
      const closest=(self,selector)=>selector==="[data-board-mode]"?panel:selector==="button[data-board-item]"&&self===legend?legend:
        selector==="[data-board-item]"&&self===legend?legend:selector===".board-plot-canvas"&&self===canvas?canvas:
        selector==="[data-board-clear]"&&self===close?close:selector===".financial-board-card,.revenue-board-plot"?panel:
        selector==="[data-board-period],.board-plot-canvas,[data-board-item]"&&self!==close?self:null;
      const legend={dataset:{boardItem:"item"},classList:classes,closest(selector){return closest(this,selector)},focus(){document.activeElement=this;events.focusin?.({target:this})}};
      const canvas={parentElement:panel,closest(selector){return closest(this,selector)},focus(){document.activeElement=this;events.focusin?.({target:this})}};
      const close={closest(selector){return closest(this,selector)},focus(){document.activeElement=this;events.focusin?.({target:this})}};
      return{context,panel,legend,canvas,close};
    }
    dom=makeDOM();
    const host={addEventListener(name,fn){events[name]=fn},removeAttribute(key){attributes.delete(key)},setAttribute(key,value){attributes.set(key,value)},
      querySelectorAll(selector){return selector===".board-context"?[dom.context]:selector==="[data-board-mode]"?[dom.panel]:selector==="[data-board-item]"||selector===".board-item-active"?[dom.legend]:[]},querySelector(){return dom.context},contains:root.contains};
    bind(host,index=>{active=index},()=>active,{valid:()=>true,key:()=>scope,order:()=>order,items:()=>order?order.split(","):[],count:()=>4,defaultMode:"amount",describe:(item,index,mode)=>`${item}:${index}:${mode}:version${version}`});
    events.click({target:dom.legend});document.activeElement=dom[kind];
    assert.equal(dom.context.hidden,false);const saved=host.profileBoardInteraction.beforeRender(root);
    dom=makeDOM();document.activeElement={};version=2;
    host.profileBoardInteraction.afterRender(saved);
    assert.equal(dom.context.hidden,false);assert.match(dom.context.innerHTML,/item:1:amount:version2/);
    assert.equal(document.activeElement,dom[kind]);assert.equal(attributes.get("data-board-pinned"),"true");
    events.pointerover({target:dom.canvas,pointerType:"mouse"});assert.match(dom.context.innerHTML,/version2/);
    // Programmatic focus after Escape and another render is not a new request for explanation.
    events.keydown({key:"Escape",target:dom.canvas,preventDefault(){},stopPropagation(){}});
    assert.equal(dom.context.hidden,true);
    const cleared=host.profileBoardInteraction.beforeRender(root);dom=makeDOM();document.activeElement={};
    host.profileBoardInteraction.afterRender(cleared);
    assert.equal(dom.context.hidden,true);assert.equal(attributes.has("data-board-pinned"),false);
    assert.equal(document.activeElement,dom[kind]);
    events.click({target:dom.legend});document.activeElement=dom[kind];
    // A newly loaded company or changed selection cannot reuse the previous pin.
    const next=host.profileBoardInteraction.beforeRender(root);scope="company2";order="";dom=makeDOM();
    host.profileBoardInteraction.afterRender(next);assert.equal(dom.context.hidden,true);assert.equal(attributes.has("data-board-pinned"),false);
  }
});

test("all revenue comparison contexts and financial growth include their prepared actual dates",()=>{
  const h=harness(()=>{}),{revenue,financial}=vm.runInContext('({revenue:revenueBoardContext,financial:financialBoardContext})',h.context);
  const period={period_start:"2024-01-01",period_end:"2025-01-01",end_convention:"EXCLUSIVE",fiscal_year:2024};
  h.context.testRevenue={periods:[{label:"FY2024"}],view:{periods:[period]},visible:[{id:"x",label:"Item",points:{
    amount:[{value:"100"}],yoy:[{value:"2"}],share:[{value:"3",basis:"연결 매출"}]}}]};
  vm.runInContext('revenueBreakdowns.board=testRevenue',h.context);
  for(const mode of ["amount","yoy","share"])assert.match(revenue("x",0,mode),/2024-01-01/);
  const definition={metric_id:"cfo",unit_kind:"MONEY",definition_version:"v1"},row={...period,value:"100",metric_observation_id:"id"};
  h.context.testFinancial={definitions:new Map([["cfo",definition]]),context:{basis:"ANNUAL"},slots:[{key:2024,label:"FY2024"}],series:new Map([["cfo",{rows:[row]}]]),
    growth:{data:{definitions:{cfo:{basis:"FY",definition_version:"v1"}},series:{cfo:{2024:{current:{...period,value:"100",observation_id:"id"},prior:{...period,value:"50"},status:"RATE_AVAILABLE",yoy:"100",delta:"50"}}}}}};
  vm.runInContext('financialProfileBoard=testFinancial',h.context);
  assert.match(financial("cfo",0,"growth"),/2024-01-01/);
});

test("union profile growth validates owner capability and preserves parent header",async()=>{
  const requested={dataset_id:"union",dataset_publication_id:"union-P",financial_as_of:"2026-10-25",cik:"0000000001"};
  const parent={dataset_id:"old50",dataset_publication_id:"old-P",financial_as_of:requested.financial_as_of,dataset_manifest_sha256:"1".repeat(64)};
  const union={...requested,dataset_manifest_sha256:"9".repeat(64)};delete union.cik;
  const envelope={schema_version:"screening-auxiliary-owner-response-v1",request_scope:{...union,cik:requested.cik},source_scope:parent,
    owner_proof:{cik:requested.cik,union_manifest_sha256:union.dataset_manifest_sha256,source_manifest_sha256:parent.dataset_manifest_sha256},
    data:{...parent,cik:requested.cik,schema_version:"screening-financial-growth-v1",rule_version:"signed-prepared-financial-yoy-v1",period_end_convention:"EXCLUSIVE",definitions:{},series:{}}};
  const h=harness(url=>url==="/api/financial-growth"?{configured:true,...parent,owner_contexts:[{request_scope:union,source_scope:parent,available_ciks:[requested.cik]}]}:envelope);
  h.S.defaultDataset={...union,publication_id:union.dataset_publication_id,auxiliary_manifest_sha256:union.dataset_manifest_sha256};
  h.S.profile={company:{cik:requested.cik}};
  const model=vm.runInContext(`(()=>{renderFinancialProfileBoard=()=>{};const model={profile:S.profile,context:{dataset:"union",publication:"union-P",financialAsOf:"2026-10-25"},definitions:new Map([["cfo",{unit_kind:"MONEY"}]]),selection:{order:["cfo"]},slots:[{}],key:explorerContextKey()};financialProfileBoard=model;requestFinancialGrowth(model);return model})()`,h.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(model.growth.data.dataset_id,"old50");assert.equal(model.growth.data.auxiliary_owner.request_scope.dataset_id,"union");
  assert.equal(h.calls.length,2);
});

test("union company without owner asset keeps levels and does not fetch another parent's growth",async()=>{
  const h=harness(()=>({configured:true,dataset_id:"old50",dataset_publication_id:"old-P",financial_as_of:"2026-10-25",owner_contexts:[{request_scope:{dataset_id:"union",dataset_publication_id:"union-P",financial_as_of:"2026-10-25",dataset_manifest_sha256:"9".repeat(64)},available_ciks:["0000000001"]}]}));
  h.S.defaultDataset={dataset_id:"union",publication_id:"union-P",auxiliary_manifest_sha256:"9".repeat(64)};
  h.S.profile={company:{cik:"0000000002"}};
  const model=vm.runInContext(`(()=>{renderFinancialProfileBoard=()=>{};const model={profile:S.profile,context:{dataset:"union",publication:"union-P",financialAsOf:"2026-10-25"},definitions:new Map([["cfo",{unit_kind:"MONEY"}]]),selection:{order:["cfo"]},slots:[{}],key:explorerContextKey()};financialProfileBoard=model;requestFinancialGrowth(model);return model})()`,h.context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(model.growth.error,/수준 값/);assert.equal(h.calls.length,1);assert.equal(model.slots.length,1);
});
