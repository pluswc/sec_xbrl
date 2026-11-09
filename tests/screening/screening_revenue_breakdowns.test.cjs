"use strict";
const assert=require("node:assert/strict");
const crypto=require("node:crypto");
const fs=require("node:fs");
const os=require("node:os");
const path=require("node:path");
const test=require("node:test");
const vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
const {loadRevenueBreakdowns,serveRevenueBreakdowns}=require(path.join(root,"examples/screening/windows-loopback-bridge.cjs"));
const source=fs.readFileSync(path.join(root,"examples/screening/display-assets/app.js"),"utf8");
const cik="0000000042",scope={dataset_id:"current",dataset_publication_id:"published",financial_as_of:"2026-10-25"};

test("only a pinned asset and exact GET scope expose one company",t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"revenue-breakdown-"));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const file=path.join(dir,"companies.json");
  const view={periods:[],groups:{segments:[],products:[]}};
  fs.writeFileSync(file,JSON.stringify({...scope,schema_version:"screening-revenue-breakdowns-v1",
    dataset_manifest_sha256:"a".repeat(64),companies:{[cik]:{ticker:"TEST",annual:view,quarterly:view}}}));
  const digest=crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
  const bundle=loadRevenueBreakdowns(file,digest);
  assert.throws(()=>loadRevenueBreakdowns(file,"0".repeat(64)),/differs from pin/);
  assert.throws(()=>loadRevenueBreakdowns("companies.json",digest),/absolute/);
  const request=(query,method="GET",asset=bundle)=>{
    const response={writeHead(status){this.status=status},end(body){this.body=JSON.parse(body)}};
    serveRevenueBreakdowns(asset,{method,url:"/api/revenue-breakdowns?"+query},response);
    return response;
  };
  const query=new URLSearchParams({...scope,cik});
  const result=request(query);
  assert.equal(result.status,200);assert.equal(result.body.ticker,"TEST");assert.equal(result.body.cik,cik);
  assert.equal(request(new URLSearchParams({...scope,dataset_publication_id:"previous",cik})).status,409);
  assert.equal(request(query+"&cik="+cik).status,400);
  assert.equal(request(new URLSearchParams({...scope,cik:"0000000001"})).status,404);
  assert.equal(request(query,"POST").status,405);
  assert.equal(request(query,"GET",null).status,503);
});

