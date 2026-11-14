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

test("governed delta preserves exact parent ownership and rejects relabelled owners",t=>{
  const f=fixture(t),file=path.join(f.root,"delta.json");
  const manifest={schema_version:"screening-governed-delta-v1",dataset_id:"delta",publication_id:"delta-publication",
    financial_as_of:f.manifest.financial_as_of,configured_ciks:f.manifest.configured_ciks,
    parent:{path:"/home/immutable/union/screening_cohort_union_manifest.json",sha256:f.digest},auxiliary_owners:structuredClone(f.manifest.auxiliary_owners)};
  const write=value=>{fs.writeFileSync(file,JSON.stringify(value));return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex")};
  const digest=write(manifest),owner=bridge.loadAuxiliaryUnion(file,digest,{path:f.file,sha256:f.digest});
  const served=growth(f.bundle,owner,{dataset_id:"delta",dataset_publication_id:"delta-publication",financial_as_of:source.financial_as_of,cik});
  assert.equal(served.status,200);assert.deepEqual(served.body.data,f.data);
  assert.equal(served.body.owner_proof.union_manifest_sha256,digest);
  const parentRequest={dataset_id:f.manifest.dataset_id,dataset_publication_id:f.manifest.publication_id,
    financial_as_of:source.financial_as_of,cik};
  const parentServed=growth(f.bundle,owner,parentRequest);
  assert.equal(parentServed.status,200);assert.deepEqual(parentServed.body.data,f.data);
  assert.deepEqual(parentServed.body.request_scope,{...parentRequest,dataset_manifest_sha256:f.digest});
  assert.equal(parentServed.body.owner_proof.union_manifest_sha256,f.digest);
  assert.deepEqual(parentServed.body.source_scope,source);
  const contexts=growth(f.bundle,owner).body.owner_contexts;
  assert.equal(contexts.length,2);
  assert.equal(contexts[0].request_scope.dataset_manifest_sha256,digest);
  assert.equal(contexts[1].request_scope.dataset_manifest_sha256,f.digest);
  assert.deepEqual(contexts[1].available_ciks,[cik]);
  assert.equal(growth(f.bundle,owner,{...parentRequest,dataset_publication_id:"unknown"}).status,409);
  assert.equal(growth(f.bundle,owner,{...parentRequest,cik:newCik}).status,409);
  const bad=structuredClone(manifest);bad.auxiliary_owners[cik].dataset_publication_id="wrong";
  assert.throws(()=>bridge.loadAuxiliaryUnion(file,write(bad),{path:f.file,sha256:f.digest}),/ownership/);
  const tampered=structuredClone(manifest);tampered.parent.sha256="0".repeat(64);
  assert.throws(()=>bridge.loadAuxiliaryUnion(file,write(tampered),{path:f.file,sha256:f.digest}),/pin/);
  assert.throws(()=>bridge.loadAuxiliaryUnion(file,write(manifest)),/host parent/);
});

test("typed union preserves exact ancestor auxiliary scope and CIK boundaries",t=>{
  const f=fixture(t),manifest={...f.manifest,schema_version:"screening-cohort-union-v2",dataset_id:"composed100",
    publication_id:"composed100-publication",auxiliary_contexts:[{scope:{dataset_id:"approved92",dataset_publication_id:"approved92-publication",
      financial_as_of:source.financial_as_of,dataset_manifest_sha256:"3".repeat(64)},ciks:[cik]}]};
  const digest=f.write(manifest),owner=bridge.loadAuxiliaryUnion(f.file,digest);
  const requested={dataset_id:"approved92",dataset_publication_id:"approved92-publication",financial_as_of:source.financial_as_of,cik};
  const ancestor=growth(f.bundle,owner,requested);assert.equal(ancestor.status,200);
  assert.deepEqual(ancestor.body.data,f.data);assert.equal(ancestor.body.owner_proof.union_manifest_sha256,"3".repeat(64));
  const composed=growth(f.bundle,owner,{...requested,dataset_id:"composed100",dataset_publication_id:"composed100-publication"});
  assert.equal(composed.status,200);assert.equal(composed.body.owner_proof.union_manifest_sha256,digest);
  assert.deepEqual(growth(f.bundle,owner).body.owner_contexts[1].available_ciks,[cik]);
  assert.equal(growth(f.bundle,owner,{...requested,cik:newCik}).status,409);
  const invalid=structuredClone(manifest);invalid.auxiliary_contexts[0].ciks=["9999999999"];
  assert.throws(()=>bridge.loadAuxiliaryUnion(f.file,f.write(invalid)),/ancestor scope/);
});

test("prepared publication binds separate ROOT approval to exact original union while retaining legacy contexts",t=>{
  const f=fixture(t);
  const stable=value=>JSON.stringify(value,(_,item)=>item&&typeof item==="object"&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
  const hash=value=>crypto.createHash("sha256").update(stable(value)).digest("hex");
  const write=(name,value)=>{const file=path.join(f.root,name);fs.writeFileSync(file,stable(value));return{path:file,sha256:hash(value)}};
  const original={schema_version:"screening-prepared-changes-v1",dataset_id:"new-changes",publication_id:"changes-pub",financial_as_of:source.financial_as_of,
    parent_dataset_id:f.owner.scope.dataset_id,parent_publication_id:f.owner.scope.dataset_publication_id,parent_manifest_sha256:f.owner.scope.dataset_manifest_sha256,
    parent_logical_sha256:"8".repeat(64),configured_ciks:[cik,newCik],auxiliary_owners:structuredClone(f.manifest.auxiliary_owners)};
  function declared(change=()=>{}){
    const manifest=structuredClone(original);change(manifest);
    const snapshot={schema_version:"screening-read-snapshot-v1",reader_version:"screening-read-snapshot-v1",logical_sha256:"9".repeat(64),origin:{kind:"screening-prepared-changes-v1"},properties:{original_manifest:manifest,original_manifest_sha256:hash(manifest)}};
    const declaration={manifest:write("snapshot.json",snapshot)};
    declaration.verification=write("verification.json",{schema_version:"screening-read-export-verification-v1",verified:true,manifest_sha256:declaration.manifest.sha256,logical_sha256:snapshot.logical_sha256,origin:snapshot.origin});
    declaration.approval=write("approval.json",{schema_version:"screening-read-snapshot-root-approval-v1",authority:"ROOT",approved:true,reader_version:snapshot.reader_version,manifest_sha256:declaration.manifest.sha256,verification_sha256:declaration.verification.sha256,logical_sha256:snapshot.logical_sha256,origin:snapshot.origin});return declaration;
  }
  const binding=bridge.bindPreparedAuxiliary(f.owner,declared());
  const contexts=growth(f.bundle,binding).body.owner_contexts;assert.equal(contexts.length,2);assert.deepEqual(contexts[1].available_ciks,[cik]);
  const served=growth(f.bundle,binding,{dataset_id:"new-changes",dataset_publication_id:"changes-pub",financial_as_of:source.financial_as_of,cik});
  assert.equal(served.status,200);assert.deepEqual(served.body.data,f.data);assert.equal(served.body.owner_proof.union_manifest_sha256,hash(original));
  assert.equal(growth(f.bundle,binding,{dataset_id:f.manifest.dataset_id,dataset_publication_id:f.manifest.publication_id,financial_as_of:source.financial_as_of,cik}).status,200);
  for(const mutate of [x=>x.parent_manifest_sha256="0".repeat(64),x=>x.parent_publication_id="foreign",x=>x.auxiliary_owners[cik].dataset_publication_id="foreign"]){assert.throws(()=>bridge.bindPreparedAuxiliary(f.owner,declared(mutate)),/exact approved parent/)}
  const missing=declared();delete missing.approval;assert.throws(()=>bridge.bindPreparedAuxiliary(f.owner,missing));
  assert.throws(()=>bridge.bindPreparedAuxiliary(null,declared()),/explicit original union/);
});
