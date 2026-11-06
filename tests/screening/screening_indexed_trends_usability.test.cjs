"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm"),test=require("node:test");
const source=fs.readFileSync(path.resolve(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
const ids=["revenue","operating_income","net_income","cfo","standardized_fcf"],definitions=ids.map(metric_id=>({metric_id,label:metric_id,definition_version:"v1",period_class:"FY",unit_kind:"MONEY",unit:"USD"}));
function harness(respond=()=>{throw new Error("unexpected request")}){
  const nodes=new Map(),inputs=[],calls=[],focus=[],refreshes=[];
  const get=id=>{if(!nodes.has(id))nodes.set(id,{value:"",innerHTML:"",textContent:"",hidden:false,disabled:false,isConnected:true,options:[],classList:{toggle(){},add(){},remove(){}},setAttribute(){},replaceChildren(){this.innerHTML="";this.textContent=""},getBoundingClientRect(){return{width:390}},focus(){focus.push(id)}});return nodes.get(id)};
  const context=vm.createContext({URLSearchParams,location:{search:""},Node:{TEXT_NODE:3},document:{querySelector:get,querySelectorAll:selector=>selector==="[data-explorer-select]"?inputs:[]},fetch:async url=>{calls.push(url);const value=await respond(url);return{ok:true,json:async()=>value}}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  const api=vm.runInContext("({trend:companyTrend,selection:explorerSelection,basis:explorerBasis,S,displayIndex100,buildCompanyTrendDisplay,applyCompanyTrendDisplay,setCompanyTrendScale,companyTrendGeometry,renderCompanyTrendPlot,loadCompanyTrend,invalidateCompanyTrend,resetCompanyTrendView,transitionExplorerSelection,syncExplorerSelectionUI,registerExplorerCompanies,closeExplorerComparison})",context);
  api.S.defaultDataset={dataset_id:"D"};api.S.explorerYear=2025;api.S.explorerCatalog={metrics:definitions};api.S.explorer={dataset_publication_id:"P",financial_as_of:"2026-10-25",fiscal_years:[2022,2023,2024,2025].map(fiscal_year=>({fiscal_year})),rows:Array.from({length:5},(_,i)=>({company:{cik:String(i+1),ticker:"C"+(i+1),name:"Company "+(i+1)}}))};
  api.basis.readyKey="D:ANNUAL:2025";api.registerExplorerCompanies(api.S.explorer.rows.map(row=>row.company));
  api.selection.mounted=true;get("#comparison-panel").hidden=true;get("#comparison-trend-metric").value="revenue";get("#comparison-trend-scale").value="AMOUNT";
  return{...api,get,calls,inputs,focus,context,refreshes,stubRefresh(){context.onRefresh=value=>refreshes.push(value);vm.runInContext("mountCompanyTrend=(userOpened)=>onRefresh(userOpened)",context)}};
}
function model(valuesA=["0","100","0","-50"],valuesB=["10","20","0","-10"]){
  const slots=[2024,2025,2026,2027].map(year=>({key:year,ordinal:year,label:"FY"+year}));
  return{context:{basis:"ANNUAL",end:2027,definition:definitions[0]},slots,series:[valuesA,valuesB].map((values,index)=>({company:{cik:String(index+1),ticker:"C"+(index+1)},style:{color:"#225e80",dash:""},points:values.map((value,i)=>({slot:slots[i],observation:{value,availability_status:value===null?"UNAVAILABLE":"AVAILABLE",period_start:`${2023+i}-01-01`,period_end:`${2024+i}-01-01`,fiscal_year:2024+i}}))}))};
}
function profile(cik){return{dataset_id:"D",dataset_publication_id:"P",financial_as_of:"2026-10-25",selected_fiscal_year:2025,company:{cik,ticker:"C"+cik,name:"Company "+cik},prepared_years:[2022,2023,2024,2025],groups:[{metrics:definitions.map(definition=>({definition}))}],series:Object.fromEntries(ids.map(id=>[id,[2022,2023,2024,2025].map(fiscal_year=>({metric_id:id,definition_version:"v1",fiscal_year,value:"100000000",availability_status:"AVAILABLE",period_start:`${fiscal_year}-01-01`,period_end:`${fiscal_year+1}-01-01`}))]))}}
function deferred(){let resolve,reject;const promise=new Promise((done,fail)=>{resolve=done;reject=fail});return{promise,resolve,reject}}

test("index division is exact BigInt half-up, including negative ties, scientific values and negative zero",()=>{
  const h=harness();for(const [value,base,result]of [["1","6","16.67"],["-1","6","-16.67"],["-0.00005","1","-0.01"],["-0.0000001","1","0.00"],["1e30","2e30","50.00"],["9007199254740993","9007199254740993","100.00"]])assert.equal(h.displayIndex100(value,base),result);
  for(const base of ["0","-1","-0.00"])assert.throws(()=>h.displayIndex100("1",base));
});

test("one common positive base yields all100, suppresses earlier points and preserves post-base zero/negative/gaps",()=>{
  const h=harness(),raw=model(),before=JSON.stringify(raw),view=h.buildCompanyTrendDisplay(raw,"INDEX100");
  assert.equal(view.baseSlot.key,2025);assert.equal(view.effectiveScale,"INDEX100");
  for(const series of view.series)assert.deepEqual(Array.from(series.points,point=>point.plotValue),[null,"100.00","0.00","-50.00"]);
  assert.equal(JSON.stringify(raw),before);
  const scaled=model(["0","1000","0","-500"],["100","200","0","-100"]);
  assert.deepEqual(Array.from(h.buildCompanyTrendDisplay(scaled,"INDEX100").series[0].points,point=>point.plotValue),Array.from(view.series[0].points,point=>point.plotValue));
  raw.series[0].points[2].observation.value=null;assert.equal(h.buildCompanyTrendDisplay(raw,"INDEX100").series[0].points[2].plotValue,null);
});

test("no common positive or failed-company base visibly falls back to actual AMOUNT",()=>{
  const h=harness();for(const raw of [model(["0","0","0","0"]),model(["-1","-2",null,"0"]),(()=>{const value=model();value.series[1].error="failed";return value})()]){
    const view=h.buildCompanyTrendDisplay(raw,"INDEX100");assert.equal(view.effectiveScale,"AMOUNT");assert.match(view.reason,/공통 기간/);
  }
  h.get("#comparison-panel").hidden=false;h.trend.model=model(["0","0","0","0"]);h.setCompanyTrendScale("INDEX100");
  assert.equal(h.get("#comparison-trend-scale").value,"AMOUNT");assert.match(h.get("#comparison-trend-base").textContent,/실제 금액/);assert.match(h.get("#comparison-trend-chart").innerHTML,/단위 백만 달러/);
});

test("AMOUNT→INDEX→AMOUNT is raw-identical and fetch-free, with zero/100 reference labels",()=>{
  const h=harness(),raw=model(),before=JSON.stringify(raw);h.get("#comparison-panel").hidden=false;h.trend.model=raw;
  h.applyCompanyTrendDisplay();h.setCompanyTrendScale("INDEX100");
  assert.match(h.get("#comparison-trend-chart").innerHTML,/100.00/);assert.match(h.get("#comparison-trend-chart").innerHTML,/0.00/);assert.match(h.get("#comparison-trend-values").innerHTML,/기준 이전/);
  const geometry=h.companyTrendGeometry(h.trend.displayModel,390);assert(geometry.ticks.includes(0)&&geometry.ticks.includes(100));
  h.setCompanyTrendScale("AMOUNT");h.renderCompanyTrendPlot();assert.equal(JSON.stringify(raw),before);assert.equal(h.calls.length,0);
  assert.deepEqual(Array.from(h.trend.displayModel.series[0].points,point=>point.plotValue),["0","100","0","-50"]);
});

test("selection inverses cover0/1/2/4/5 and reject5 without invalidating the current chart",()=>{
  const h=harness();for(let i=1;i<=4;i++)h.transitionExplorerSelection("toggle",String(i),true,h.S.explorer.rows[i-1].company);
  assert.equal(h.S.explorerSelected.size,4);assert.equal(h.get("#compare-selected").disabled,false);
  h.inputs.push({dataset:{explorerCik:"5"},checked:true});h.get("#comparison-panel").hidden=false;const raw={sentinel:true};h.trend.model=raw;const token=h.trend.token;
  assert.equal(h.transitionExplorerSelection("toggle","5",true,h.S.explorer.rows[4].company).accepted,false);
  assert.equal(h.inputs[0].checked,false);assert.equal(h.trend.model,raw);assert.equal(h.trend.token,token);assert.equal(h.calls.length,0);
  assert.match(h.get("#explorer-selection-status").textContent,/최대 4/);
  h.transitionExplorerSelection("clear");h.transitionExplorerSelection("clear");assert.equal(h.S.explorerSelected.size,0);assert.equal(h.trend.model,null);assert.equal(h.get("#comparison-panel").hidden,true);assert.equal(h.get("#compare-selected").disabled,true);
  h.transitionExplorerSelection("toggle","1",true);assert.equal(h.get("#compare-selected").disabled,true);
  h.transitionExplorerSelection("toggle","2",true);assert.equal(h.get("#compare-selected").disabled,false);
  h.transitionExplorerSelection("remove","1");assert.equal(h.S.explorerSelected.size,1);
});

test("filtered chips use the pinned explorer registry; valid open-panel changes refresh only the trend",()=>{
  const h=harness();h.transitionExplorerSelection("toggle","1",true);h.transitionExplorerSelection("toggle","2",true);
  h.S.explorer.rows=[];h.S.companies=[{cik:"1",ticker:"OLD21"}];h.S.catalog=[];h.syncExplorerSelectionUI();
  assert.match(h.get("#explorer-selection-list").innerHTML,/C1/);assert.doesNotMatch(h.get("#explorer-selection-list").innerHTML,/OLD21/);
  h.stubRefresh();h.get("#comparison-panel").hidden=false;h.transitionExplorerSelection("toggle","3",true);
  assert.deepEqual(h.refreshes,[false]);assert.equal(h.get("#comparison-panel").hidden,false);assert.match(h.get("#comparison-result").textContent,/기업 선택이 변경/);assert.equal(h.calls.length,0);
  h.closeExplorerComparison();assert.equal(h.S.explorerSelected.size,3);assert.equal(h.get("#comparison-panel").hidden,true);assert.equal(h.focus.at(-1),"#compare-selected");
});

test("clear during an in-flight load removes every stale visual without fetching or repainting",async()=>{
  const pending=new Map(),h=harness(url=>{const cik=new URLSearchParams(url.split("?")[1]).get("cik");const item=deferred();pending.set(cik,item);return item.promise});
  h.S.explorerSelected=new Set(["1","2"]);h.get("#comparison-panel").hidden=false;const loading=h.loadCompanyTrend();h.transitionExplorerSelection("clear");
  for(const [cik,item]of pending)item.resolve(profile(cik));await loading;
  assert.equal(h.calls.length,2);assert.equal(h.S.explorerSelected.size,0);assert.equal(h.trend.model,null);assert.equal(h.trend.displayModel,null);assert.equal(h.get("#comparison-trend-chart").innerHTML,"");
});

test("latest scale is applied to an owned response and retry fetches only the failed company",async()=>{
  const pending=new Map(),h=harness(url=>{const cik=new URLSearchParams(url.split("?")[1]).get("cik");const item=deferred();pending.set(cik,item);return item.promise});
  h.S.explorerSelected=new Set(["1","2"]);h.get("#comparison-panel").hidden=false;const loading=h.loadCompanyTrend();h.setCompanyTrendScale("INDEX100");
  for(const [cik,item]of pending)item.resolve(profile(cik));await loading;
  assert.equal(h.trend.displayModel.effectiveScale,"INDEX100");assert.equal(h.calls.length,2);
  let failed=true;const retry=harness(url=>{const cik=new URLSearchParams(url.split("?")[1]).get("cik");if(cik==="2"&&failed)throw new Error("retry me");return profile(cik)});
  retry.S.explorerSelected=new Set(["1","2"]);retry.get("#comparison-panel").hidden=false;await retry.loadCompanyTrend();assert.equal(retry.get("#comparison-trend-retry").hidden,false);
  failed=false;await retry.loadCompanyTrend();assert.equal(retry.calls.length,3);assert.equal(retry.get("#comparison-trend-retry").hidden,true);
});

test("chart reset is scoped to revenue+AMOUNT and preserves period, selections and saved state",()=>{
  const h=harness();h.get("#comparison-panel").hidden=false;h.trend.model=model();h.trend.baseMetric="cfo";h.trend.scale="INDEX100";
  h.S.explorerSelected=new Set(["1","2"]);h.S.run={saved:"run"};h.S.catalog=[{saved:"catalog"}];h.S.revision={saved:"revision"};
  const before=JSON.stringify([h.S.run,h.S.catalog,h.S.revision,h.S.explorerYear,[...h.S.explorerSelected]]);h.resetCompanyTrendView();
  assert.equal(h.trend.baseMetric,"revenue");assert.equal(h.trend.scale,"AMOUNT");assert.equal(JSON.stringify([h.S.run,h.S.catalog,h.S.revision,h.S.explorerYear,[...h.S.explorerSelected]]),before);assert.equal(h.calls.length,0);
});


test("unready contexts keep compare disabled and clear returns focus to a usable search field",()=>{
  const h=harness();h.basis.readyKey=null;h.transitionExplorerSelection("toggle","1",true);h.transitionExplorerSelection("toggle","2",true);
  assert.equal(h.get("#compare-selected").disabled,true);
  const origin={closest:()=>null};h.transitionExplorerSelection("clear",null,false,null,origin);
  assert.equal(h.focus.at(-1),"#explorer-query");
});
