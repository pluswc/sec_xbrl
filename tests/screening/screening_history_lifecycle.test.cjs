"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),http=require("node:http"),os=require("node:os"),path=require("node:path"),vm=require("node:vm"),test=require("node:test");
const {once}=require("node:events");
const root=path.resolve(__dirname,"../.."),bridge=require(path.join(root,"examples/screening/windows-loopback-bridge.cjs"));
const source=fs.readFileSync(path.join(root,"examples/screening/display-assets/app.js"),"utf8");
const revision="revision-"+"1".repeat(24),run="run-"+"2".repeat(24);
function snapshot(version=0,trash=[]){return{configured:true,version,revisions:trash.some(x=>x.kind==="REVISION")?[]:[{revision_id:revision,screen_id:"screen-one",name:"<Condition & name>",revision_number:1,created_at:"2026-11-07"}],runs:trash.some(x=>x.kind==="RUN")?[]:[{run_id:run,revision_id:revision,result_name:"Result",counts:{target:2,pass:1},created_at:"2026-11-07"}],decisions:[],trash}}
function harness(respond){
  const nodes=new Map(),calls=[],focus=[];
  const get=id=>{if(!nodes.has(id))nodes.set(id,{value:"",innerHTML:"",textContent:"",disabled:false,hidden:false,readOnly:false,isConnected:true,dataset:{},classList:{toggle(){},add(){},remove(){}},setAttribute(){},focus(){focus.push(id)},showModal(){this.open=true},close(){this.open=false},before(){},append(){},addEventListener(){}});return nodes.get(id)};
  const context=vm.createContext({URLSearchParams,location:{search:""},document:{querySelector:get,querySelectorAll:()=>[],createElement:()=>get("new"),body:get("body")},setTimeout:()=>0,fetch:async(url,options={})=>{calls.push({url,options});const value=await respond(url,options);return{ok:value?.status===undefined||value.status<400,status:value?.status||200,json:async()=>value?.body??value}}});
  vm.runInContext(source.slice(0,source.indexOf("async function boot()")),context);
  vm.runInContext('renderRows=()=>{}',context);
  return{...vm.runInContext('({S,history:journalHistory,historyRecords,applyHistorySnapshot,renderHistoryLists,historyEntries,confirmHistoryAction,closeHistoryConfirmation,submitHistoryAction,retryHistory,openRun,selectHistoryItems,switchHistoryView,confirmSelectedHistory,historySelectionKey})',context),get,calls,focus,context};
}
function deferred(){let resolve;return{promise:new Promise(done=>resolve=done),resolve:value=>resolve(value)}}

test("unconfigured history uses legacy reads; configured failure never falls back and is recoverable locally",async()=>{
  const legacy=harness(url=>url.endsWith("capabilities")?{configured:false}:[]);
  await legacy.historyRecords("runs","/api/runs");assert.equal(legacy.calls.at(-1).url,"/api/runs");
  let down=true;const h=harness(url=>{if(url.endsWith("capabilities"))return down?{status:503,body:{configured:true,error:"offline"}}:{configured:true};if(url==="/api/history")return snapshot();throw Error("raw fallback forbidden")});
  assert.equal((await h.historyRecords("runs","/api/runs")).length,0);assert.match(h.get("#history-status").textContent,/offline/);assert.equal(h.get("#open-run").disabled,true);
  h.renderHistoryLists();assert.equal(h.get("#open-run").disabled,true);assert(!h.calls.some(call=>call.url==="/api/runs"));
  down=false;await h.retryHistory();assert.equal(h.S.runs.length,1);assert.equal(h.get("#open-run").disabled,false);assert.equal(h.history.error,"");
});