function profileHarness(){
  const elements=new Map();
  const get=selector=>{
    if(!elements.has(selector))elements.set(selector,{value:"",textContent:"",innerHTML:"",hidden:false});
    return elements.get(selector);
  };
  const context=vm.createContext({URLSearchParams,location:{search:""},document:{querySelector:get,querySelectorAll:()=>[]}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  const app=vm.runInContext("({revenueBreakdowns,revenueView,renderRevenueBreakdownTrend,revenueSourceLinks,revenueTrendSeries,renderRevenueBreakdownTable})",context);
  return {get,app};
}

test("profile frequency uses its own full window and trend gaps are not connected",()=>{
  const {get,app}=profileHarness();
  const period=(year,quarter)=>({fiscal_year:year,fiscal_quarter:quarter,period_end:"2026-07-01"});
  const periods=[period(2025,4),period(2026,1),period(2026,2)];
  const row={id:"cloud",label:"Cloud",mapping_epoch:"epoch-a",axis_members:{axis:"cloud"},cells:[{value:"1000000"},{value:null},{value:"2000000"}]};
  app.revenueBreakdowns.context={profile:{selected_fiscal_year:2025}};
  app.revenueBreakdowns.data={quarterly:{periods,groups:{segments:[row]}}};
  get("#revenue-breakdown-frequency").value="quarterly";
  get("#revenue-breakdown-kind").value="segments";
  get("#revenue-breakdown-series").value=app.revenueTrendSeries([row],3)[0].id;
  assert.equal(app.revenueView().periods.length,3);
  app.renderRevenueBreakdownTrend();
  const chart=get("#revenue-breakdown-chart").innerHTML;
  assert.equal((chart.match(/<circle/g)||[]).length,2);
  assert.doesNotMatch(chart,/<line class="line"/);
  assert.match(chart,/FY2026 Q1 자료 없음/);
  const member={label:"Search",scope:"services",axis_members:{product:"search",segment:"services"}};
  const first={...member,id:"old",mapping_epoch:"old",cells:[{value:"1000000"},{value:null},{value:null}]};
  const second={...member,id:"new",mapping_epoch:"new",axis_members:{segment:"services",product:"search"},
    cells:[{value:null},{value:"2000000"},{value:"3000000"}]};
  const foreign={...member,id:"foreign",scope:"other",axis_members:{segment:"other",product:"search"},
    mapping_epoch:"other",cells:[{value:"9000000"},{value:null},{value:null}]};
  const combined=app.revenueTrendSeries([first,second,foreign],3);
  assert.equal(combined.length,2);
  assert.deepEqual(Array.from(combined[0].slots,item=>item?.cell.value),["1000000","2000000","3000000"]);
  app.revenueBreakdowns.data.quarterly.groups.segments=[first,second,foreign];
  get("#revenue-breakdown-series").value=combined[0].id;
  app.renderRevenueBreakdownTrend();
  const epochs=get("#revenue-breakdown-chart").innerHTML;
  assert.equal((epochs.match(/<circle/g)||[]).length,3);
  assert.equal((epochs.match(/<line class="line"/g)||[]).length,1);
  assert.doesNotMatch(epochs,/9\.0 백만 USD/);
  second.mapping_review_required=true;
  app.renderRevenueBreakdownTrend();
  assert.doesNotMatch(get("#revenue-breakdown-chart").innerHTML,/<line class="line"/);
  second.cells[0]={value:"999000000"};
  assert.equal(app.revenueTrendSeries([first,second],3)[0].slots[0],null);
  const link=app.revenueSourceLinks([{accession:"0000000042-26-000001",filed_date:"2026-07-30"}],cik);
  assert.match(link,/https:\/\/www\.sec\.gov\/Archives\/edgar\/data\/42\/000000004226000001\//);
  assert.equal(app.revenueSourceLinks([{accession:"javascript:alert(1)"}],cik),"");
});


test("table places exact parent amounts above grouped details and retains totals in detail gaps",()=>{
  const {get,app}=profileHarness();
  const sources=[{accession:"0000000042-26-000001",filed_date:"2026-07-30"}];
  const amount=(value,status="REPORTED")=>({value,status,sources});
  const gap={value:null};
  const scope="issuer:ServicesMember";
  const periods=[{fiscal_year:2026,fiscal_quarter:2},{fiscal_year:2026,fiscal_quarter:3}];
  const totals=[amount("119796000000"),amount("121000000000","DERIVED")];
  const segments=[{member:scope,cells:[amount("94540000000"),gap]},
    {member:"other:ServicesMember",cells:[amount("999000000"),gap]}];
  const search={...amount("63271000000"),share:"66.92511",yoy:"16.7577",ratios:{
    share:{denominator:"SEGMENT_SUBTOTAL"},yoy:{prior_period_start:"2025-04-01",prior_period_end:"2025-07-01"}
  }};
  const products=[{label:"Search",scope,cells:[search,gap]},
    {label:"Company product",scope:null,cells:[amount("2000000"),gap]}];
  const view={periods,totals,groups:{segments,products}};
  app.revenueBreakdowns.data={cik,quarterly:view};
  get("#revenue-breakdown-frequency").value="quarterly";
  get("#revenue-breakdown-kind").value="products";
  get("#revenue-breakdown-period").value="0";
  const render=()=>{
    app.renderRevenueBreakdownTable();
    return get("#revenue-breakdown-table").innerHTML;
  };
  const grouped=render();
  assert.match(grouped,/연결 매출[\s\S]*119,796\.0[\s\S]*scope="rowgroup" id="revenue-scope-heading-0">부문 소계[\s\S]*94,540\.0[\s\S]*Search/);
  assert.equal((grouped.match(/scope="rowgroup" id="revenue-scope-heading-0">부문 소계/g)||[]).length,1);
  assert.match(grouped,/66\.93[\s\S]*title="비중의 분모">부문 소계/);
  assert.match(grouped,/16\.76[\s\S]*2025-04-01 ~ 2025-06-30/);
  assert.match(grouped,/2026-07-30/);
  assert.doesNotMatch(grouped,/999\.0/);
  segments.push({member:scope,cells:[amount("1000000"),gap]});
  assert.match(render(),/부문 소계[\s\S]*같은 범위의 준비 자료가 일치하지 않습니다/);
  get("#revenue-breakdown-period").value="1";
  assert.match(render(),/연결 매출[\s\S]*121,000\.0[\s\S]*계산값[\s\S]*이 회계기간의 매출 구성 자료가 준비되지 않았습니다/);
  delete view.totals;
  assert.match(render(),/연결 매출[\s\S]*이 기간에 확인된 연결 매출이 없습니다/);
});

test("prepared role hierarchy indents reported members and leaves ambiguous rows visible",()=>{
  const {get,app}=profileHarness();
  const value=(amount,share)=>({value:amount,status:"REPORTED",share,ratios:{share:{denominator:"SEGMENT_SUBTOTAL"}}});
  const node=(id,children=[])=>({id,children});
  const scope="issuer:ServicesMember";
  const products=[
    {id:"ad",scope,label:"Services / Advertising",cells:[value("80000000","80")]},
    {id:"search",scope,label:"Services / Search",cells:[value("60000000","60")]},
    {id:"video",scope,label:"Services / Video",cells:[value("20000000","20")]},
    {id:"subs",scope,label:"Subscriptions",cells:[value("20000000","20")]},
  ];
  const view={
    periods:[{fiscal_year:2026,fiscal_quarter:2}],
    totals:[value("200000000")],
    groups:{products,segments:[{member:scope,label:"Services",cells:[value("100000000")]}]},
    product_hierarchy:[[{scope,mode:"RECONCILED",groups:[
      {rows:[node("ad",[node("search"),node("video")]),node("subs")]}
    ]}]],
  };
  app.revenueBreakdowns.data={cik,quarterly:view};
  get("#revenue-breakdown-frequency").value="quarterly";
  get("#revenue-breakdown-kind").value="products";
  get("#revenue-breakdown-period").value="0";
  const render=()=>{
    app.renderRevenueBreakdownTable();
    return get("#revenue-breakdown-table").innerHTML;
  };
  const tree=render();
  assert.match(tree,/<tbody data-revenue-layout="RECONCILED"><tr class="revenue-subtotal" data-revenue-depth="0"><th scope="rowgroup" id="revenue-scope-heading-0">부문 소계/);
  assert.match(tree,/data-revenue-depth="1"[^>]+data-revenue-subtotal><th scope="row">Advertising<small>공시 소계/);
  assert.match(tree,/data-revenue-depth="2"><th scope="row">Search[\s\S]*60\.00[\s\S]*title="비중의 분모">부문 소계/);
  assert.doesNotMatch(tree,/Services \/ Search/);
  assert.match(tree,/하위 항목의 합계가 소계와 일치/);
  const layout=view.product_hierarchy[0][0];
  layout.groups[0].rows[0].children.push(node("search"));
  const ambiguous=render();
  assert.match(ambiguous,/합산 범위 미확인/);
  assert.doesNotMatch(ambiguous,/data-revenue-depth="2"/);
  assert.equal((ambiguous.match(/>Search</g)||[]).length,1);

  layout.mode="DISCLOSURES";
  layout.groups=[{label:"1000 - Statement - Consolidated Operations",rows:[node("ad"),node("subs")]},
    {label:"2000 - Disclosure - Revenue Detail",rows:[node("search"),node("video")]}];
  const alternatives=render();
  assert.equal((alternatives.match(/data-revenue-disclosure/g)||[]).length,2);
  assert.match(alternatives,/공시 분류 · Consolidated Operations/);
  assert.match(alternatives,/공시 분류 · Revenue Detail/);
  assert.equal((alternatives.match(/aria-describedby="revenue-scope-heading-0"/g)||[]).length,4);
  assert.doesNotMatch(alternatives,/1000 - Statement|data-revenue-depth="2"/);

  get("#revenue-breakdown-kind").value="segments";
  assert.match(render(),/부문 간 거래 제거/);
});
