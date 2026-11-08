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

test("profile frequency uses its own full window and trend gaps are not connected",()=>{
  const elements=new Map();
  const get=selector=>{
    if(!elements.has(selector))elements.set(selector,{value:"",textContent:"",innerHTML:"",hidden:false});
    return elements.get(selector);
  };
  const context=vm.createContext({URLSearchParams,location:{search:""},document:{querySelector:get,querySelectorAll:()=>[]}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  const app=vm.runInContext("({revenueBreakdowns,revenueView,renderRevenueBreakdownTrend,revenueSourceLinks,revenueTrendSeries})",context);
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