test("delete/cancel/restore projection keeps dropdowns, current actions and raw dependency copy coherent",()=>{
  const h=harness(()=>{throw Error("unexpected fetch")});h.history.configured=true;
  h.applyHistorySnapshot(snapshot());h.renderHistoryLists();assert.match(h.get("#timeline").innerHTML,/&lt;Condition &amp; name&gt;/);
  const button=h.get("delete");h.confirmHistoryAction("delete","REVISION",revision,button);assert.equal(h.get("#history-confirm").open,true);
  h.closeHistoryConfirmation();assert.equal(h.calls.length,0);assert.equal(h.history.version,0);assert.equal(h.focus.at(-1),"delete");
  h.S.revision={revision_id:revision};h.S.run={run_id:run};h.S.preview={};h.S.frequencyDrafts={ANNUAL:{revision:h.S.revision}};
  h.applyHistorySnapshot(snapshot(1,[{kind:"REVISION",record_id:revision,record:snapshot().revisions[0]}]));h.renderHistoryLists();
  assert.equal(h.S.revision,null);assert.equal(h.S.run.run_id,run);assert.equal(h.S.preview,null);assert.equal(Object.keys(h.S.frequencyDrafts).length,0);assert.match(h.get("#save-state").textContent,/복사본/);
  h.applyHistorySnapshot(snapshot(2,[{kind:"RUN",record_id:run,record:snapshot().runs[0]}]));h.renderHistoryLists();assert.equal(h.S.run,null);assert.equal(h.get("#export-full-csv").disabled,true);
  h.applyHistorySnapshot(snapshot(3));h.renderHistoryLists();assert.equal(h.S.run,null);assert.equal(h.S.runs.length,1);assert.equal(h.calls.length,0);
});

test("pending mutation is single-submit, errors stay local and explicit retry sends same typed confirmation",async()=>{
  let attempt=0;const pending=deferred(),h=harness(()=>{attempt++;if(attempt===1)return{status:503,body:{error:"worker down"}};return pending.promise});
  h.history.configured=true;h.applyHistorySnapshot(snapshot());h.confirmHistoryAction("delete","RUN",run,h.get("delete"));
  await h.submitHistoryAction();assert.match(h.get("#history-confirm-error").textContent,/worker down/);assert.equal(h.history.pending,false);
  const request=h.submitHistoryAction();await h.submitHistoryAction();assert.equal(h.calls.length,2);assert.equal(h.get("#history-confirm-submit").disabled,true);
  pending.resolve(snapshot(1,[{kind:"RUN",record_id:run,record:snapshot().runs[0]}]));await request;
  assert.equal(h.history.pending,false);assert.equal(h.get("#history-confirm").open,false);assert.equal(h.S.runs.length,0);
  assert.deepEqual(JSON.parse(h.calls[1].options.body),{kind:"RUN",record_id:run,expected_version:0});
});

test("a late raw run read cannot reopen a result after its lifecycle context changed",async()=>{
  const response=deferred(),h=harness(url=>url.startsWith("/api/runs/")?response.promise:{revision_id:revision});h.history.configured=true;h.applyHistorySnapshot(snapshot());
  const opening=h.openRun(run);h.applyHistorySnapshot(snapshot(1,[{kind:"RUN",record_id:run,record:snapshot().runs[0]}]));response.resolve({run_id:run,revision_id:revision});await opening;
  assert.equal(h.S.run,null);assert.equal(h.S.revision,null);
});

