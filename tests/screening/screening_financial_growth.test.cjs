"use strict";
const assert=require("node:assert/strict");
const {createHash}=require("node:crypto");
const fs=require("node:fs");
const os=require("node:os");
const path=require("node:path");
const test=require("node:test");
const bridge=require("../../examples/screening/windows-loopback-bridge.cjs");

const scope={dataset_id:"dataset",dataset_publication_id:"publication",financial_as_of:"2026-10-25"};
const cik="0000000042";
const formulas=Object.fromEntries(["ordinary_yoy","negative_magnitude_change","delta"].map(key=>[key,{
  unit:key==="delta"?"USD":"PERCENT",expression:"rule",eligibility:"policy",
}]));
const defs=Object.fromEntries(Object.entries({FY:"",QTD_3M:"quarter_",TTM:"ttm_"}).flatMap(
  ([basis,prefix])=>["operating_income","cfo","standardized_fcf"].map(id=>[prefix+id,{basis,definition_version:"v1",formulas}])));
const fixture=()=>{
  const current={observation_id:"current",end_convention:"EXCLUSIVE",value:"2.1000000000000000001",period_start:"2025-01-01",period_end:"2026-01-01"};
  const prior={observation_id:"prior",end_convention:"EXCLUSIVE",value:"1",period_start:"2024-01-01",period_end:"2025-01-01"};
  return {...scope,schema_version:"screening-financial-growth-v1",rule_version:"signed-prepared-financial-yoy-v1",
    dataset_manifest_sha256:"1".repeat(64),period_end_convention:"EXCLUSIVE",source_compatibility_sha256:"2".repeat(64),definitions:defs,companies:{
      [cik]:{cfo:{2025:{status:"RATE_AVAILABLE",basis_assurance:"ARITHMETIC_ONLY_NOT_RECAST_VALIDATED",current,prior,yoy:"110.00000000000000001",delta:"1.1000000000000000001",negative_magnitude_change:null}}},
    }};
};
function serve(bundle,query="",method="GET"){
  const response={writeHead(status,headers){this.status=status;this.headers=headers},end(body){this.body=JSON.parse(body)}};
  bridge.serveFinancialGrowth(bundle,{method,url:"/api/financial-growth"+query},response);
  return response;
}
function temporary(t){
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),"screening-growth-"));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const file=path.join(directory,"growth.json");
  const write=payload=>{
    const data=JSON.stringify(payload);
    fs.writeFileSync(file,data);
    return createHash("sha256").update(data).digest("hex");
  };
  return {file,write};
}

test("growth bridge serves pinned exact company bytes without calculating or calling the backend",t=>{
  const {file,write}=temporary(t);
  const payload=fixture(),bundle=bridge.loadFinancialGrowth(file,write(payload));
  const query="?"+new URLSearchParams({...scope,cik});
  const served=serve(bundle,query);
  assert.equal(served.status,200);
  assert.equal(served.headers["cache-control"],"no-store");
  assert.equal(served.body.series.cfo["2025"].yoy,"110.00000000000000001");
  assert.equal(served.body.dataset_manifest_sha256,payload.dataset_manifest_sha256);
  assert.deepEqual(serve(null).body,{configured:false});
  assert.equal(serve(bundle).body.configured,true);
  assert.equal(serve(bundle,query+"&cik="+cik).status,400);
  assert.equal(serve(bundle,query+"&extra=1").status,400);
  assert.equal(serve(bundle,query.replace("publication&","older&")).status,409);
  assert.equal(serve(bundle,query.replace(cik,"0000000001")).status,404);
  assert.equal(serve(bundle,query,"POST").status,405);
});

test("growth bridge rejects tampered, malformed, oversized, and alias assets",t=>{
  const {file,write}=temporary(t);
  const payload=fixture(),digest=write(payload);
  fs.appendFileSync(file," ");
  assert.throws(()=>bridge.loadFinancialGrowth(file,digest),/differs from pin/);
  payload.companies[cik].cfo["2025"].yoy=110;
  assert.throws(()=>bridge.loadFinancialGrowth(file,write(payload)),/company series/);
  const large=fixture();
  large.companies[cik].cfo["2025"].current.observation_id="x".repeat(520*1024);
  assert.throws(()=>bridge.loadFinancialGrowth(file,write(large)),/response limit/);
  const good=write(fixture());
  const alias=path.join(path.dirname(file),"alias");
  fs.symlinkSync(file,alias);
  assert.throws(()=>bridge.loadFinancialGrowth(alias,good),/aliases/);
  fs.truncateSync(file,17*1024*1024);
  assert.throws(()=>bridge.loadFinancialGrowth(file,good),/bounded/);
});

test("v2 bridge serves catalog money and percentage-point values and keeps their semantics separate",t=>{
  const {file,write}=temporary(t),payload=fixture();
  payload.schema_version="screening-financial-growth-v2";
  payload.rule_version="catalog-prepared-financial-comparison-v2";
  payload.definitions={cash:{...defs.cfo,period_class:"INSTANT",unit_kind:"MONEY",comparison_kind:"YOY"},
    current_ratio:{basis:"FY",period_class:"INSTANT",definition_version:"v1",unit_kind:"PERCENT",comparison_kind:"PERCENTAGE_POINT",
      formulas:{change_pp:{unit:"PERCENTAGE_POINT",expression:"current - prior",eligibility:"compatible prepared inputs"}}}};
  const row=payload.companies[cik].cfo[2025];
  payload.companies[cik]={cash:{2025:row},current_ratio:{2025:{...row,status:"CHANGE_AVAILABLE",yoy:null,change_pp:"-0.0000001",delta:"-0.0000001"}}};
  const bundle=bridge.loadFinancialGrowth(file,write(payload));
  const served=serve(bundle,"?"+new URLSearchParams({...scope,cik}));
  assert.equal(served.body.series.current_ratio[2025].change_pp,"-0.0000001");
  assert.equal(served.body.series.cash[2025].yoy,row.yoy);
  for(const mutate of [p=>p.definitions.current_ratio.comparison_kind="YOY",
    p=>p.definitions.current_ratio.formulas.change_pp.unit="PERCENT",
    p=>p.companies[cik].current_ratio[2025].yoy="1",
    p=>p.companies[cik].current_ratio[2025].change_pp=1,
    p=>p.companies[cik].cash[2025].status="CHANGE_AVAILABLE"]){
    const invalid=structuredClone(payload);mutate(invalid);
    assert.throws(()=>bridge.loadFinancialGrowth(file,write(invalid)),/comparison/);
  }
  const legacy=fixture();legacy.companies[cik].cfo[2025].status="CHANGE_AVAILABLE";
  assert.throws(()=>bridge.loadFinancialGrowth(file,write(legacy)),/company series/);
});
