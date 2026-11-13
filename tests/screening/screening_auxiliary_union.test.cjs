"use strict";
const assert=require("node:assert/strict");
const crypto=require("node:crypto"),fs=require("node:fs"),os=require("node:os"),path=require("node:path"),vm=require("node:vm"),test=require("node:test");
const bridge=require("../../examples/screening/windows-loopback-bridge.cjs");
const cik="0000000001",newCik="0000000002";
const source={dataset_id:"old50",dataset_publication_id:"old-publication",financial_as_of:"2026-10-25",dataset_manifest_sha256:"1".repeat(64)};
function fixture(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),"auxiliary-owner-"));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const file=path.join(root,"union.json");
  const manifest={schema_version:"screening-cohort-union-v1",dataset_id:"union",publication_id:"union-publication",financial_as_of:source.financial_as_of,
    configured_ciks:[cik,newCik],config:{expose_auxiliary_owners:true},auxiliary_owners:{[cik]:source,[newCik]:{...source,dataset_id:"new",dataset_publication_id:"new-publication",dataset_manifest_sha256:"2".repeat(64)}}};
  const write=body=>{fs.writeFileSync(file,JSON.stringify(body));return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex")};
  const digest=write(manifest),owner=bridge.loadAuxiliaryUnion(file,digest);
  const data={...source,cik,schema_version:"screening-financial-growth-v2",series:{value:"0"},definitions:{},period_end_convention:"EXCLUSIVE"};
  const bundle={scope:{...source,schema_version:data.schema_version},byCik:new Map([[cik,Buffer.from(JSON.stringify(data))]])};
  return{root,file,manifest,write,digest,owner,data,bundle};
}
function response(){return{writeHead(status,headers){this.status=status;this.headers=headers},end(body){this.raw=body;this.body=JSON.parse(body)}}}
function growth(bundle,owner,scope){const out=response();bridge.serveFinancialGrowth(bundle,{method:"GET",url:"/api/financial-growth"+(scope?"?"+new URLSearchParams(scope):"")},out,owner);return out}

test("union owner dispatch preserves legacy bytes and exposes explicit source scope",t=>{
  const f=fixture(t),scope={dataset_id:"union",dataset_publication_id:"union-publication",financial_as_of:source.financial_as_of,cik};
  const legacy=growth(f.bundle,f.owner,{...source,cik}); // Extra manifest query is rejected as before.
  assert.equal(legacy.status,400);
  const old=growth(f.bundle,f.owner,{dataset_id:source.dataset_id,dataset_publication_id:source.dataset_publication_id,financial_as_of:source.financial_as_of,cik});
  assert.deepEqual(old.raw,f.bundle.byCik.get(cik));
  const served=growth(f.bundle,f.owner,scope);assert.equal(served.status,200);
  assert.equal(served.body.schema_version,"screening-auxiliary-owner-response-v1");
  assert.deepEqual(served.body.source_scope,source);assert.deepEqual(served.body.data,f.data);
  assert.equal(served.body.request_scope.dataset_id,"union");assert.equal(served.body.owner_proof.union_manifest_sha256,f.digest);
  const capability=growth(f.bundle,f.owner).body;
  assert.equal(capability.dataset_id,"old50");assert.deepEqual(capability.owner_contexts[0].available_ciks,[cik]);
  assert.equal(growth(f.bundle,f.owner,{...scope,cik:newCik}).status,409);
  assert.equal(growth(f.bundle,f.owner,{...scope,dataset_publication_id:"other"}).status,409);
  assert.equal(growth(f.bundle,null,scope).status,409);
});

test("owner manifest rejects tamper, missing/foreign CIK and source cutoff",t=>{
  const f=fixture(t);assert.throws(()=>bridge.loadAuxiliaryUnion(f.file,"0".repeat(64)),/pin/);
  for(const change of [x=>delete x.auxiliary_owners[cik],x=>x.auxiliary_owners[cik].financial_as_of="2026-11-01",x=>x.config.expose_auxiliary_owners=false]){
    const invalid=structuredClone(f.manifest);change(invalid);assert.throws(()=>bridge.loadAuxiliaryUnion(f.file,f.write(invalid)),/owner scope/);
  }
  const alias=path.join(f.root,"alias.json");fs.symlinkSync(f.file,alias);assert.throws(()=>bridge.loadAuxiliaryUnion(alias,f.write(f.manifest)),/aliases/);
});

test("UI validates original payload and both sides of owner proof without relabeling",t=>{
  const f=fixture(t),requested={dataset_id:"union",dataset_publication_id:"union-publication",financial_as_of:source.financial_as_of,cik};
  const payload=growth(f.bundle,f.owner,requested).body;
  const app=fs.readFileSync(path.join(__dirname,"../../examples/screening/display-assets/app.js"),"utf8");
  const start=app.indexOf("function auxiliaryOwnerPayload("),end=app.indexOf("\nfunction requestFinancialGrowth(",start);
  const unwrap=vm.runInNewContext(app.slice(start,end)+";auxiliaryOwnerPayload");
  const dataset={auxiliary_manifest_sha256:f.digest};
  const data=unwrap(payload,requested,dataset,source);assert.equal(data.dataset_id,"old50");assert.equal(data.series.value,"0");
  assert.equal(data.auxiliary_owner.request_scope.dataset_id,"union");
  assert.strictEqual(unwrap(f.data,{...source,cik},{}),f.data);
  assert.throws(()=>unwrap(f.data,requested,dataset),/증거/);
  assert.throws(()=>unwrap({...f.data,auxiliary_owner:{source_scope:source}},{...source,cik},{}),/증거/);
  for(const change of [x=>x.request_scope.cik=newCik,x=>x.source_scope.dataset_manifest_sha256="9".repeat(64),x=>x.owner_proof.union_manifest_sha256="8".repeat(64),x=>x.data.dataset_id="union"]){
    const bad=structuredClone(payload);change(bad);assert.throws(()=>unwrap(bad,requested,dataset,source),/범위/);
  }
});

test("optional union flags fail closed and retain the old bridge default",t=>{
  const f=fixture(t),base=["--distribution","fixture","--linux-python","/python","--source-root","/src","--backend-port","19070","--frontend-port","19065"];
  assert.equal(bridge.parseArgs(base).auxiliaryUnion,null);
  assert.throws(()=>bridge.parseArgs([...base,"--auxiliary-union",f.file]),/auxiliary union/);
  assert.throws(()=>bridge.parseArgs([...base,"--auxiliary-union","relative.json","--auxiliary-union-sha256",f.digest]),/auxiliary union/);
  assert.equal(bridge.parseArgs([...base,"--auxiliary-union",f.file,"--auxiliary-union-sha256",f.digest]).auxiliaryUnion,f.file);
  const request={method:"POST",url:"/api/financial-growth?"+new URLSearchParams({dataset_id:"union",dataset_publication_id:"union-publication",financial_as_of:source.financial_as_of,cik})};
  const denied=response();bridge.serveFinancialGrowth(f.bundle,request,denied,f.owner);assert.equal(denied.status,405);
});