function request(server,route,options={}){return new Promise((resolve,reject)=>{const req=http.request({host:"127.0.0.1",port:server.address().port,path:route,method:options.method||"GET",headers:{host:"127.0.0.1:0",...options.headers}},res=>{const chunks=[];res.on("data",chunk=>chunks.push(chunk));res.on("end",()=>resolve({status:res.statusCode,body:Buffer.concat(chunks).toString()}))});req.on("error",reject);req.end(options.body)})}
async function fixture(enabled,runTest){
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),"history-bridge-")),executable=path.join(directory,"fake-wsl");
  fs.writeFileSync(executable,`#!/usr/bin/env node\nconst history=process.argv.includes('/worker.py');require('node:readline').createInterface({input:process.stdin}).on('line',line=>{const m=JSON.parse(line);let value=history?(m.check_only?{allowed:true}:m.path==='/api/history/capabilities'?{configured:true}:m.path==='/api/history'?{revisions:[],runs:[],decisions:[],trash:[],version:0}:{private_note:true}):{financial:m.path};console.log(JSON.stringify({id:m.id,status:200,body_base64:Buffer.from(JSON.stringify(value)).toString('base64'),headers:{'content-type':'application/json'}}))});\n`,{mode:0o700});
  const instance=bridge.startBridge({wsl:executable,distribution:"fixture",linuxPython:"/unused/python",sourceRoot:"/unused/src",frontendPort:0,backendPort:1,historyWorker:enabled?"/worker.py":null,journalStore:enabled?"/private.sqlite":null});await once(instance.server,"listening");
  try{await runTest(instance)}finally{instance.server.closeAllConnections();await new Promise(resolve=>instance.server.close(resolve));instance.relay.kill();instance.history?.stop();fs.rmSync(directory,{recursive:true,force:true})}
}
test("bridge requires paired explicit paths and fixed routes behind all existing request gates",async()=>{
  const args=["--distribution","x","--linux-python","/python","--source-root","/src","--backend-port","1","--frontend-port","2"];
  assert.throws(()=>bridge.parseArgs([...args,"--history-worker","/worker.py"]),/together/);
  assert.throws(()=>bridge.parseArgs([...args,"--history-worker","../worker.py","--journal-store","/db"]),/absolute/);
  await fixture(true,async({server,history})=>{
    assert.equal((await request(server,"/api/history/capabilities")).status,200);
    assert.equal((await request(server,"/api/history",{headers:{host:"evil"}})).status,403);
    assert.equal((await request(server,"/api/history/delete",{method:"POST",body:"{}"})).status,403);
    assert.equal((await request(server,"/api/history/delete",{method:"POST",headers:{origin:"http://127.0.0.1:0","content-type":"text/plain"},body:"{}"})).status,400);
    const options={method:"POST",headers:{origin:"http://127.0.0.1:0","content-type":"application/json"},body:"{}"};
    assert.equal(JSON.parse((await request(server,"/api/decisions",options)).body).private_note,true);
    assert.deepEqual(JSON.parse((await request(server,"/api/runs")).body),[]);
    history.child.kill();await once(history.child,"exit");
    assert.equal((await request(server,"/api/history")).status,503);assert.equal((await request(server,"/api/runs")).status,503);
    assert.equal(JSON.parse((await request(server,"/api/status")).body).financial,"/api/status");
    assert.equal((await request(server,"/api/results",options)).status,503);
  });
  await fixture(false,async({server})=>{assert.equal(JSON.parse((await request(server,"/api/history/capabilities")).body).configured,false);assert.equal(JSON.parse((await request(server,"/api/runs")).body).financial,"/api/runs")});
});


test("an unresponsive history child times out without coupling to financial relay pending requests", {timeout:40000}, async()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),"history-timeout-")),executable=path.join(directory,"fake-wsl");
  fs.writeFileSync(executable,"#!/usr/bin/env node\nprocess.stdin.resume();\n",{mode:0o700});
  const history=bridge.startHistoryWorker({wsl:executable,distribution:"fixture",sourceRoot:"/unused/src",linuxPython:"/unused/python",historyWorker:"/worker.py",journalStore:"/private.sqlite"});
  try{await assert.rejects(history.request({method:"GET",path:"/api/history/capabilities",body_base64:""}),error=>error.status===504)}
  finally{history.stop();fs.rmSync(directory,{recursive:true,force:true})}
});


