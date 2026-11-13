"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const test=require("node:test");
const source=fs.readFileSync(path.resolve(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
const bases=["revenue","operating_income","net_income","cfo","standardized_fcf"];
function definition(id,basis="ANNUAL"){return{metric_id:id,definition_version:basis+"-v1",unit_kind:"MONEY",unit:"USD",period_class:"FY",observation_basis:basis==="TTM"?"TTM":"QTD_3M",label:id}}
const annualDefinitions=bases.map(id=>definition(id));
const spine=Array.from({length:8},(_,index)=>{const ordinal=2024*4+3+index;return{calendar_year:Math.floor(ordinal/4),calendar_quarter:ordinal%4+1}});
function harness(respond){
  const nodes=new Map(),get=selector=>{
    if(!nodes.has(selector))nodes.set(selector,{value:"",hidden:false,textContent:"",innerHTML:"",disabled:false,setAttribute(){},replaceChildren(){this.innerHTML="";this.textContent=""},getBoundingClientRect(){return{width:390}},classList:{toggle(){}}});
    return nodes.get(selector);
  };
  const calls=[],context=vm.createContext({URLSearchParams,location:{search:""},Node:{TEXT_NODE:3},document:{querySelector:get,querySelectorAll:()=>[]},fetch:async url=>{calls.push(url);const value=await respond(url);return{ok:true,json:async()=>value}}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  const api=vm.runInContext("({state:companyTrend,basis:explorerBasis,S,companyTrendContext,validateCompanyTrendSeries,cachedCompanyTrendSeries,companyTrendSlots,alignCompanyTrend,companyTrendGeometry,renderCompanyTrendPlot,loadCompanyTrend,invalidateCompanyTrend})",context);
  api.S.defaultDataset={dataset_id:"D"};api.S.explorerSelected=new Set(["1","2"]);api.S.explorerYear=2025;
  api.S.explorerCatalog={metrics:annualDefinitions};api.S.explorer={dataset_publication_id:"P",financial_as_of:"2026-10-25",fiscal_years:[2022,2023,2024,2025].map(fiscal_year=>({fiscal_year})),rows:[{company:{cik:"1",ticker:"A",name:"Alpha"}},{company:{cik:"2",ticker:"B",name:"Beta"}}]};
  get("#comparison-trend-metric").value="revenue";api.basis.readyKey="D:ANNUAL:2025";
  return{...api,get,calls};
}
function annualRow(id,year,value){return{metric_id:id,definition_version:"ANNUAL-v1",fiscal_year:year,value,availability_status:value===null?"UNAVAILABLE":"AVAILABLE",period_start:`${year-1}-09-29`,period_end:`${year}-09-29`,reason_labels:value===null?["공표 값 없음"]:[]}}
function profile(cik="1",year=2025,dataset="D"){
  return{dataset_id:dataset,dataset_publication_id:"P",financial_as_of:"2026-10-25",selected_fiscal_year:year,company:{cik,ticker:cik==="1"?"A":"B",name:cik==="1"?"Alpha":"Beta"},prepared_years:[2022,2024,2025],groups:[{metrics:annualDefinitions.map(definition=>({definition}))}],series:Object.fromEntries(bases.map(id=>[id,[annualRow(id,2025,"500000000"),annualRow(id,2022,"100000000"),annualRow(id,2024,"300000000")]]))};
}
function interim(h,basis="QUARTERLY",end="2026Q2",metric="revenue"){
  h.basis.basis=basis;h.basis.periods[basis]=end;h.basis.inventory={spine};
  const prefix=basis==="TTM"?"ttm_":"quarter_";
  h.basis.metrics=bases.map(id=>definition(prefix+id,basis));h.basis.snapshot={financial_as_of:"2026-10-25",rows:h.S.explorer.rows};
  h.get("#comparison-trend-metric").value=prefix+metric;h.basis.readyKey=`D:${basis}:${end}`;
}
function quarterSeries(cik="1",metric="quarter_revenue"){
  const basis=metric.startsWith("ttm_")?"TTM":"QUARTERLY";
  return{metric:definition(metric,basis),observations:spine.map((coordinate,index)=>({cik,metric_id:metric,definition_version:basis+"-v1",unit:"USD",selection_as_of_date:"2026-10-25",period_class:basis==="TTM"?"TTM":"QTD_3M",...coordinate,fiscal_year:coordinate.calendar_year,fiscal_quarter:"Q"+(coordinate.calendar_quarter===2?3:coordinate.calendar_quarter),end_convention:"EXCLUSIVE",period_start:"2026-01-01",period_end:"2026-04-01",availability_status:index===7?"UNAVAILABLE":"AVAILABLE",value:index===7?null:String(index*1000000),source_lineage:{large:"not retained"}})).reverse()};
}
function deferred(){let resolve,reject;const promise=new Promise((done,fail)=>{resolve=done;reject=fail});return{promise,resolve,reject}}

test("annual coordinates preserve intermediate missing years and end at the selected fiscal year",()=>{
  const h=harness(()=>{}),context=h.companyTrendContext("revenue"),record=h.validateCompanyTrendSeries(context,"1",profile());
  const model=h.alignCompanyTrend(context,[record]);
  assert.deepEqual(Array.from(model.slots,item=>item.key),[2022,2023,2024,2025]);
  assert.deepEqual(Array.from(model.series[0].points,item=>item.observation.value),["100000000",null,"300000000","500000000"]);
  context.end=2024;assert.deepEqual(Array.from(h.companyTrendSlots(context,[record]),item=>item.key),[2022,2023,2024]);
  assert.equal(model.series[0].points[0].observation.period_start,"2021-09-29");
});

test("quarter and TTM use coordinate keys, selected-end windows and compact projections",()=>{
  for(const basis of ["QUARTERLY","TTM"]){
    const h=harness(()=>{});interim(h,basis);const metric=h.get("#comparison-trend-metric").value,context=h.companyTrendContext(metric),record=h.validateCompanyTrendSeries(context,"1",quarterSeries("1",metric)),model=h.alignCompanyTrend(context,[record]);
    assert.equal(model.slots.length,7);assert.equal(model.slots.at(-1).key,"2026Q2");
    assert.equal(model.series[0].points[0].observation.value,"0");
    assert.equal(model.series[0].points.at(-1).observation.fiscal_quarter,"Q3");
    assert.equal(record.rows.some(row=>Object.hasOwn(row,"source_lineage")),false);
    context.end="2026Q3";assert.equal(h.companyTrendSlots(context,[record]).length,8);
  }
});

test("scope and duplicate-coordinate mismatches fail closed for both source adapters",()=>{
  const h=harness(()=>{}),context=h.companyTrendContext("revenue");
  for(const mutate of [p=>p.company.cik="other",p=>p.dataset_id="other",p=>p.dataset_publication_id="other",p=>p.selected_fiscal_year=2024,p=>p.groups[0].metrics[0].definition.unit="EUR",p=>p.series.revenue.push(p.series.revenue[0])]){
    const value=structuredClone(profile());mutate(value);assert.throws(()=>h.validateCompanyTrendSeries(context,"1",value));
  }
  interim(h);const current=h.companyTrendContext("quarter_revenue");
  for(const mutate of [p=>p.metric.definition_version="other",p=>p.observations[0].cik="other",p=>p.observations[0].unit="EUR",p=>p.observations[0].selection_as_of_date="2026-01-01",p=>p.observations[0].metric_id="quarter_cfo",p=>p.observations[0].calendar_year=2020,p=>p.observations.push(p.observations[0])]){
    const value=quarterSeries();mutate(value);assert.throws(()=>h.validateCompanyTrendSeries(current,"1",value));
  }
});

test("negative and zero values share a labeled zero axis; missing/quality values break lines",()=>{
  const h=harness(()=>{});interim(h);const context=h.companyTrendContext("quarter_revenue"),payload=quarterSeries();
  payload.observations.find(row=>row.calendar_year===2026&&row.calendar_quarter===2).value="-5855000000";
  payload.observations.find(row=>row.calendar_year===2025&&row.calendar_quarter===2).quality_blocking=true;
  const record=h.validateCompanyTrendSeries(context,"1",payload),model=h.alignCompanyTrend(context,[record]),geometry=h.companyTrendGeometry(model,390);
  assert(geometry.min<0&&geometry.max>0);assert(geometry.ticks.includes(0));
  assert.equal(new Set(geometry.ticks).size,geometry.ticks.length);
  assert.equal(model.series[0].points.find(point=>point.slot.key==="2025Q2").observation.value,null);
  h.state.model=model;h.renderCompanyTrendPlot();const svg=h.get("#comparison-trend-chart").innerHTML;
  assert.match(svg,/>0<\/text>/);assert.match(svg,/-5,855/);
  assert.equal((svg.match(/<circle/g)||[]).length,6);
  assert.equal((svg.match(/<line x1=/g)||[]).length,4);
});

test("one point stays visible and all-missing clears the previous chart with an explanation",()=>{
  const h=harness(()=>{}),context=h.companyTrendContext("revenue"),payload=profile();payload.series.revenue.forEach(row=>row.value=null);payload.series.revenue[0].value="0";
  const record=h.validateCompanyTrendSeries(context,"1",payload);h.state.model=h.alignCompanyTrend(context,[record]);h.renderCompanyTrendPlot();
  assert.equal((h.get("#comparison-trend-chart").innerHTML.match(/<circle/g)||[]).length,1);
  payload.series.revenue[0].value=null;const empty=h.validateCompanyTrendSeries(context,"1",payload);h.state.model=h.alignCompanyTrend(context,[empty]);h.renderCompanyTrendPlot();
  assert.match(h.get("#comparison-trend-chart").innerHTML,/미제공은 0이 아닙니다/);assert.doesNotMatch(h.get("#comparison-trend-chart").innerHTML,/<svg/);
});

test("one annual profile supplies all five metrics; interim cache reuses windows and removes failures",async()=>{
  const h=harness(url=>{const q=new URLSearchParams(url.split("?")[1]);return profile(q.get("cik"),Number(q.get("fiscal_year")),q.get("dataset_id"))});
  for(const id of [...bases,"revenue"]){h.get("#comparison-trend-metric").value=id;await h.cachedCompanyTrendSeries(h.companyTrendContext(id),"1")}
  assert.equal(h.calls.length,1);
  for(let i=0;i<20;i++){h.S.defaultDataset.dataset_id="D"+i;h.basis.readyKey=`D${i}:ANNUAL:2025`;await h.cachedCompanyTrendSeries(h.companyTrendContext("revenue"),"1")}
  assert.equal(h.state.cache.size,16);
  let attempt=0;const q=harness(()=>{if(attempt++===0)throw new Error("first failure");return quarterSeries()});interim(q);
  await assert.rejects(q.cachedCompanyTrendSeries(q.companyTrendContext("quarter_revenue"),"1"));assert.equal(q.state.cache.size,0);
  await q.cachedCompanyTrendSeries(q.companyTrendContext("quarter_revenue"),"1");q.basis.periods.QUARTERLY="2026Q3";q.basis.readyKey="D:QUARTERLY:2026Q3";
  await q.cachedCompanyTrendSeries(q.companyTrendContext("quarter_revenue"),"1");assert.equal(q.calls.length,2);
});

test("partial company failures are explicit while successful published values and detail dates remain",async()=>{
  const h=harness(url=>{const q=new URLSearchParams(url.split("?")[1]);if(q.get("cik")==="2")throw new Error("company unavailable");return profile()});
  await h.loadCompanyTrend();
  assert.equal(h.state.model.series.length,2);assert.match(h.get("#comparison-trend-status").textContent,/1개 기업 조회 실패/);
  assert.match(h.get("#comparison-trend-legend").innerHTML,/company unavailable/);assert.match(h.get("#comparison-trend-values").innerHTML,/2021-09-29/);
  assert.match(h.get("#comparison-trend-values").innerHTML,/class="missing"/);
  const calls=h.calls.length;h.renderCompanyTrendPlot();h.renderCompanyTrendPlot();assert.equal(h.calls.length,calls);
});

test("late success/error after close or context change cannot repaint or reopen the trend",async()=>{
  for(const reject of [false,true]){
    const pending=deferred(),h=harness(()=>pending.promise),request=h.loadCompanyTrend();h.invalidateCompanyTrend();h.get("#comparison-panel").hidden=true;
    if(reject)pending.reject(new Error("late failure"));else pending.resolve(profile());await request;
    assert.equal(h.state.model,null);assert.equal(h.get("#comparison-trend-chart").innerHTML,"");assert.equal(h.get("#comparison-trend-status").textContent,"");assert.equal(h.get("#comparison-panel").hidden,true);
  }
  const pending=deferred(),h=harness(()=>pending.promise),request=h.loadCompanyTrend();h.basis.basis="TTM";h.invalidateCompanyTrend();pending.reject(new Error("old basis"));await request;assert.equal(h.state.model,null);
});

test("metric requests own their token; same-context filter loading does not discard the current trend",async()=>{
  const pending=new Map(),h=harness(url=>{const q=new URLSearchParams(url.split("?")[1]),cik=q.get("cik");if(!pending.has(cik))pending.set(cik,deferred());return pending.get(cik).promise});
  const old=h.loadCompanyTrend();h.get("#comparison-trend-metric").value="net_income";const current=h.loadCompanyTrend();h.basis.readyKey=null;
  for(const [cik,item]of pending)item.resolve(profile(cik));await Promise.all([old,current]);
  assert.equal(h.state.model.context.definition.metric_id,"net_income");assert.equal(h.calls.length,2);
});

test("latest trends request guarded series even after caching the same fixed coordinate",async()=>{
  const h=harness(url=>{
    const q=new URLSearchParams(url.split("?")[1]),p=profile(q.get("cik"));
    if(q.has("latest"))p.series.revenue.find(row=>row.fiscal_year===2025).value=null;
    return p;
  });
  const fixed=h.companyTrendContext("revenue");
  const old=await h.cachedCompanyTrendSeries(fixed,"1");
  assert.equal(old.rows.find(row=>row.fiscal_year===2025).value,"500000000");
  const latest={...fixed,ends:{"1":2025,"2":2025}};
  const held=await h.cachedCompanyTrendSeries(latest,"1");
  assert.equal(held.rows.find(row=>row.fiscal_year===2025).value,null);
  assert.match(h.calls.at(-1),/latest=true/);
  assert.doesNotMatch(h.calls.at(-1),/fiscal_year=/);
  assert.equal(h.calls.length,2);

  const q=harness(url=>{
    const payload=quarterSeries();
    const params=new URLSearchParams(url.split("?")[1]);
    const endpoint=payload.observations.find(row=>row.calendar_year===2026&&row.calendar_quarter===2);
    if(params.has("latest"))Object.assign(endpoint,{value:null,availability_status:"UNAVAILABLE",reason:"PERIOD_MISMATCH"});
    return payload;
  });
  interim(q);
  const context=q.companyTrendContext("quarter_revenue");
  await q.cachedCompanyTrendSeries(context,"1");
  const guarded={...context,ends:{"1":"2026Q2","2":"2026Q2"}};
  const result=await q.cachedCompanyTrendSeries(guarded,"1");
  const chart=q.alignCompanyTrend(guarded,[result]);
  assert.equal(chart.series[0].points.at(-1).observation.value,null);
  assert.match(q.calls.at(-1),/latest=true/);
  assert.equal(q.calls.length,2);
});

test("published latest coordinates extend only latest chart slots under the exact dataset scope",()=>{
  const h=harness(()=>{});interim(h,"QUARTERLY","LATEST");
  h.S.defaultDataset={dataset_id:"D",publication_id:"P",financial_as_of:"2026-10-25"};
  const a="0000000001",b="0000000002";h.S.explorerSelected=new Set([a,b]);
  h.basis.snapshot.rows=[{company:{cik:a},period:{calendar_year:2026,calendar_quarter:4}},{company:{cik:b},period:{calendar_year:2026,calendar_quarter:3}}];
  const published={schema_version:"screening-latest-company-periods-v1",dataset_id:"D",dataset_publication_id:"P",financial_as_of:"2026-10-25",
    records:[{cik:a,calendar_year:2026,calendar_quarter:4,bucket_status:"PERIOD_AVAILABLE",end_convention:"EXCLUSIVE",period_end:"2026-10-03"}]};
  h.basis.inventory.latest_company_periods=published;
  let context=h.companyTrendContext("quarter_revenue");
  assert.equal(context.spine.length,9);assert.equal(h.companyTrendSlots(context,[]).at(-1).key,"2026Q4");
  const payload=quarterSeries(a);payload.observations=[{...payload.observations[0],availability_status:"AVAILABLE",value:"300",calendar_quarter:4,period_end:"2026-10-03"}];
  assert.equal(h.validateCompanyTrendSeries(context,a,payload).rows.length,1);
  h.basis.periods.QUARTERLY="2026Q3";h.basis.readyKey="D:QUARTERLY:2026Q3";
  context=h.companyTrendContext("quarter_revenue");assert.equal(context.spine.length,8);assert.equal(h.companyTrendSlots(context,[]).at(-1).key,"2026Q3");
  h.basis.periods.QUARTERLY="LATEST";h.basis.readyKey="D:QUARTERLY:LATEST";
  published.dataset_publication_id="foreign";assert.throws(()=>h.companyTrendContext("quarter_revenue"),/범위/);
  published.dataset_publication_id="P";published.records[0].period_end="2027-01-01";assert.throws(()=>h.companyTrendContext("quarter_revenue"),/범위/);
});
