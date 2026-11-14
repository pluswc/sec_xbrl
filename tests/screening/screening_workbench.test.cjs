"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const test=require("node:test");
const source=fs.readFileSync(path.resolve(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
class Element{
  constructor(tag="div",classes=""){this.tagName=tag.toUpperCase();this.classes=new Set(classes.split(" "));this.children=[];this.parentElement=null;this.dataset={};this.value="";this.checked=false;this.hidden=false;this._html="";this.classList={toggle(){},add(){},remove(){}}}
  set className(value){this.classes=new Set(value.split(" "))}
  get className(){return [...this.classes].join(" ")}
  append(...nodes){for(const node of nodes){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(child=>child!==node);node.parentElement=this;this.children.push(node)}}
  replaceChildren(...nodes){for(const child of this.children)child.parentElement=null;this.children=[];this.append(...nodes)}
  after(node){const parent=this.parentElement,index=parent.children.indexOf(this);if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(child=>child!==node);node.parentElement=parent;parent.children.splice(index+1,0,node)}
  closest(selector){for(let node=this;node;node=node.parentElement)if(selector==="label"?node.tagName==="LABEL":node.classes.has(selector.slice(1)))return node;return null}
  querySelector(selector){for(const child of this.children){if(child.classes.has(selector.slice(1)))return child;const match=child.querySelector(selector);if(match)return match}return null}
  set innerHTML(value){this._html=value;for(const name of ["screening-saved-fields"])if(value.includes(`class="${name}"`))this.append(new Element("div",name))}
  get innerHTML(){return this._html}
  setAttribute(){}
}
function harness(){
  const nodes=new Map(),predicates=[];
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)};
  const form=get("#criteria-form"),identity=new Element("div","condition-identity");form.append(identity,new Element("fieldset","company-scope"));
  for(const id of ["#screen-name","#saved-screen","#frequency","#period-mode","#fiscal-year","#calendar-quarter","#period-offset"]){const label=new Element("label");label.append(get(id));identity.append(label)}
  identity.append(get("#open-screen"));
  const workspace=new Element("section","workspace"),head=new Element("div","section-head"),filters=new Element("div","filters"),all=new Element("label","pass-only");
  head.append(get("#results-title"));workspace.append(head,filters,all);nodes.set(".workspace",workspace);
  const columns=["company","aggregate","predicates","decision"].map(value=>({value}));
  const context=vm.createContext({URLSearchParams,location:{search:""},Node:{TEXT_NODE:3},document:{createElement:tag=>new Element(tag),querySelector:get,querySelectorAll:selector=>selector===".predicate"?predicates:selector==='[name="visible-column"]:checked'?columns:[]}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  const api=vm.runInContext('({S,mount:mountScreeningWorkbench,serialize:revisionContent,cell:screeningResultMetricCell,roles:displayTableColumnRoles,render:renderRows})',context);
  api.S.catalog=[{metric_id:"revenue",label:"매출",unit_kind:"MONEY",unit:"USD",definition_version:"v1"},
    {metric_id:"operating_margin",label:"영업이익률",unit_kind:"PERCENT",unit:"PERCENT",definition_version:"v1"}];
  for(const [id,value] of Object.entries({"#dataset":"D","#universe-mode":"ALL_PREPARED","#frequency":"ANNUAL","#period-mode":"FIXED_FISCAL_YEAR","#fiscal-year":"2025","#calendar-quarter":"2026Q2","#sort-column":"ticker","#sort-direction":"ASC","#industry-select":"3571"}))get(id).value=value;
  for(const [metric,threshold] of [["revenue","12345.0000001"],["operating_margin","10.5"]]){
    const row=new Element("div","predicate");
    for(const [cls,value] of [["metric",metric],["operator","GTE"],["threshold",threshold]]){const field=new Element("input",cls);field.value=value;row.append(field)}
    predicates.push(row);
  }
  return {...api,get,form,identity,workspace,context};
}

test("moving existing controls is idempotent and preserves exact annual/quarter/universe serialization and handlers",()=>{
  const h=harness(),name=h.get("#screen-name"),saved=h.get("#saved-screen"),open=h.get("#open-screen");
  const handler=()=>{};open.onclick=handler;
  h.S.companySelection.add("1");h.S.companySelection.add("2");
  const snapshots=[];
  for(const universe of ["ALL_PREPARED","CIKS","SIC"]){
    h.get("#universe-mode").value=universe;snapshots.push(JSON.stringify(h.serialize()));
  }
  h.get("#universe-mode").value="ALL_PREPARED";
  h.mount();h.mount();
  assert.equal(h.identity.children.length,2);assert.equal(h.get("#screen-name"),name);assert.equal(h.get("#saved-screen"),saved);assert.equal(open.onclick,handler);
  assert.equal(open.parentElement.classes.has("screening-saved-fields"),true);
  assert.equal(h.get("#frequency").closest("label").parentElement.classes.has("screening-period-fields"),true);
  for(const [index,universe] of ["ALL_PREPARED","CIKS","SIC"].entries()){
    h.get("#universe-mode").value=universe;assert.equal(JSON.stringify(h.serialize()),snapshots[index]);
  }
  assert.equal(h.serialize().predicates[0].threshold,"12345000000.1");
  h.get("#frequency").value="QUARTERLY";h.get("#period-mode").value="FIXED_CALENDAR_QUARTER_END";
  assert.equal(JSON.stringify(h.serialize().period_policy),JSON.stringify({mode:"FIXED_CALENDAR_QUARTER_END",calendar_year:2026,calendar_quarter:2}));
  h.S.screenAvailability={dataset_id:"D",decision_date:"2026-10-25"};h.get("#period-mode").value="LATEST_COMPANY_QUARTER_V1";
  const latest=JSON.stringify(h.serialize());h.mount();assert.equal(JSON.stringify(h.serialize()),latest);
  assert.equal(h.workspace.children.filter(node=>node.classes.has("screening-result-toolbar")).length,1);
});

test("latest result period is a distinct role while fixed-period metrics and hidden company remain unchanged",()=>{
  const {roles}=harness(),cell=(extra={})=>({dataset:{},...extra});
  const fixed=[cell(),cell(),cell(),cell(),cell(),cell()];
  assert.equal(roles("results",fixed).join(),"select,company,status,number,number,status");
  const latest=[...fixed.slice(0,3),cell({dataset:{displayRole:"period"}}),...fixed.slice(3)];
  assert.equal(roles("results",latest).join(),"select,company,status,period,number,number,status");
  latest[1]={...latest[1],hidden:true};assert.equal(roles("results",latest).join(),"select,hidden,status,period,number,number,status");
  assert.equal(roles("results",fixed).join(),"select,company,status,number,number,status");
  assert.equal(roles("explorer",fixed).join(),"select,company,period,number,number,number");
});

test("native result value titles retain full names, precision, units and actual dates or missing reasons",()=>{
  const {cell,S}=harness();
  const value=cell({observation:{value:"9007199254740993.123",period_start:"2024-01-01",period_end:"2025-01-01"}},S.catalog[0]);
  assert.match(value,/매출 · 9,007,199,255 백만 USD · 실제 기간 2024-01-01 ~ 2024-12-31 · 공표값 9007199254740993.123 USD/);
  assert.match(value,/aria-label="매출/);
  const missing=cell({reason:"QUALITY_BLOCKED",observation:{value:null,period_end:"2025-01-01"}},{...S.catalog[1],label:'full <source> "label"'});
  assert.match(missing,/full &lt;source&gt; &quot;label&quot;.*자료 품질 확인이 필요합니다/s);
  assert.doesNotMatch(missing,/<source>|공표값 null/);
  assert.match(cell({observation:{value:"10.567",period_end:"2025-01-01"}},S.catalog[1]),/10.6 %.*공표값 10.567 PERCENT/);
});

test("rendered results retain selection and status filters across latest and fixed presentation",()=>{
  const h=harness();h.S.resultContent={predicates:h.S.catalog.map(metric=>({metric_id:metric.metric_id})),columns:["company"]};
  h.get("#show-all").checked=true;h.S.selected.add("1");
  const row=(cik,aggregate)=>({cik,ticker:"C"+cik,name:"Company "+cik,aggregate,resolved_period:{fiscal_year:2025,period_start:"2024-09-29",period_end:"2025-09-28",filed_date:"2025-10-31"},predicates:h.S.catalog.map(metric=>({metric_id:metric.metric_id,observation:{value:"100",period_start:"2024-01-01",period_end:"2025-01-01"}}))});
  h.S.run={period_policy:{mode:"LATEST_COMPANY_ANNUAL_V1"},rows:[row("1","PASS"),row("2","FAIL")]};
  h.render();assert.match(h.get("#result-head").innerHTML,/data-display-role="period"/);
  assert.match(h.get("#result-body").innerHTML,/data-cik="1" class="selected"/);
  assert.match(h.get("#result-body").innerHTML,/title="FY2025 · 2024-09-29 ~ 2025-09-27 · 공시일 2025-10-31"/);
  h.S.activeFilter="FAIL";h.render();assert.doesNotMatch(h.get("#result-body").innerHTML,/data-cik="1"/);
  assert.match(h.get("#result-body").innerHTML,/data-cik="2"/);
  h.S.activeFilter="ALL";h.get("#show-all").checked=false;h.S.run.period_policy={mode:"FIXED_FISCAL_YEAR",fiscal_year:2024};h.render();
  assert.doesNotMatch(h.get("#result-head").innerHTML,/data-display-role="period"/);
  assert.doesNotMatch(h.get("#result-body").innerHTML,/data-cik="2"/);assert(h.S.selected.has("1"));
});