test("batch selection handles none/partial/all/clear without requests and stays scoped to the visible tab",()=>{
  const h=harness(()=>{throw Error("unexpected fetch")});h.history.configured=true;h.applyHistorySnapshot(snapshot());h.renderHistoryLists();
  assert.equal(h.get("#history-bulk-action").disabled,true);h.confirmSelectedHistory(h.get("bulk"));assert.equal(h.history.confirm,null);
  h.selectHistoryItems("toggle","REVISION",revision,true);assert.equal(h.history.selected.size,1);assert.equal(h.get("#history-bulk-action").textContent,"선택 1개 삭제");
  h.selectHistoryItems("all");h.selectHistoryItems("all");assert.equal(h.history.selected.size,2);assert.equal(h.get("#history-select-all").disabled,true);
  h.selectHistoryItems("clear");h.selectHistoryItems("clear");assert.equal(h.history.selected.size,0);assert.equal(h.get("#history-clear-selection").disabled,true);
  h.selectHistoryItems("all");h.applyHistorySnapshot(snapshot(1,[{kind:"RUN",record_id:run,record:snapshot().runs[0]}]));assert.equal(h.history.selected.size,1);
  h.switchHistoryView(true);assert.equal(h.history.selected.size,0);h.selectHistoryItems("all");assert.equal(h.history.selected.size,1);assert.equal(h.get("#history-bulk-action").textContent,"선택 1개 복원");
  h.switchHistoryView(false);assert.equal(h.history.selected.size,0);assert.equal(h.calls.length,0);
});

test("batch refresh prunes stale IDs but never expands selection to newly visible records",()=>{
  const h=harness(()=>{throw Error("unexpected fetch")});h.history.configured=true;h.applyHistorySnapshot(snapshot());h.selectHistoryItems("all");
  const refreshed=snapshot();refreshed.revisions.push({...refreshed.revisions[0],revision_id:"revision-"+"3".repeat(24),name:"Newly saved"});
  h.applyHistorySnapshot(refreshed);assert.equal(h.history.selected.size,2);assert(!h.history.selected.has("REVISION:revision-"+"3".repeat(24)));
  const hidden=snapshot(1,[{kind:"RUN",record_id:run,record:snapshot().runs[0]}]);h.applyHistorySnapshot(hidden);assert.deepEqual([...h.history.selected],["REVISION:"+revision]);
  h.history.configured=false;h.selectHistoryItems("all");assert.equal(h.history.selected.size,1);assert.equal(h.calls.length,0);
});

test("batch confirmation captures exact items/version with bounded names and cancel preserves selection",()=>{
  const h=harness(()=>{throw Error("unexpected fetch")});h.history.configured=true;const initial=snapshot();initial.revisions[0].name="Long "+"x".repeat(1000);h.applyHistorySnapshot(initial);h.selectHistoryItems("all");
  h.confirmSelectedHistory(h.get("bulk"));assert.equal(h.history.confirm.batch,true);assert.equal(h.history.confirm.items.length,2);assert.match(h.get("#history-confirm-item").textContent,/조건 1개 · 결과 1개/);assert(h.get("#history-confirm-item").textContent.length<300);
  h.selectHistoryItems("clear");h.switchHistoryView(true);assert.equal(h.history.selected.size,2);assert.equal(h.history.trash,false);
  const next=snapshot(1);next.revisions.push({...next.revisions[0],revision_id:"revision-"+"3".repeat(24)});h.applyHistorySnapshot(next);
  assert.equal(h.history.confirm.items.length,2);assert.equal(h.history.confirm.version,0);
  h.closeHistoryConfirmation();assert.equal(h.history.selected.size,2);assert.equal(h.calls.length,0);assert.equal(h.focus.at(-1),"bulk");
});

