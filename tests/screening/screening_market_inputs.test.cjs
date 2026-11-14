"use strict";
const assert=require("node:assert/strict"),crypto=require("node:crypto"),fs=require("node:fs"),os=require("node:os"),path=require("node:path"),vm=require("node:vm"),test=require("node:test");
const bridge=require("../../examples/screening/windows-loopback-bridge.cjs");
const scope={dataset_id:"prepared109",dataset_publication_id:"pub109",financial_as_of:"2026-10-25",dataset_manifest_sha256:"a".repeat(64)};
const cik="0000000001";
function company(){return {registered_ticker:"COMMON",prices:[{security:{cik,ticker:"COMMON",security_id:"US:COMMON"},value:10,basis:"AS_TRADED_CLOSE",currency:null,requested_date:"2026-10-25",trade_date:"2026-10-23",staleness_calendar_days:2}],other_prices:[],reported_12m:{status:"AVAILABLE_REPORTED",value:"-1.2",positive_for_multiple:false,period_class:"FY",display_end:"2026-06-30",sources:[]},share_candidates:[],header_links:[],four_quarter_diagnostic:{reason:"SHARE_BASIS_UNKNOWN"}}}
function fixture(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),"market-profile-"));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const file=path.join(dir,"market.json");const asset={schema_version:"screening-market-input-profile-v1",...scope,companies:{[cik]:company()},source_pins:{common:{sha256:"b".repeat(64)},assessment:{sha256:"c".repeat(64)}},price_provenance:{realtime:false,automatic_update:false}};function write(){fs.writeFileSync(file,JSON.stringify(asset));return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex")}return {file,asset,write}}
function response(){return {writeHead(status){this.status=status},end(data){this.raw=data;this.body=JSON.parse(data)}}}
function get(bundle,query,method="GET"){const out=response();bridge.serveMarketInputs(bundle,{method,url:"/api/market-inputs"+(query?"?"+new URLSearchParams(query):"")},out);return out}

test("market route is optional read-only and exact current-publication scope without owner fallback",t=>{
 const f=fixture(t),bundle=bridge.loadMarketInputs(f.file,f.write());
 assert.equal(get(null).body.configured,false);assert.equal(get(bundle).body.configured,true);
 const request={dataset_id:scope.dataset_id,dataset_publication_id:scope.dataset_publication_id,financial_as_of:scope.financial_as_of,cik};
 const result=get(bundle,request);assert.equal(result.status,200);assert.equal(result.body.prices[0].value,10);assert.equal(result.body.reported_12m.value,"-1.2");
 assert.equal(get(bundle,{...request,dataset_publication_id:"old21"}).status,409);
 assert.equal(get(bundle,{...request,financial_as_of:"2025-10-25"}).status,409);
 assert.equal(get(bundle,{...request,fiscal_year:"2025"}).status,400);
 assert.equal(get(bundle,request,"POST").status,405);
 assert.equal(get(bundle,{...request,cik:"0000000002"}).status,404);
 assert.throws(()=>bridge.loadMarketInputs(f.file,"0".repeat(64)),/pin/);
});

test("market asset rejects foreign security ownership, future date and wrong basis",t=>{
 const f=fixture(t);for(const mutate of [c=>c.prices[0].security.cik="0000000002",c=>c.prices[0].trade_date="2026-11-01",c=>c.prices[0].basis="SPLIT_ADJUSTED",c=>c.prices[0].currency="USD",c=>c.prices[0].security.ticker="PREFERRED"]){f.asset.companies[cik]=company();mutate(f.asset.companies[cik]);assert.throws(()=>bridge.loadMarketInputs(f.file,f.write()),/market price/)}
});

const source=fs.readFileSync(path.join(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
function ui(extra={}){const state={profile:{company:{cik},financial_as_of:scope.financial_as_of}},basis={profileToken:1};const host={hidden:false,innerHTML:""},profileHost={hidden:false};const env={URLSearchParams,S:state,explorerBasis:basis,explorerDataset:()=>({dataset_id:scope.dataset_id,publication_id:scope.dataset_publication_id,financial_as_of:scope.financial_as_of,auxiliary_manifest_sha256:scope.dataset_manifest_sha256}),latestExplorerPeriod:()=>true,explorerContextKey:()=>"current",$:(selector)=>selector==="#company-profile"?profileHost:host,esc:value=>String(value??""),formatDecimal:value=>String(value),compactFinancialDate:value=>value,...extra};const helpers=source.slice(source.indexOf("// Optional pinned current-publication input worksheet"));const functions=vm.runInNewContext(helpers+"\n({beginMarketInputProfile,marketProfileEligible,validateMarketProfile,marketProfileMarkup})",env);return {functions,state,basis,host,profileHost}}

test("market UI guards fixed/history scope and displays negative EPS without price currency inference",()=>{
 const {functions:f}=ui();const dataset={...scope,publication_id:scope.dataset_publication_id,auxiliary_manifest_sha256:scope.dataset_manifest_sha256};
 assert(f.marketProfileEligible(dataset,true,{configured:true,...scope},cik));
 assert(!f.marketProfileEligible(dataset,false,{configured:true,...scope},cik));
 assert(!f.marketProfileEligible({...dataset,publication_id:"old21"},true,{configured:true,...scope},cik));
 const markup=f.marketProfileMarkup({...scope,cik,...company()});assert.match(markup,/거래일 기준 종가/);assert.match(markup,/-1.2/);assert.match(markup,/통화 미확인/);assert.match(markup,/2026-10-23/);assert.match(markup,/자동 갱신 자료가 아닙니다/);
 assert.throws(()=>f.validateMarketProfile({schema_version:"screening-market-input-profile-v1",...scope,cik,...company()},{...scope,cik:"0000000002"},scope),/범위/);
});

test("late market responses cannot repaint a switched or closed company",async()=>{
 const pending=[];let calls=0;const view=ui({api:url=>url==="/api/market-inputs"?Promise.resolve({configured:true,...scope}):new Promise(resolve=>{pending.push(resolve);calls++})});
 view.functions.beginMarketInputProfile();await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,1);
 view.state.profile={company:{cik:"0000000002"},financial_as_of:scope.financial_as_of};view.basis.profileToken++;view.functions.beginMarketInputProfile();await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,2);
 pending[0]({schema_version:"screening-market-input-profile-v1",...scope,cik,...company()});await new Promise(resolve=>setImmediate(resolve));assert.doesNotMatch(view.host.innerHTML,/최근 12개월 공시 EPS/);
 view.profileHost.hidden=true;pending[1]({schema_version:"screening-market-input-profile-v1",...scope,cik:"0000000002",...company(),prices:[]});await new Promise(resolve=>setImmediate(resolve));assert.doesNotMatch(view.host.innerHTML,/최근 12개월 공시 EPS/);
});