test("batch pending disables selection and double submission; success clears selection through the shared projection",async()=>{
  const pending=deferred(),h=harness(()=>pending.promise);h.history.configured=true;h.applyHistorySnapshot(snapshot());h.S.run={run_id:run};h.selectHistoryItems("all");h.confirmSelectedHistory(h.get("bulk"));
  const submitting=h.submitHistoryAction();h.selectHistoryItems("clear");await h.submitHistoryAction();assert.equal(h.calls.length,1);assert.equal(h.history.selected.size,2);assert.equal(h.get("#history-bulk-action").disabled,true);assert.equal(h.get("#history-clear-selection").disabled,true);
  assert.equal(h.calls[0].url,"/api/history/batch-delete");assert.deepEqual(JSON.parse(h.calls[0].options.body),{items:[{kind:"REVISION",record_id:revision},{kind:"RUN",record_id:run}],expected_version:0});
  pending.resolve({configured:true,version:2,revisions:[],runs:[],decisions:[],trash:[{kind:"REVISION",record_id:revision,record:snapshot().revisions[0]},{kind:"RUN",record_id:run,record:snapshot().runs[0]}]});await submitting;
  assert.equal(h.history.selected.size,0);assert.equal(h.S.run,null);assert.equal(h.get("#history-confirm").open,false);assert.equal(h.get("#history-bulk-action").disabled,true);
});

test("batch conflict refresh retains only valid selected IDs, requires reconfirmation and cannot auto-expand scope",async()=>{
  const refreshed=snapshot(1,[{kind:"RUN",record_id:run,record:snapshot().runs[0]}]);refreshed.revisions.push({...refreshed.revisions[0],revision_id:"revision-"+"3".repeat(24)});
  const h=harness(url=>url==="/api/history/batch-delete"?{status:409,body:{error:"changed"}}:refreshed);h.history.configured=true;h.applyHistorySnapshot(snapshot());h.selectHistoryItems("all");h.confirmSelectedHistory(h.get("bulk"));
  await h.submitHistoryAction();assert.equal(h.calls.length,2);assert.equal(h.history.confirm.stale,true);assert.equal(h.get("#history-confirm-submit").disabled,true);assert.deepEqual([...h.history.selected],["REVISION:"+revision]);
  await h.submitHistoryAction();assert.equal(h.calls.length,2);h.closeHistoryConfirmation();h.confirmSelectedHistory(h.get("bulk"));assert.equal(h.history.confirm.version,1);assert.equal(h.history.confirm.items.length,1);assert.equal(h.history.confirm.items[0].record_id,revision);
});

test("batch empty/unsupported/error states have no executable action and restore uses only captured trash",async()=>{
  const h=harness(()=>{throw Error("unexpected fetch")});h.applyHistorySnapshot(snapshot());h.selectHistoryItems("all");h.confirmSelectedHistory(h.get("bulk"));assert.equal(h.history.confirm,null);
  h.history.configured=true;h.history.error="unavailable";h.selectHistoryItems("all");assert.equal(h.history.selected.size,0);h.history.error="";
  h.applyHistorySnapshot({configured:true,version:0,revisions:[],runs:[],decisions:[],trash:[]});h.selectHistoryItems("all");assert.equal(h.get("#history-bulk-action").disabled,true);await h.submitHistoryAction();assert.equal(h.calls.length,0);
  const trash={kind:"RUN",record_id:run,record:snapshot().runs[0]};h.applyHistorySnapshot(snapshot(1,[trash]));h.switchHistoryView(true);h.selectHistoryItems("all");h.confirmSelectedHistory(h.get("bulk"));assert.equal(h.history.confirm.action,"restore");assert.deepEqual(JSON.parse(JSON.stringify(h.history.confirm.items)),[{kind:"RUN",record_id:run}]);
});


test("batch checkboxes keep native labels and a40px hit area while retaining row action hooks",()=>{
  const h=harness(()=>{throw Error("unexpected fetch")});h.history.configured=true;h.applyHistorySnapshot(snapshot());
  assert.match(h.get("#timeline").innerHTML,/<label class="history-checkbox"><input type="checkbox" data-history-select[^>]+><\/label>/);
  const css=fs.readFileSync(path.join(root,"examples/screening/display-assets/app.css"),"utf8");
  assert.match(css,/#timeline \.history-checkbox\{[^}]*min-width:40px;min-height:40px/);
  assert.match(css,/#timeline li\.history-selected\{background:var\(--blue-soft\)/);
});
