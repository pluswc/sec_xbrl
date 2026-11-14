const S={screenAvailability:null,screens:[],runs:[],decisions:[],catalog:[],companies:[],companySelection:new Set(),defaultDataset:null,contextToken:0,revision:null,run:null,resultContent:null,preview:null,busy:false,selected:new Set(),activeFilter:"ALL",dirty:false,lastFocus:null,evidenceRow:null,admin:new URLSearchParams(location.search).get("mode")==="admin",explorerDataset:null,explorerYear:null,explorer:null,library:null,explorerCatalog:null,explorerCatalogKey:null,explorerCatalogToken:0,explorerSelected:new Set(),profile:null,profileMetric:"revenue",view:"explorer",explorerToken:0,libraryToken:0,frequencyDrafts:{},quarterSpine:[],frequency:"ANNUAL"};const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
async function api(path,options={}){
  if(options.method==="POST"&&(path==="/api/preview"||(path==="/api/results"&&S.preview?.include_evidence===false))){
    const body=JSON.parse(options.body);
    if(path==="/api/preview"||body.preview_hash===S.preview.preview_hash)options={...options,body:JSON.stringify({...body,include_evidence:false})};
  }
  const r=await fetch(path,{headers:{"Content-Type":"application/json"},...options}),b=await r.json().catch(()=>({error:`요청 오류 ${r.status}`}));if(!r.ok)throw Object.assign(new Error(b.error||"요청에 실패했습니다."),{status:r.status});if(options.method==="POST"&&/^\/api\/(?:screens|results|runs|decisions|history)(?:\/|$)/.test(path))invalidateHistoryRead();return b}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function toast(m){const e=$("#toast");e.textContent=m;e.classList.add("visible");setTimeout(()=>e.classList.remove("visible"),1800)}
function fail(e){const m=e.message||String(e);$("#criteria-error").hidden=false;$("#criteria-error").textContent=m.startsWith("metric is unavailable for execution:")?"현재 자료에서 실행할 수 없는 지표가 포함돼 있습니다. 사용 가능한 지표를 선택해 주세요.":m}
function categoryLabel(v){return ({GROWTH:"성장성",PROFITABILITY:"수익성",CASH_FLOW:"현금흐름",FINANCIAL_STABILITY:"재무안정성",OTHER_REPORTED:"공시항목"})[v]||v}
function aggregateLabel(v){return ({PASS:"조건 충족",FAIL:"조건 미충족",UNDETERMINED:"자료 확인 필요"})[v]||v}
function decisionLabel(v){return ({INTEREST:"관심",HOLD:"보류",EXCLUDE:"제외"})[v]||v||"기록 없음"}
function metricById(id){return S.catalog.find(x=>x.metric_id===id)||{metric_id:id,label:id,category:"OTHER_REPORTED",unit_kind:"MONEY",unit:"USD",definition_version:"annual-core-reported-v1",period_class:"FY",coverage:{}}}
// Display only: exact decimal half-up rounding, with ties away from zero.
function formatDecimal(v,places=1){
  if(v===null||v===undefined)return"—";
  const normalized=shiftDecimal(String(v),0),negative=normalized.startsWith("-"),absolute=negative?normalized.slice(1):normalized;
  const [whole,fraction=""]=absolute.split("."),kept=fraction.padEnd(places,"0").slice(0,places);
  let scaled=BigInt(whole+kept);
  if((fraction[places]||"0")>="5")scaled+=1n;
  const digits=scaled.toString().padStart(places+1,"0"),integer=places?digits.slice(0,-places):digits;
  return(negative&&scaled!==0n?"-":"")+integer.replace(/\B(?=(\d{3})+(?!\d))/g,",")+(places?"."+digits.slice(-places):"");
}
function shiftDecimal(v,p){const c=String(v).trim().replace(/,/g,""),m=c.match(/^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);if(!m||(m[2]+m[3]).length===0)throw new Error("숫자 형식을 확인해 주세요.");const s=m[1]==="-"?"-":"",w=m[2]||"",f=m[3]||"",raw=w+f;if(/^0+$/.test(raw))return"0";const leading=(raw.match(/^0*/)||[""])[0].length,d=raw.slice(leading),q=w.length+Number(m[4]||0)+p-leading;let o=q<=0?"0."+"0".repeat(-q)+d:q>=d.length?d+"0".repeat(q-d.length):d.slice(0,q)+"."+d.slice(q);o=o.replace(/^0+(?=\d)/,"");if(o.includes("."))o=o.replace(/0+$/,"").replace(/\.$/,"");o=o||"0";return o==="0"?o:s+o}
function displayValue(v,m){
  if(v===null||v===undefined)return "—";
  const value=shiftDecimal(v,m.unit_kind==="MONEY"?-6:0);
  const places=m.unit_kind==="MONEY"?0:m.unit_kind==="PERCENT"?1:2;
  const text=formatDecimal(value,places);
  if(value!=="0"&&/^0(?:\.0+)?$/u.test(text)){
    const quantum=places?"0."+"0".repeat(places-1)+"1":"1";
    return value.startsWith("-")?">-"+quantum:"<"+quantum;
  }
  return text;
}
function numberMarkup(v,m){const text=displayValue(v,m);return`<span class="display-number explorer-value" title="${esc(v)} ${esc(m.unit||unitLabel(m))}" aria-label="${esc(text)} ${esc(unitLabel(m))}"><span class="number-text">${esc(text)}</span><span class="number-clipped" aria-hidden="true">…</span></span>`}
function thresholdToApi(v,m){return shiftDecimal(v,m.unit_kind==="MONEY"?6:0)}
function thresholdFromApi(v,m){return shiftDecimal(v,m.unit_kind==="MONEY"?-6:0)}
function unitLabel(m){return metricPresentationUnit(m)}
function businessReason(c){return ({LATEST_SOURCE_PERIOD_NOT_PUBLISHED:"최신 분기 조회 자료 미준비",MULTIPLE_CANDIDATES:"같은 기간의 값이 여러 개입니다.",PERIOD_NOT_PREPARED:"선택한 기간의 자료가 없습니다.",MISSING_INPUT:"계산에 필요한 공시 항목이 없습니다.",QUALITY_BLOCKED:"자료 품질 확인이 필요합니다.",MAPPING_REVIEW_REQUIRED:"공시 항목 확인이 필요합니다.",NON_POSITIVE_DENOMINATOR:"비율 계산 기준값을 사용할 수 없습니다.",NEGATIVE_EQUITY:"자본이 음수여서 비율을 제공하지 않습니다.",CAPEX_SIGN_UNCERTAIN:"투자지출 표시 방향을 확인해야 합니다.",UNSUPPORTED_FISCAL_QUARTER_DURATION:"일반적인 3개월 분기보다 기간이 길어 비교에서 보류했습니다.",INPUTS_NOT_COMPATIBLE:"연속 분기의 계산 기준이 달라 값을 제공하지 않습니다.",NO_FILING_AS_OF_CUTOFF:"기준일까지 해당 분기 공시가 없습니다."})[c]||"공시자료 확인이 필요합니다."}
function filteredCatalog(){const c=$("#metric-category").value,n=$("#metric-search").value.trim().toLowerCase();return S.catalog.filter(x=>(!c||x.category===c)&&(!n||x.label.toLowerCase().includes(n)||x.metric_id.toLowerCase().includes(n)))}
function metricOptions(selected){let rows=filteredCatalog();const keep=metricById(selected);if(selected&&!rows.some(x=>x.metric_id===selected))rows=[keep,...rows];return ["GROWTH","PROFITABILITY","CASH_FLOW","FINANCIAL_STABILITY","OTHER_REPORTED"].map(c=>{const a=rows.filter(x=>x.category===c);return a.length?`<optgroup label="${categoryLabel(c)}">${a.map(x=>{const v=x.coverage||{},coverage=v.companies_total?` · ${v.companies_available}/${v.companies_total}개 기업`:"",disabled=x.business_availability==="UNAVAILABLE"&&x.metric_id!==selected;return`<option value="${esc(x.metric_id)}" ${x.metric_id===selected?'selected':''} ${disabled?'disabled':''}>${esc(x.label)} · ${unitLabel(x)}${coverage}${disabled?' · 현재 사용 불가':''}</option>`}).join("")}</optgroup>`:""}).join("")}
function predicateRow(v){const m=metricById(v?.metric_id||filteredCatalog()[0]?.metric_id||S.catalog[0]?.metric_id||"revenue"),r=document.createElement("div");r.className="predicate";r.innerHTML=`<label>지표<select class="metric">${metricOptions(m.metric_id)}</select><span class="metric-hint"></span></label><label>조건<select class="operator"><option value="GTE">이상</option><option value="GT">초과</option><option value="LTE">이하</option><option value="LT">미만</option><option value="EQ">같음</option></select></label><label><span class="field-caption">기준값 (<span class="threshold-unit"></span>)</span><input class="threshold" inputmode="decimal" required></label><button type="button" class="quiet remove">삭제</button>`;r.querySelector(".operator").value=v?.operator||"GTE";r.querySelector(".threshold").value=v?thresholdFromApi(v.threshold,m):"0";updatePredicateHint(r);r.querySelector(".metric").onchange=()=>{updatePredicateHint(r);markDirty()};r.querySelector(".remove").onclick=()=>{if($$(".predicate").length>1){r.remove();markDirty()}};$("#predicates").append(r)}
function updatePredicateHint(r){const m=metricById(r.querySelector(".metric").value),c=m.coverage||{},presentation=metricPresentation(m,{catalog:S.catalog});r.querySelector(".threshold-unit").textContent=presentation.unit;r.querySelector(".metric-hint").innerHTML=`${esc(categoryLabel(m.category))} · ${esc(presentation.period)}${presentation.comparison?` · ${esc(presentation.comparison)}`:""} · ${esc(presentation.source)} <span class="coverage">준비 범위 ${c.companies_available??c.available_companies??"—"}개 기업</span>`}

function refreshMetricOptions(){$$(".predicate").forEach(r=>{const s=r.querySelector(".metric"),v=s.value;s.innerHTML=metricOptions(v);if([...s.options].some(x=>x.value===v))s.value=v;updatePredicateHint(r)})}
const LATEST_ANNUAL_POLICY="LATEST_COMPANY_ANNUAL_V1",LATEST_QUARTER_POLICY="LATEST_COMPANY_QUARTER_V1";
const batchView={enabled:false,datasets:[],snapshot:null,token:0,fixedOnly:false};
function latestScreenPolicy(policy){return [LATEST_ANNUAL_POLICY,LATEST_QUARTER_POLICY].includes(policy?.mode)}
function quarterlyScreenPolicy(policy){return ["FIXED_CALENDAR_QUARTER_END",LATEST_QUARTER_POLICY].includes(policy?.mode)}
function availabilityCaption(snapshot){
  if(!snapshot)return "배치를 선택해 주세요.";
  if(snapshot.mode==="PREPARED_SIMULATION")return `준비된 자료로 가정 · 재무 기준일 ${snapshot.financial_as_of} · 실제 가용 이력 미적용`;
  const ready=new Date(snapshot.ready_at).toLocaleString("ko-KR",{timeZone:"America/New_York"});
  return `확보 기록 기준 · 뉴욕 ${ready} 조회 가능 확인 · 판단일 ${snapshot.decision_date} · 사용지연 ${snapshot.lag}거래일 · 재무 기준일 ${snapshot.financial_as_of}`;
}
function syncScreenPeriodModes(){
  if(!batchView.enabled)return;
  const field=$("#period-mode"),quarterly=$("#frequency").value==="QUARTERLY",current=field.value;
  const latest=quarterly?LATEST_QUARTER_POLICY:LATEST_ANNUAL_POLICY;
  field.innerHTML=quarterly
    ?'<option value="FIXED_CALENDAR_QUARTER_END">종료 분기 고정</option>'
    :'<option value="LATEST_COMPLETE_ANNUAL">최근 완료 연도 (기존 방식)</option><option value="FIXED_FISCAL_YEAR">회계연도 고정</option>';
  if(S.screenAvailability?.dataset_id===$("#dataset").value){
    field.insertAdjacentHTML("afterbegin",`<option value="${latest}">회사별 최신</option>`);
  }
  if([...field.options].some(option=>option.value===current))field.value=current;
}
function screeningPeriodPolicy(){
  const mode=$("#period-mode").value;
  const snapshot=S.screenAvailability?.dataset_id===$("#dataset").value?S.screenAvailability:null;
  const availability=snapshot?{availability:{...snapshot}}:{};
  if(latestScreenPolicy({mode})){
    if(S.screenAvailability?.dataset_id!==$("#dataset").value)throw new Error("조회 배치를 선택해 주세요.");
    return{mode,availability:{...S.screenAvailability}};
  }
  if($("#frequency").value==="QUARTERLY"){
    const period=$("#calendar-quarter").value;
    return{mode:"FIXED_CALENDAR_QUARTER_END",calendar_year:Number(period.slice(0,4)),calendar_quarter:Number(period.slice(-1)),...availability};
  }
  return mode==="FIXED_FISCAL_YEAR"?{mode,fiscal_year:Number($("#fiscal-year").value),...availability}
    :{mode:"LATEST_COMPLETE_ANNUAL",offset:Number($("#period-offset").value)};
}
function revisionContent(){const mode=$("#universe-mode").value;let universe={mode:"ALL_PREPARED"};if(mode==="CIKS")universe={mode,ciks:[...S.companySelection]};if(mode==="SIC")universe={mode,sic_codes:[$("#industry-select").value]};const period=screeningPeriodPolicy();return{universe,predicates:$$(".predicate").map(r=>{const m=metricById(r.querySelector(".metric").value);return{metric_id:m.metric_id,operator:r.querySelector(".operator").value,threshold:thresholdToApi(r.querySelector(".threshold").value,m),definition_version:m.definition_version}}),period_policy:period,columns:$$('[name="visible-column"]:checked').map(x=>x.value),sort:{column:$("#sort-column").value,direction:$("#sort-direction").value}}}
function markDirty(){S.dirty=true;S.preview=null;syncScreeningPresentation(true);$("#save-result").disabled=true;$("#save-state").textContent=S.revision?"수정됨 · 저장 필요":"저장 전 · 저장 필요"}
function isRevisionEdit(t){return t instanceof Element&&!t.closest("#saved-screen,#open-screen,#dataset,#metric-category,#metric-search,#company-query")}
function setCriteriaCompact(c){$(".criteria").classList.toggle("compact",c);$("#toggle-criteria").setAttribute("aria-expanded",String(!c));$("#toggle-criteria").textContent=c?"조건 편집":"조건 접기"}

// Recoverable history is a journal projection, separate from financial evaluation.
const journalHistory={configured:null,capability:null,snapshot:null,promise:null,version:0,epoch:0,request:0,error:"",pending:false,trash:false,confirm:null,selected:new Set()};
async function historyCapability(){
  if(journalHistory.capability)return journalHistory.capability;
  journalHistory.capability=(async()=>{try{
    const response=await fetch("/api/history/capabilities"),body=await response.json().catch(()=>({}));
    if(response.status===404){journalHistory.configured=false;return false}
    journalHistory.configured=body.configured!==false;
    if(!response.ok)throw new Error(body.error||"이력 연결을 사용할 수 없습니다.");
    return journalHistory.configured;
  }catch(error){journalHistory.configured=true;throw error}})();
  return journalHistory.capability;
}
function invalidateHistoryRead(){journalHistory.snapshot=null;journalHistory.request++;journalHistory.promise=null}
function historyUnavailable(error){
  journalHistory.epoch++;journalHistory.error=error.message||String(error);journalHistory.snapshot=null;
  S.screens=[];S.runs=[];S.decisions=[];
  clearResult();renderHistoryControls();
}
async function historySnapshot(){
  if(journalHistory.snapshot)return journalHistory.snapshot;
  if(journalHistory.promise)return journalHistory.promise;
  const request=journalHistory.request;
  const promise=api("/api/history").then(snapshot=>{
    if(request!==journalHistory.request)return historySnapshot();
    applyHistorySnapshot(snapshot);return snapshot;
  }).finally(()=>{if(journalHistory.promise===promise)journalHistory.promise=null});
  journalHistory.promise=promise;return promise;
}
async function historyRecords(key,legacyPath){
  try{if(!await historyCapability())return await api(legacyPath);return(await historySnapshot())[key]}
  catch(error){historyUnavailable(error);return[]}
}
function historyHidden(kind,id){return(journalHistory.snapshot?.trash||[]).some(x=>x.kind===kind&&x.record_id===id)}
function applyHistorySnapshot(snapshot){
  const changed=journalHistory.version!==snapshot.version;
  journalHistory.version=snapshot.version;journalHistory.snapshot=snapshot;journalHistory.error="";
  if(changed)journalHistory.epoch++;
  S.screens=snapshot.revisions;S.runs=snapshot.runs;S.decisions=snapshot.decisions;
  if(S.run?.run_id&&historyHidden("RUN",S.run.run_id)){clearResult();$("#run-diff").textContent="";toast("열었던 결과를 휴지통으로 이동했습니다. 복원 후 다시 열어 주세요.")}
  if(S.revision&&historyHidden("REVISION",S.revision.revision_id)){
    detachHistoryRevision();
  }
  renderHistoryControls();
}
function detachHistoryRevision(){
    S.revision=null;S.preview=null;S.dirty=true;S.frequencyDrafts={};
    $("#saved-screen").value="";$("#screen-name").readOnly=false;
    $("#save-state").textContent="휴지통의 조건 · 현재 내용은 저장 전 복사본";
    $("#screen-context").textContent="삭제된 저장 조건의 복사본 · 새 조건으로 저장 가능";
}
function historyRecordTitle(kind,record){
  if(kind==="REVISION")return`${record.name} · v${record.revision_number}`;
  if(kind==="RUN")return`${record.result_name||"저장 결과"} · 대상 ${record.counts?.target??"—"} · 충족 ${record.counts?.pass??"—"}`;
  return`CIK ${record.cik} · ${Object.hasOwn(record,"display_before_state")?`${decisionLabel(record.display_before_state)} → `:""}${decisionLabel(record.state)} · ${record.rationale}`;
}
const historyFilter={query:"",kind:""};
function historyAllEntries(){
  if(journalHistory.trash)return(journalHistory.snapshot?.trash||[]).map(x=>({...x,deleted:true}));
  return[...S.screens.map(record=>({kind:"REVISION",record_id:record.revision_id,record})),...S.runs.map(record=>({kind:"RUN",record_id:record.run_id,record})),...S.decisions.map(record=>({kind:"DECISION",record_id:record.event_id,record}))];
}
function historyEntries(){const query=historyFilter.query.trim().toLocaleLowerCase();return historyAllEntries().filter(item=>(!historyFilter.kind||item.kind===historyFilter.kind)&&(!query||`${item.kind} ${historyRecordTitle(item.kind,item.record)} ${item.record_id}`.toLocaleLowerCase().includes(query)))}
function changeHistoryFilter(query,kind){if(journalHistory.pending||journalHistory.confirm){$("#history-query").value=historyFilter.query;$("#history-kind").value=historyFilter.kind;return;}historyFilter.query=query;historyFilter.kind=kind;journalHistory.selected.clear();renderTimeline();$("#history-filter-status").textContent=`검색 ${historyEntries().length}개 · 필터 변경으로 선택을 초기화했습니다.`}
function historySelectionKey(item){return`${item.kind}:${item.record_id}`}
function pruneHistorySelection(){
  if(!journalHistory.snapshot||journalHistory.error)return;
  const valid=new Set(historyEntries().map(historySelectionKey));
  for(const key of journalHistory.selected)if(!valid.has(key))journalHistory.selected.delete(key);
}
function syncHistorySelectionControls(){
  const entries=historyEntries(),count=journalHistory.selected.size;
  const blocked=journalHistory.configured!==true||Boolean(journalHistory.error)||journalHistory.pending;
  $("#history-selected-count").textContent=`선택 ${count}개`;
  $("#history-select-all").disabled=blocked||!entries.length||count===entries.length;
  $("#history-clear-selection").disabled=blocked||!count;
  $("#history-bulk-action").textContent=`선택 ${count}개 ${journalHistory.trash?"복원":"삭제"}`;
  $("#history-bulk-action").disabled=blocked||!count;
  $("#history-selection-tools").hidden=journalHistory.configured!==true||Boolean(journalHistory.error)||!entries.length;
  $("#history-selected-count").hidden=!count;
  $("#history-clear-selection").hidden=!count;
  $("#history-bulk-action").hidden=!count;
  $$('[data-history-select]').forEach(input=>{
    input.checked=journalHistory.selected.has(historySelectionKey({kind:input.dataset.historyKind,record_id:input.dataset.historyId}));
    input.disabled=blocked;input.closest('[data-history-row]')?.classList.toggle("history-selected",input.checked);
  });
}
function selectHistoryItems(action,kind=null,id=null,checked=false){
  if(journalHistory.pending||journalHistory.confirm||journalHistory.error||journalHistory.configured!==true)return;
  pruneHistorySelection();const entries=historyEntries();
  if(action==="all")entries.forEach(item=>journalHistory.selected.add(historySelectionKey(item)));
  else if(action==="clear")journalHistory.selected.clear();
  else if(action==="toggle"){
    const key=historySelectionKey({kind,record_id:id});
    if(!entries.some(item=>historySelectionKey(item)===key))return;
    checked?journalHistory.selected.add(key):journalHistory.selected.delete(key);
  }
  syncHistorySelectionControls();
}
function switchHistoryView(trash){
  if(journalHistory.pending||journalHistory.confirm)return;
  if(journalHistory.trash!==trash)journalHistory.selected.clear();
  journalHistory.trash=trash;renderTimeline();
}
function confirmSelectedHistory(button){
  pruneHistorySelection();
  const items=historyEntries().filter(item=>journalHistory.selected.has(historySelectionKey(item)));
  if(items.length)openHistoryConfirmation(journalHistory.trash?"restore":"delete",items,button,true);
}
function historyTimestampCaption(value){const raw=String(value||""),match=raw.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/);if(!match)return raw;return`${match[1].slice(2)}.${match[2]}.${match[3]} ${match[4]}:${match[5]} ${match[6]==="Z"?"UTC":`UTC${match[6]}`}`}
function renderHistoryControls(){
  if(!$("#history-lifecycle"))return;
  pruneHistorySelection();
  const configured=journalHistory.configured===true,blocked=configured&&Boolean(journalHistory.error),busy=journalHistory.pending;
  $("#history-trash").hidden=!configured;$("#history-active").setAttribute("aria-pressed",String(!journalHistory.trash));$("#history-trash").setAttribute("aria-pressed",String(journalHistory.trash));
  $("#history-active").disabled=busy;$("#history-trash").disabled=busy;
  $("#history-filter-status").textContent=blocked?"연결 오류 · 기록을 표시하지 않습니다.":`검색 ${historyEntries().length}개 · 전체 선택은 현재 보이는 범위에만 적용됩니다.`;
  $("#history-query").disabled=busy||Boolean(journalHistory.confirm);$("#history-kind").disabled=busy||Boolean(journalHistory.confirm);
  $("#history-retry").disabled=busy;$("#history-lifecycle").setAttribute("aria-busy",String(busy));
  $("#history-status").textContent=journalHistory.error||(configured?`활성 조건 ${S.screens.length} · 결과 ${S.runs.length} · 메모 ${S.decisions.length} · 휴지통 ${journalHistory.snapshot?.trash.length||0}`:"삭제·복원 연결이 설정되지 않았습니다. 기존 이력 조회를 사용합니다.");
  const tab=$("#history-current-tab");
  if(tab)tab.textContent=journalHistory.trash?"현재 보기 · 휴지통":"현재 보기 · 활성 이력";
  $("#history-status").classList.toggle("explorer-error",blocked);
  $("#history-retry").textContent=blocked?"이력 다시 연결":"이력 새로고침";
  $("#timeline").innerHTML=blocked?'<li class="empty">이력을 불러올 수 없습니다. 다시 연결해 주세요. 숨긴 기록을 원본 목록으로 대신 표시하지 않습니다.</li>':historyEntries().map(x=>`<li data-history-row="${esc(x.record_id)}" data-history-kind="${x.kind}" data-history-id="${esc(x.record_id)}">${configured?`<label class="history-checkbox"><input type="checkbox" data-history-select data-history-kind="${x.kind}" data-history-id="${esc(x.record_id)}" aria-label="${esc(historyRecordTitle(x.kind,x.record).slice(0,120))} 선택"></label>`:""}<div class="history-row-content"><div class="history-row-title"><b>${({REVISION:"조건",RUN:"결과",DECISION:"판단 메모"})[x.kind]}</b> · ${esc(historyRecordTitle(x.kind,x.record))}</div><div class="history-row-metadata"><time title="${esc(x.record.created_at||"")}" aria-label="${esc(x.record.created_at||"")}">${esc(historyTimestampCaption(x.record.created_at))}</time><details class="history-record-detail"><summary>기록 ID·원문</summary><small>${esc(x.record_id)}</small><pre>${esc(JSON.stringify(x.record,null,2))}</pre></details></div></div>${!x.deleted&&x.kind!=="DECISION"?`<button type="button" class="quiet" data-history-open="${esc(x.record_id)}" data-history-kind="${x.kind}" ${busy?"disabled":""}>불러오기</button>`:""}${configured?`<button type="button" class="quiet" data-history-action="${x.deleted?"restore":"delete"}" ${x.deleted?"data-history-restore":"data-history-delete"} data-history-kind="${x.kind}" data-history-id="${esc(x.record_id)}" ${busy?'disabled':''}>${x.deleted?"복원":"삭제"}</button>`:""}</li>`).join("")||`<li class="empty">${historyFilter.query||historyFilter.kind?"검색 조건에 맞는 이력이 없습니다.":journalHistory.trash?"휴지통이 비어 있습니다.":"아직 이력이 없습니다."}</li>`;
  syncHistorySelectionControls();
}
function renderTimeline(){renderHistoryControls()}
function renderHistoryLists(){
  const selected=$("#saved-screen").value,old=$("#old-run").value,newer=$("#new-run").value;
  $("#saved-screen").innerHTML='<option value="">새 조건</option>'+S.screens.map(x=>`<option value="${esc(x.revision_id)}">${esc(x.name)} · v${x.revision_number}</option>`).join("");
  if(S.screens.some(x=>x.revision_id===selected))$("#saved-screen").value=selected;
  const options='<option value="">실행 선택</option>'+S.runs.map(x=>`<option value="${esc(x.run_id)}">${esc(x.result_name||S.screens.find(s=>s.revision_id===x.revision_id)?.name||"저장 결과")} · ${esc(x.created_at?.slice(0,16)||"")} · 대상 ${x.counts.target}</option>`).join("");
  $("#old-run").innerHTML=options;$("#new-run").innerHTML=options;
  if(S.runs.some(x=>x.run_id===old))$("#old-run").value=old;
  if(S.runs.some(x=>x.run_id===newer))$("#new-run").value=newer;
  renderTimeline();syncResultActions();if(S.run)renderRows();
}
async function refreshScreens(){S.screens=await historyRecords("revisions","/api/screen-revisions");renderHistoryLists()}
async function refreshRuns(){S.runs=await historyRecords("runs","/api/runs");renderHistoryLists()}
async function refreshDecisions(){S.decisions=await historyRecords("decisions","/api/decisions");renderHistoryLists()}
async function retryHistory(){
  if(journalHistory.pending)return;
  journalHistory.capability=null;invalidateHistoryRead();
  await refreshScreens();await refreshRuns();await refreshDecisions();
}
function confirmHistoryAction(action,kind,id,button){
  const item=historyEntries().find(x=>x.kind===kind&&x.record_id===id);
  if(item)openHistoryConfirmation(action,[item],button,false);
}
function openHistoryConfirmation(action,items,button,batch){
  if(journalHistory.pending||journalHistory.confirm||journalHistory.error||journalHistory.configured!==true||!items.length)return;
  journalHistory.confirm={action,kind:items[0].kind,id:items[0].record_id,items:items.map(x=>({kind:x.kind,record_id:x.record_id})),batch,version:journalHistory.version,focus:button};
  const count=items.length,summary=["REVISION","RUN","DECISION"].map(kind=>{const n=items.filter(x=>x.kind===kind).length;return n?`${({REVISION:"조건",RUN:"결과",DECISION:"메모"})[kind]} ${n}개`:""}).filter(Boolean).join(" · ");
  $("#history-confirm-title").textContent=batch?`선택 ${count}개를 ${action==="delete"?"휴지통으로 이동":"복원"}할까요?`:action==="delete"?"이 기록을 휴지통으로 이동할까요?":"이 기록을 복원할까요?";
  $("#history-confirm-item").textContent=(batch?`${summary}\n`:"")+items.slice(0,5).map(x=>historyRecordTitle(x.kind,x.record).slice(0,120)).join("\n")+(count>5?`\n외 ${count-5}개`:"");
  $("#history-confirm-note").textContent=action==="delete"?"확인한 항목만 함께 숨깁니다. 연결된 조건·결과·다른 메모와 다운로드 파일은 삭제하지 않습니다. 휴지통에서 복원할 수 있습니다.":"확인한 항목을 같은 ID와 원래 내용으로 함께 되돌립니다. 판단 메모를 복원하면 현재 관심상태가 다시 계산됩니다.";
  $("#history-confirm-submit").textContent=batch?`선택 ${count}개 ${action==="delete"?"삭제":"복원"}`:action==="delete"?"휴지통으로 이동":"복원";
  $("#history-confirm-submit").disabled=false;$("#history-confirm-error").textContent="";$("#history-confirm-refresh").hidden=true;$("#history-confirm").showModal();$("#history-confirm-cancel").focus();
}
function closeHistoryConfirmation(){
  if(journalHistory.pending)return;
  const focus=journalHistory.confirm?.focus;journalHistory.confirm=null;$("#history-confirm").close();
  (focus?.isConnected?focus:$("#history-retry")).focus();
}
async function submitHistoryAction(){
  const item=journalHistory.confirm;if(!item||item.stale||journalHistory.pending)return;
  journalHistory.pending=true;syncResultActions();$("#history-confirm-submit").disabled=true;$("#history-confirm-cancel").disabled=true;renderHistoryControls();
  try{
    const snapshot=await api(`/api/history/${item.batch?"batch-":""}${item.action}`,{method:"POST",body:JSON.stringify(item.batch?{items:item.items,expected_version:item.version}:{kind:item.kind,record_id:item.id,expected_version:item.version})});
    if(item.batch)journalHistory.selected.clear();
    journalHistory.epoch++;applyHistorySnapshot(snapshot);renderHistoryLists();
    journalHistory.pending=false;closeHistoryConfirmation();$(journalHistory.trash?"#history-trash":"#history-active").focus();
    toast(item.action==="delete"?"휴지통으로 이동했습니다.":"기록을 복원했습니다.");
  }catch(error){
    $("#history-confirm-error").textContent=error.message;$("#history-confirm-refresh").hidden=false;
    if(error.status===409){
      item.stale=true;invalidateHistoryRead();
      try{await historySnapshot();renderHistoryLists()}catch(refreshError){historyUnavailable(refreshError);renderHistoryLists()}
    }else if(error.status>=500){historyUnavailable(error);renderHistoryLists()}
  }
  finally{journalHistory.pending=false;$("#history-confirm-submit").disabled=Boolean(journalHistory.confirm?.stale);$("#history-confirm-cancel").disabled=false;renderHistoryControls();syncResultActions()}
}
async function openHistoryEntry(kind,id){if(journalHistory.pending||journalHistory.error||journalHistory.trash)return;const item=historyEntries().find(x=>x.record_id===id&&x.kind===kind);if(!item)return;if(item.kind==="RUN")await openRun(item.record_id);else if(item.kind==="REVISION")await openSavedScreenRecord(item.record)}
function mountJournalHistory(){
  const controls=document.createElement("section");controls.id="history-lifecycle";
  controls.innerHTML='<div class="history-toolbar"><button id="history-active" type="button" class="quiet" aria-pressed="true">활성 이력</button><button id="history-trash" type="button" class="quiet" aria-pressed="false" hidden>휴지통</button><button id="history-retry" type="button" class="quiet">이력 새로고침</button><small id="history-current-tab">현재 보기 · 활성 이력</small></div><div id="history-selection-tools" class="history-toolbar" hidden><button id="history-select-all" type="button" class="quiet">전체 선택</button><button id="history-clear-selection" type="button" class="quiet">선택 해제</button><span id="history-selected-count" role="status" aria-live="polite">선택 0개</span><button id="history-bulk-action" type="button" disabled>선택 0개 삭제</button></div><p id="history-status" role="status" aria-live="polite"></p>';
  const filters=document.createElement("div");filters.className="history-filter-bar";filters.innerHTML='<label>이력 검색<input id="history-query" type="search" placeholder="제목·기록 ID 검색"></label><label>유형<select id="history-kind"><option value="">전체 유형</option><option value="REVISION">조건</option><option value="RUN">결과</option><option value="DECISION">판단 메모</option></select></label><p id="history-filter-status" role="status" aria-live="polite"></p>';controls.append(filters);
  filters.querySelector("input").oninput=()=>changeHistoryFilter($("#history-query").value,$("#history-kind").value);filters.querySelector("select").onchange=()=>changeHistoryFilter($("#history-query").value,$("#history-kind").value);
  const timeline=$("#timeline"),comparison=$("#old-run").closest(".compare");
  timeline.before(controls);
  const savedResults=document.createElement("details");
  savedResults.className="history-saved-results workflow-disclosure";
  savedResults.innerHTML="<summary>저장 결과 열기·비교</summary>";
  timeline.after(savedResults);
  savedResults.append(comparison,$("#run-diff"));
  $("#toggle-history").hidden=true;
  const dialog=document.createElement("dialog");dialog.id="history-confirm";dialog.setAttribute("aria-labelledby","history-confirm-title");
  dialog.innerHTML='<h3 id="history-confirm-title"></h3><p id="history-confirm-item"></p><p id="history-confirm-note" class="muted"></p><p id="history-confirm-error" role="alert"></p><div class="button-row"><button id="history-confirm-refresh" type="button" class="quiet" hidden>이력 새로 확인</button><button id="history-confirm-cancel" type="button" class="quiet">취소</button><button id="history-confirm-submit" type="button">확인</button></div>';
  document.body.append(dialog);
  $("#history-active").onclick=()=>switchHistoryView(false);$("#history-trash").onclick=()=>switchHistoryView(true);
  $("#history-select-all").onclick=()=>{selectHistoryItems("all");$("#history-clear-selection").focus()};$("#history-clear-selection").onclick=()=>{selectHistoryItems("clear");$("#history-select-all").focus()};
  $("#history-bulk-action").onclick=()=>confirmSelectedHistory($("#history-bulk-action"));
  $("#timeline").onchange=event=>{const input=event.target.closest("[data-history-select]");if(input)selectHistoryItems("toggle",input.dataset.historyKind,input.dataset.historyId,input.checked)};
  $("#history-retry").onclick=()=>retryHistory();
  document.querySelectorAll('[data-view="history"]').forEach(link=>link.addEventListener("click",()=>retryHistory()));
  $("#timeline").onclick=event=>{const open=event.target.closest("[data-history-open]");if(open){withBusy(()=>openHistoryEntry(open.dataset.historyKind,open.dataset.historyOpen)).catch(fail);return}const b=event.target.closest("[data-history-action]");if(b)confirmHistoryAction(b.dataset.historyAction,b.dataset.historyKind,b.dataset.historyId,b)};
  $("#history-confirm-submit").onclick=submitHistoryAction;$("#history-confirm-cancel").onclick=closeHistoryConfirmation;
  $("#history-confirm-refresh").onclick=async()=>{closeHistoryConfirmation();await retryHistory();$("#history-retry").focus()};
  dialog.addEventListener("cancel",event=>{event.preventDefault();closeHistoryConfirmation()});
}

async function saveScreen(){const c=revisionContent();if(!c.predicates.length)throw new Error("재무 조건을 하나 이상 추가해 주세요.");if(!c.columns.length)throw new Error("표시 항목을 하나 이상 선택해 주세요.");$("#save-state").textContent="저장 중…";const r=S.revision?await api(`/api/screens/${S.revision.screen_id}/revisions`,{method:"POST",body:JSON.stringify({content:c,dataset_id:$("#dataset").value})}):await api("/api/screens",{method:"POST",body:JSON.stringify({name:$("#screen-name").value,content:c,dataset_id:$("#dataset").value})});S.revision=r;S.dirty=false;$("#screen-name").readOnly=true;$("#save-state").textContent=`저장됨 · v${r.revision_number}`;$("#screen-context").textContent=`${$("#screen-name").value} · v${r.revision_number}`;await refreshScreens();$("#saved-screen").value=r.revision_id;toast("조건을 저장했습니다.")}
function columnEnabled(c,g){const a={company:["company","ticker","name","cik"],aggregate:["aggregate"],predicates:["predicates"],decision:["decision"]};return(a[g]||[g]).some(x=>c.includes(x))}
function loadScreenRecord(s){if(!s)return;S.revision=s;S.dirty=false;$("#screen-name").value=s.name;$("#screen-name").readOnly=true;const c=s.content;$("#universe-mode").value=c.universe.mode;toggleUniverse();S.companySelection=new Set(c.universe.mode==="CIKS"?(c.universe.ciks||[]):[]);renderCompanyOptions();if(c.universe.mode==="SIC")$("#industry-select").value=(c.universe.sic_codes||[])[0]||"";const quarterly=quarterlyScreenPolicy(c.period_policy);S.screenAvailability=c.period_policy.availability||null;$("#frequency").value=quarterly?"QUARTERLY":"ANNUAL";S.frequency=quarterly?"QUARTERLY":"ANNUAL";syncScreenPeriodModes();if(quarterly&&c.period_policy.mode==="FIXED_CALENDAR_QUARTER_END")$("#calendar-quarter").value=`${c.period_policy.calendar_year}Q${c.period_policy.calendar_quarter}`;if(!quarterly||batchView.enabled)$("#period-mode").value=c.period_policy.mode;togglePeriod();if(c.period_policy.fiscal_year)$("#fiscal-year").value=c.period_policy.fiscal_year;$("#period-offset").value=c.period_policy.offset||0;$("#predicates").innerHTML="";c.predicates.forEach(predicateRow);const sort=$("#sort-column");if(![...sort.options].some(x=>x.value===c.sort.column)){const o=document.createElement("option");o.value=c.sort.column;o.textContent="저장된 정렬";sort.append(o)}sort.value=c.sort.column;$("#sort-direction").value=c.sort.direction;$$('[name="visible-column"]').forEach(x=>x.checked=columnEnabled(c.columns,x.value));$("#screen-context").textContent=`${s.name} · v${s.revision_number}`;$("#save-state").textContent="저장된 조건"}
function toggleUniverse(){const m=$("#universe-mode").value;$("#company-select-label").hidden=m!=="CIKS";$("#industry-select-label").hidden=m!=="SIC"}
function togglePeriod(){
  const q=$("#frequency").value==="QUARTERLY",mode=$("#period-mode").value,latest=latestScreenPolicy({mode}),f=mode==="FIXED_FISCAL_YEAR";
  $("#period-mode").closest("label").hidden=q&&!batchView.enabled;
  $("#calendar-quarter-label").hidden=!q||latest;$("#fiscal-year-label").hidden=q||!f;$("#offset-label").hidden=q||f||latest;
  const status=$("#screen-batch-status");if(status){const scoped=latest||Boolean(S.screenAvailability&&(q||f));status.hidden=!scoped;status.textContent=scoped?availabilityCaption(S.screenAvailability):""}
}
function quarterLabel(x){const months=({1:"1–3월",2:"4–6월",3:"7–9월",4:"10–12월"})[x.calendar_quarter];return`${x.calendar_year}년 ${months}에 종료한 분기`}
async function switchFrequency(){clearResult();const target=$("#frequency").value==="QUARTERLY"?"QUARTERLY":"ANNUAL",q=target==="QUARTERLY",draft=S.frequencyDrafts[target],d=batchView.enabled?(draft?.dataset||S.explorerDataset||S.defaultDataset):q?S.defaultDataset:(draft?.dataset||S.defaultDataset);$("#dataset").value=d.dataset_id;$("#asof").textContent=d.financial_as_of;await loadCompanies(d.dataset_id,++S.contextToken);if(q){const [catalog,periods]=await Promise.all([api(`/api/quarter-metric-catalog?dataset_id=${encodeURIComponent(d.dataset_id)}`),api(`/api/quarter-periods?dataset_id=${encodeURIComponent(d.dataset_id)}`)]);S.catalog=catalog;S.quarterSpine=periods.spine;$("#calendar-quarter").innerHTML=periods.spine.map(x=>`<option value="${x.calendar_year}Q${x.calendar_quarter}">${quarterLabel(x)}</option>`).join("");$("#calendar-quarter").value=`${periods.spine.at(-1).calendar_year}Q${periods.spine.at(-1).calendar_quarter}`}else await loadCatalog(d.dataset_id,S.contextToken);if(draft){loadScreenRecord({name:draft.name,content:draft.content,revision_number:draft.revision?.revision_number||"저장 전"});S.revision=draft.revision;S.dirty=draft.dirty;$("#saved-screen").value=draft.revision?.revision_id||"";$("#screen-name").readOnly=Boolean(draft.revision);$("#save-state").textContent=draft.dirty?"수정됨 · 저장 필요":draft.revision?"저장된 조건":"저장 전 · 저장 필요"}else{$("#frequency").value=target;$("#predicates").innerHTML="";predicateRow();S.revision=null;S.dirty=true;$("#saved-screen").value="";$("#screen-name").readOnly=false;$("#screen-name").value="";$("#screen-context").textContent="새 조건 · 저장 전";$("#save-state").textContent="저장 전 · 저장 필요"}S.frequency=target;if(!draft&&batchView.enabled){S.screenAvailability=batchView.snapshot?.dataset_id===d.dataset_id?batchView.snapshot:null;syncScreenPeriodModes();if(S.screenAvailability)$("#period-mode").value=q?LATEST_QUARTER_POLICY:LATEST_ANNUAL_POLICY}togglePeriod()}

async function execute(){const content=revisionContent();clearResult();$("#result-body").innerHTML='<tr><td colspan="5" class="empty">기업을 찾는 중…</td></tr>';const r=await api("/api/preview",{method:"POST",body:JSON.stringify({content,dataset_id:$("#dataset").value})});S.preview=r;setRun(r,content);toast("시험 실행입니다. 필요한 결과만 저장하세요.")}
async function saveResult(){const p=S.preview;if(!p)throw new Error("조건을 시험 실행한 뒤 결과를 저장해 주세요.");const name=$("#screen-name").value.trim()||"스크리닝 결과",sameRevision=S.revision?.content_hash===p.condition_hash&&(!S.revision.saved_context||S.revision.saved_context.dataset_id===p.dataset_id);const r=await api("/api/results",{method:"POST",body:JSON.stringify({name,content:p.content,dataset_id:p.dataset_id,preview_hash:p.preview_hash,revision_id:sameRevision?S.revision.revision_id:null})});S.preview=null;setRun(r,p.content);await refreshRuns();toast("결과를 저장했습니다. 이력에서 다시 열 수 있습니다.")}
const screeningReview={run:null,changed:false};
function syncScreeningPresentation(changed=false){
  if(resultProfileSession.active&&resultProfileSession.run!==S.run)closeResultProfile(false);
  if(screeningReview.run!==S.run){screeningReview.run=S.run;screeningReview.changed=false}if(changed&&S.run)screeningReview.changed=true;
  $("#results-title")?.closest?.(".workspace")?.classList.toggle("result-ready",Boolean(S.run));
  $(".criteria")?.classList.toggle("preview-ready",Boolean(S.preview));
  $("#history-title")?.closest?.(".history")?.classList.toggle("export-ready",Boolean(S.run?.run_id));
  const state=$("#screening-result-state");if(state)state.textContent=!S.run?"실행 전 · 조건을 시험 실행하면 결과를 비교할 수 있습니다.":S.preview?"현재 조건의 시험 실행 결과 · 결과 저장 가능":S.run.run_id&&!screeningReview.changed?"저장된 실행 결과":"이전 실행 결과 · 수정한 조건은 다시 시험 실행해야 합니다.";
  const note=$("#results-draft-note");
  if(note&&(!S.run||changed))note.hidden=!S.run;
}
function mountScreeningWorkbench(){
  const form=$("#criteria-form");if(form.dataset.workbenchMounted)return;
  form.dataset.workbenchMounted="true";
  const identity=form.querySelector(".condition-identity"),name=$("#screen-name").closest("label");
  const saved=document.createElement("details");saved.className="screening-saved-controls";
  saved.innerHTML='<summary>저장 조건 불러오기</summary><div class="screening-saved-fields"></div>';
  saved.querySelector(".screening-saved-fields").append($("#saved-screen").closest("label"),$("#open-screen"));
  const period=document.createElement("fieldset");period.className="screening-period-fields";
  period.innerHTML='<legend>분석 기간</legend>';
  period.append(...["#frequency","#period-mode","#fiscal-year","#calendar-quarter","#period-offset"].map(id=>$(id).closest("label")));
  const inputContext=document.createElement("div");inputContext.className="screening-input-context";
  inputContext.append(period,form.querySelector(".company-scope"));
  identity.replaceChildren(name,saved);identity.after(inputContext);
  const workspace=$("#results-title").closest(".workspace"),toolbar=document.createElement("div");
  toolbar.className="screening-result-toolbar";
  toolbar.append(workspace.querySelector(".filters"),workspace.querySelector(".pass-only"));
  workspace.querySelector(".section-head").after(toolbar);
}
function screeningResultMetricCell(predicate,metric){
  const observation=predicate.observation||{},missing=observation.value===null||observation.value===undefined;
  const reason=missing?businessReason(predicate.reason):"",period=actualPeriod(observation);
  const value=missing?reason:`${displayValue(observation.value,metric)} ${unitLabel(metric)}`;
  const tooltip=`${metric.label} · ${value} · 실제 기간 ${period}${missing?"":` · 공표값 ${observation.value} ${metric.unit||unitLabel(metric)}`}`;
  const content=missing?`<span class="missing" aria-label="${esc(tooltip)}">—</span><small>자료 확인 필요</small>`:
    `<span class="display-number explorer-value" title="${esc(tooltip)}" aria-label="${esc(tooltip)}"><span class="number-text">${esc(displayValue(observation.value,metric))}</span><span class="number-clipped" aria-hidden="true">…</span></span>`;
  return `<td class="metric-cell" title="${esc(tooltip)}">${content}</td>`;
}
function displayTableColumnRoles(role,headings){
  return headings.map((cell,index)=>{
    if(cell.hidden)return "hidden";
    if(role==="explorer")return ["select","company","period"][index]||"number";
    if(role==="results")return index===0?"select":index===1?"company":index===2||index===headings.length-1?"status":cell.dataset?.displayRole==="period"?"period":"number";
    if(role==="comparison")return index===0?"label":"number";
    return index===(role==="peer"?3:2)?"number":index===(role==="peer"?2:1)?"period":"context";
  });
}
function mountScreeningPresentation(){
  mountScreeningWorkbench();
  $("#money-note").textContent="금액 단위: 백만 USD";
  const quarterOption=[...$("#frequency").options].find(option=>option.value==="QUARTERLY");if(quarterOption)quarterOption.textContent="분기·TTM";
  if(!$("#screening-review-shell")){const shell=document.createElement("div");shell.id="screening-review-shell";shell.dataset.taskView="screening";const context=$(".context"),criteria=$(".criteria"),workspace=$("#results-title").closest(".workspace"),editor=document.createElement("div");editor.className="screening-editor-column";context.before(shell);editor.append(context,criteria);shell.append(editor,workspace);const status=document.createElement("p");status.id="screening-result-state";status.setAttribute("role","status");$("#counts").before(status)}
  $(".criteria .section-head p").textContent="조건과 실행 결과는 따로 저장할 수 있습니다.";
  const note=document.createElement("p");
  note.id="results-draft-note";note.hidden=true;note.setAttribute("role","status");
  note.textContent="마지막 실행 결과입니다. 편집한 조건을 보려면 다시 시험 실행하세요.";
  $("#counts").after(note);
  const cancel=document.createElement("button");cancel.type="button";cancel.id="result-profile-cancel";cancel.className="quiet";cancel.textContent="프로필 조회 취소";cancel.hidden=true;cancel.onclick=()=>closeResultProfile(true);$("#screening-result-state").after(cancel);
  syncScreeningPresentation();
}
function syncResultActions(){syncScreeningPresentation();const blocked=journalHistory.configured===true&&(Boolean(journalHistory.error)||journalHistory.pending),saved=Boolean(S.run?.run_id)&&!blocked;["#save-screen","#open-screen","#open-run","#compare-runs"].forEach(id=>{if(blocked)$(id).disabled=true;else if(!S.busy)$(id).disabled=false});$("#save-result").disabled=S.busy||blocked||!S.preview;["#export-selected-csv","#export-selected-xlsx","#export-full-csv","#export-full-xlsx","#save-decision"].forEach(id=>$(id).disabled=S.busy||!saved)}
async function withBusy(action){if(S.busy)return;S.busy=true;$("#criteria-error").hidden=true;const controls=$$("#criteria-form input,#criteria-form select,#criteria-form button,.criteria .button-row button,#open-run,#compare-runs,#result-body button.company,[data-guide-add]");const before=controls.map(x=>[x,x.disabled]);controls.forEach(x=>x.disabled=true);syncResultActions();try{return await action()}finally{S.busy=false;before.forEach(([x,disabled])=>{if(x.isConnected)x.disabled=disabled});syncResultActions()}}
function clearResult(){S.run=null;S.preview=null;S.resultContent=null;S.selected.clear();$("#result-body").innerHTML='<tr><td colspan="5" class="empty">조건을 시험 실행하면 결과가 표시됩니다.</td></tr>';$("#counts").textContent="실행 전";$("#evidence").hidden=true;syncResultActions()}
function setRun(r,content){S.run=r;const note=$("#results-draft-note");if(note)note.hidden=true;S.resultContent=content||S.revision?.content;S.selected.clear();$("#period-context").title=latestScreenPolicy(r.period_policy)?`회사별 최신 · ${availabilityCaption(r.period_policy.availability)}`:"";$("#period-context").textContent=latestScreenPolicy(r.period_policy)?`회사별 최신 · ${quarterlyScreenPolicy(r.period_policy)?"분기":"연간"}`:r.period_policy.mode==="FIXED_FISCAL_YEAR"?`FY${r.period_policy.fiscal_year}`:r.period_policy.mode==="FIXED_CALENDAR_QUARTER_END"?quarterLabel(r.period_policy):`최근 완료 연도${r.period_policy.offset?` -${r.period_policy.offset}`:""}`;$("#asof").textContent=r.financial_as_of;$("#counts").textContent=`${r.run_id?"저장된 결과":"시험 결과 · 저장 전"} · 대상 ${r.counts.target} · 충족 ${r.counts.pass} · 미충족 ${r.counts.fail} · 확인 필요 ${r.counts.undetermined}`;renderRows();syncResultActions();setCriteriaCompact(true)}
function selectedMetrics(){return(S.resultContent?.predicates||[]).map(x=>metricById(x.metric_id))}
function decisionFor(cik){const e=S.decisions.filter(x=>x.cik===cik);return e.length?`<span class="badge review">${decisionLabel(e.at(-1).state)}</span>`:'<span class="muted">기록 없음</span>'}
function renderRows(){if(!S.run)return;const ms=selectedMetrics(),latest=latestScreenPolicy(S.run.period_policy),showCompany=!S.admin||columnEnabled(S.resultContent.columns,"company");$("#result-head").innerHTML=`<tr><th><span class="sr-only">선택</span></th><th ${showCompany?'':'hidden'}>기업</th><th>결과</th>${latest?'<th data-display-role="period">선택 재무기간</th>':""}${ms.map(m=>`<th title="${esc(m.label)} · ${esc(unitLabel(m))}">${esc(explorerMetricCaption(m))}<br><small>${esc(unitLabel(m))}</small></th>`).join("")}<th>관심상태</th></tr>`;const rows=S.run.rows.filter(r=>S.activeFilter==="ALL"||r.aggregate===S.activeFilter).filter(r=>$("#show-all").checked||r.aggregate==="PASS");$("#result-body").innerHTML=rows.length?rows.map(row=>`<tr data-cik="${row.cik}" class="${S.selected.has(row.cik)?'selected':''}"><td><input type="checkbox" aria-label="${esc(row.ticker)} 선택" ${S.selected.has(row.cik)?'checked':''}></td><td ${showCompany?'':'hidden'}><button class="company" data-open="${row.cik}" title="${esc(row.name||row.ticker)} · ${esc(row.ticker)}" aria-label="${esc(row.name||row.ticker)} 재무 상세 열기"><strong>${esc(row.name||row.ticker)}</strong><small>${esc(row.ticker)}</small></button><button type="button" class="quiet result-evidence" data-result-evidence="${esc(row.cik)}">조건 근거</button></td><td><span class="badge ${row.aggregate.toLowerCase()}">${aggregateLabel(row.aggregate)}</span></td>${latest?`<td>${companyFinancialPeriodDisplay(row.resolved_period)}</td>`:""}${row.predicates.map(predicate=>screeningResultMetricCell(predicate,metricById(predicate.metric_id))).join("")}<td>${decisionFor(row.cik)}</td></tr>`).join(""):`<tr><td colspan="${4+ms.length+(latest?1:0)}" class="empty">해당하는 기업이 없습니다.</td></tr>`;$$('[data-cik] input').forEach(x=>x.onchange=()=>{const c=x.closest("tr").dataset.cik;x.checked?S.selected.add(c):S.selected.delete(c);renderRows()});$$('[data-open]').forEach(x=>x.onclick=()=>openResultProfile(x.dataset.open,x).catch(fail));$$('[data-result-evidence]').forEach(x=>x.onclick=()=>withBusy(()=>openEvidence(x.dataset.resultEvidence,x)).catch(fail))}

// A result opens a read-only analysis session; screen/run state is never rewritten.
const resultProfileSession={token:0,active:false,saved:null,run:null};
function resultProfilePeriod(run,row,content){
  const policy=run.period_policy||content?.period_policy||{},latest=latestScreenPolicy(policy),quarterly=quarterlyScreenPolicy(policy),allTTM=row.predicates.length>0&&row.predicates.every(item=>S.catalog.find(metric=>metric.metric_id===item.metric_id)?.observation_basis==="TTM");
  if(latest)return{basis:quarterly?(allTTM?"TTM":"QUARTERLY"):"ANNUAL",latest:true,anchor:row.resolved_period};
  if(policy.mode==="FIXED_FISCAL_YEAR")return{basis:"ANNUAL",latest:false,year:policy.fiscal_year};
  if(policy.mode==="FIXED_CALENDAR_QUARTER_END")return{basis:allTTM?"TTM":"QUARTERLY",latest:false,quarter:`${policy.calendar_year}Q${policy.calendar_quarter}`};
  const observations=row.predicates.map(item=>item.observation),years=[...new Set(observations.map(item=>item?.fiscal_year).filter(Number.isInteger))],ends=new Set(observations.map(item=>item?.period_end)),starts=new Set(observations.map(item=>item?.period_start).filter(Boolean));
  if(!quarterly&&years.length===1&&observations.every(item=>item&&Number.isInteger(item.fiscal_year)&&item.period_end)&&ends.size===1&&starts.size<=1)return{basis:"ANNUAL",latest:false,year:years[0]};
  throw new Error("조건별 기간이 다르거나 고정 기간을 확인할 수 없어 전체 프로필을 연결할 수 없습니다. 조건 근거 상세는 유지됩니다.");
}
function captureResultProfileContext(button){
  const fields=["explorerDataset","explorerYear","explorer","explorerCatalog","explorerCatalogKey","explorerSelected","profile","profileMetric","lastFocus"];
  const basisFields=["basis","latestAnnual","loading","readyKey","inventoryKey","inventoryPromise","inventory","snapshots","snapshot","metrics","periods","views","profileBasis","profileMetrics","profileKey","unavailableReason","visibleRows"];
  const controls=["#explorer-query","#explorer-preset","#explorer-sort","#explorer-direction","#explorer-year","#explorer-quarter","#explorer-basis","#comparison-metrics","#comparison-metric-query","#comparison-metric-category"];
  return{state:Object.fromEntries(fields.map(key=>[key,S[key]])),basis:Object.fromEntries(basisFields.map(key=>[key,["periods","views","profileMetrics"].includes(key)?JSON.parse(JSON.stringify(explorerBasis[key])):explorerBasis[key]])),controls:controls.map(selector=>({selector,value:$(selector).value,html:$(selector).tagName==="SELECT"?$(selector).innerHTML:null,selected:$(selector).multiple?[...$(selector).options].filter(option=>option.selected).map(option=>option.value):null})),columns:{scope:annualColumnSelection.scope,order:annualColumnSelection.order?.slice()||null,status:annualColumnSelection.status,error:annualColumnSelection.error},picker:{query:comparisonPicker.query,category:comparisonPicker.category},desktop:{mode:desktopExplorer.mode,saved:desktopExplorer.saved?{...desktopExplorer.saved}:null},page:window.scrollY,top:$(".explorer-matrix").scrollTop,left:$(".explorer-matrix").scrollLeft,button};
}
function closeResultProfile(returnView=true){
  if(!resultProfileSession.active)return;
  const saved=resultProfileSession.saved;resultProfileSession.active=false;resultProfileSession.token++;resultProfileSession.saved=null;resultProfileSession.run=null;
  explorerBasis.version++;explorerBasis.loadToken++;explorerBasis.profileToken++;explorerBasis.seriesToken++;explorerBasis.comparisonToken++;S.explorerToken++;S.explorerCatalogToken++;
  closeProfile(false);closeExplorerComparison(false);Object.assign(S,saved.state);Object.assign(explorerBasis,saved.basis);Object.assign(desktopExplorer,saved.desktop);Object.assign(annualColumnSelection,saved.columns);Object.assign(comparisonPicker,saved.picker);
  for(const control of saved.controls){const node=$(control.selector);if(control.html!==null)node.innerHTML=control.html;node.value=control.value;if(control.selected)for(const option of node.options)option.selected=control.selected.includes(option.value)}
  $(".explorer-view").classList.remove("result-profile-session","analysis-open");$("#explorer-analysis-bar").hidden=true;
  $("#explorer-back-to-list").textContent="← 목록으로";$("#result-profile-cancel").hidden=true;
  if(S.explorer)renderExplorer();$(".explorer-matrix").scrollTop=saved.top;$(".explorer-matrix").scrollLeft=saved.left;
  if(returnView){showView("screening");window.scrollTo({top:saved.page,left:0,behavior:"instant"});const target=saved.button?.isConnected?saved.button:$("#results-title");target?.focus({preventScroll:true})}
}
async function openResultProfile(cik,button){
  if(!S.run)throw new Error("먼저 실행 결과를 선택해 주세요.");
  if(resultProfileSession.active)closeResultProfile(false);
  const run=S.run,row=run.rows.find(item=>item.cik===cik);if(!row)return;
  const period=resultProfilePeriod(run,row,S.resultContent),token=++resultProfileSession.token,saved=captureResultProfileContext(button);
  resultProfileSession.active=true;resultProfileSession.saved=saved;resultProfileSession.run=run;
  const current=()=>resultProfileSession.active&&token===resultProfileSession.token&&run===S.run;
  $("#screening-result-state").textContent="원래 실행 발행물·재무기간으로 전체 프로필을 불러옵니다…";$("#result-profile-cancel").hidden=false;
  try{
    const status=await api("/api/status");if(!current())return;
    const dataset=status.datasets.find(item=>item.dataset_id===run.dataset_id&&(item.publication_id||item.dataset_publication_id)===run.dataset_publication_id&&item.financial_as_of===run.financial_as_of);
    if(!dataset)throw new Error("저장 결과의 원래 발행물을 현재 조회할 수 없습니다. 최신 자료로 대신 열지 않습니다.");
    S.explorerDataset=dataset;S.explorer={dataset_id:run.dataset_id,dataset_publication_id:run.dataset_publication_id,financial_as_of:run.financial_as_of,rows:[],fiscal_years:[]};S.explorerSelected=new Set();S.explorerCatalog=null;S.explorerCatalogKey=null;S.explorerToken++;S.explorerCatalogToken++;
    explorerBasis.version++;explorerBasis.profileToken++;explorerBasis.seriesToken++;explorerBasis.comparisonToken++;explorerBasis.basis=period.basis;explorerBasis.latestAnnual=period.latest;explorerBasis.snapshots=new Map();explorerBasis.inventory=null;explorerBasis.inventoryKey=null;explorerBasis.inventoryPromise=null;explorerBasis.periods={QUARTERLY:period.latest?"LATEST":period.quarter,TTM:period.latest?"LATEST":period.quarter};explorerBasis.views={...saved.basis.views};
    const scope={dataset_id:run.dataset_id,dataset_publication_id:run.dataset_publication_id};
    if(period.basis==="ANNUAL"){
      const profile=await api(`/api/company-profile?${new URLSearchParams({...scope,cik,...(period.latest?{latest:"true"}:{fiscal_year:String(period.year)})})}`);if(!current())return;
      if(profile.dataset_id!==run.dataset_id||profile.dataset_publication_id!==run.dataset_publication_id||profile.financial_as_of!==run.financial_as_of||profile.company?.cik!==cik||!period.latest&&profile.selected_fiscal_year!==period.year||period.latest&&!samePublishedPeriod(profile.resolved_period,period.anchor))throw new Error("전체 프로필의 발행물·실제 기간이 실행 결과와 다릅니다.");
      S.explorerYear=profile.selected_fiscal_year;const catalog=await api(`/api/metric-library?${new URLSearchParams({...scope,fiscal_year:String(S.explorerYear)})}`);if(!current())return;S.explorerCatalog=catalog;S.explorerCatalogKey=`${dataset.dataset_id}:${S.explorerYear}`;
      S.explorer={...profile,rows:run.rows.map(item=>({company:{...item},resolved_period:item.resolved_period,metrics:{}})),resolved_periods:Object.fromEntries(run.rows.map(item=>[item.cik,item.resolved_period]))};
      S.profile=profile;explorerBasis.profileBasis="ANNUAL";S.profileMetric=explorerBasis.profileMetrics.ANNUAL;renderProfile();profileTrendCaption(false);
    }else{
      const coordinate=period.quarter?.match(/^(\d{4})Q([1-4])$/),snapshot=await api(`/api/quarter-explorer?${new URLSearchParams({...scope,...(period.latest?{latest:"true"}:{calendar_year:coordinate[1],calendar_quarter:coordinate[2]})})}`);if(!current())return;
      const target=snapshot.rows.find(item=>item.company.cik===cik);if(snapshot.dataset_id!==run.dataset_id||snapshot.dataset_publication_id!==run.dataset_publication_id||snapshot.financial_as_of!==run.financial_as_of||!target||!period.latest&&periodCoordinate(snapshot)!==period.quarter||period.latest&&!samePublishedPeriod(target.period,period.anchor))throw new Error("분기 프로필의 발행물·실제 기간이 실행 결과와 다릅니다.");
      explorerBasis.snapshot={...snapshot,rows:snapshot.rows.filter(item=>run.rows.some(result=>result.cik===item.company.cik))};explorerBasis.metrics=snapshot.metrics;S.explorerYear=target.period?.fiscal_year||snapshot.calendar_year;
      const inventory=await api(`/api/quarter-periods?${new URLSearchParams(scope)}`);if(!current())return;explorerBasis.inventory=inventory;explorerBasis.inventoryKey=dataset.dataset_id;explorerBasis.readyKey=explorerContextKey();
      await openProfile(cik,button,true,true);if(!current())return;
    }
    explorerBasis.readyKey=explorerContextKey();showView("explorer");$(".explorer-view").classList.add("result-profile-session");showCompanyProfile();
    $("#explorer-back-to-list").textContent="← 스크리닝 결과로";$("#analysis-context").textContent=`실행 결과의 전체 프로필 · ${period.latest?"회사별 최신":period.basis==="ANNUAL"?`FY${period.year}`:period.quarter} · ${period.basis==="ANNUAL"?"연간":"분기·TTM"}`;$("#analysis-context").title=`${run.dataset_id} · ${run.dataset_publication_id} · 재무 기준일 ${run.financial_as_of}`;
  }catch(error){if(current()){closeResultProfile(true);$("#screening-result-state").textContent=error.message;throw error}}
}

async function openEvidence(cik,b){S.lastFocus=b;S.evidenceRow=S.run.rows.find(x=>x.cik===cik);const r=S.evidenceRow;$("#evidence-title").textContent=`${r.name||r.ticker} 재무 상세`;$("#evidence-metric").innerHTML=r.predicates.map(x=>`<option value="${x.metric_id}">${esc(metricById(x.metric_id).label)}</option>`).join("");const p=await api(`/api/peers?dataset_id=${encodeURIComponent(S.run.dataset_id)}&dataset_publication_id=${encodeURIComponent(S.run.dataset_publication_id)}&cik=${cik}`);$("#peer-company").innerHTML='<option value="">기업 선택</option>'+p.peers.filter(x=>x.financial_prepared).map(x=>`<option value="${x.cik}">${esc((x.tickers||[])[0]||x.name)}</option>`).join("");$("#peer-comparison").textContent="같은 업종의 넓은 후보군이며 재무항목이 같다는 뜻은 아닙니다.";$("#evidence").dataset.cik=cik;$("#evidence").hidden=false;await renderMetricEvidence();$("#evidence").focus()}
function metricHelp(m){
  const kind=m.input_contract?.kind,meanings={
    ADJACENT_FISCAL_QUARTER_GROWTH:"현재 분기 매출과 직전 회계분기 매출을 비교한 공표 성장률입니다.",
    SAME_FISCAL_QUARTER_YOY_GROWTH:"현재 분기 매출과 전년 같은 회계분기 매출을 비교한 공표 성장률입니다.",
    TTM_PERIOD_SUM_RATIO:"최근 12개월의 분자 항목 합계를 분모 항목 합계로 나눈 공표 비율입니다. 분기별 비율을 더한 값이 아닙니다.",
    SAME_PERIOD_RATIO:"같은 기간의 공표된 입력 항목을 나눈 계산 지표입니다.",
    SAME_PERIOD_DIFFERENCE:"같은 기간의 공표된 입력 항목의 차이로 준비한 계산 지표입니다.",
  },annual={revenue_yoy:"해당 회계연도 매출과 직전 회계연도 매출을 비교한 공표 성장률입니다.",gross_margin:"매출총이익을 매출로 나눈 비율입니다.",operating_margin:"영업이익을 매출로 나눈 비율입니다.",net_margin:"순이익을 매출로 나눈 비율입니다.",standardized_fcf:"영업활동 현금흐름에서 유형자산 취득 지출을 뺀 표준화 지표입니다. 회사가 별도로 제시하는 FCF와 같다는 뜻은 아닙니다.",fcf_margin:"표준화 FCF를 매출로 나눈 비율입니다.",current_ratio:"유동자산을 유동부채로 나눈 기말 비율입니다.",liabilities_to_equity:"부채총계를 자본으로 나눈 비율입니다. 부채총계는 차입금과 다릅니다.",liabilities_to_assets:"부채총계를 자산으로 나눈 비율입니다.",net_debt:"직접 보고된 결합 차입금에서 현금 및 현금성자산을 뺀 금액입니다."};
  const source=metricPresentation(m).source,ttm=(m.observation_basis||m.period_class)==="TTM";
  const description=m.description||meanings[kind]||annual[m.metric_id]||(ttm?"최근 12개월(TTM)의 공표된 계산 지표입니다. 계산 방식은 아래 발행 정의를 따릅니다.":source==="계산 지표"?"공표된 입력과 계산 정의로 준비한 지표입니다.":source==="회사 보고"?"회사가 보고한 공시 항목입니다.":"공표된 지표입니다. 출처와 정의를 함께 확인해 주세요.");
  const arithmetic=["ARITHMETIC_ONLY_NOT_RECAST_VALIDATED","DECLARED_EQUAL_OR_ALL_NULL_ARITHMETIC_V1"].includes(m.input_contract?.basis_policy||m.basis_policy)&&!description.includes("회계기준")?"산술 비교이며 회계기준 변경을 조정한 비교 수치라고 주장하지 않습니다.":"";
  return[description,m.formula?`공표 계산 정의: ${m.formula}`:"",arithmetic].filter(Boolean).join(" ");
}
function quarterSourceLabel(v){return({REPORTED:"보고값",DERIVED_QUARTER:"승인된 분기 계산",DERIVED_METRIC:"승인된 파생지표",UNAVAILABLE:"자료 확인 필요"})[v]||"자료 확인 필요"}
function actualPeriod(x){const end=x.period_end?inclusiveEnd(x.period_end):x.context_end_date;return x.period_start?`${x.period_start} ~ ${end||"—"}`:end||"—"}
function fiscalLabel(x){return x.fiscal_year&&x.fiscal_quarter?`FY${x.fiscal_year} ${x.fiscal_quarter}`:"—"}
// Compact ordinary captions are separate from exact period/selection helpers.
function compactFinancialDate(value){
  return comparisonDate(value)?value.slice(2).replaceAll("-","."):typeof value==="string"&&value?value:"—";
}
function compactFinancialDateText(full){
  return String(full??"—").replace(/\b\d{4}-\d{2}-\d{2}\b/gu,date=>compactFinancialDate(date)).replaceAll(" ~ ","–");
}
function financialDateCaption(compact,full){
  const lines=String(compact??"—").split("\n").map(line=>esc(line).replace(/\b\d{2}\.\d{2}\.\d{2}\b/gu,date=>`<span class="financial-date-token">${date}</span>`).replaceAll("–","–<wbr>"));
  return `<span class="financial-date" data-financial-date title="${esc(full??"—")}" aria-label="${esc(full??"—")}">${lines.map(line=>`<span class="financial-date-line">${line}</span>`).join("")}</span>`;
}
function compactFinancialCaption(full){const caption=full??"—";return financialDateCaption(compactFinancialDateText(caption),caption)}
function financialPeriodDisplay(observation){return compactFinancialCaption(actualPeriod(observation))}
function companyFinancialPeriodDisplay(period){
  const full=companyPeriodCaption(period),compact=compactFinancialDateText(full).replace(" · 공시일 ","\n공시 ").replace(/^공시일 /u,"공시 ");
  return financialDateCaption(compact,full);
}
async function renderMetricEvidence(){const id=$("#evidence-metric").value,m=metricById(id),r=S.evidenceRow,e=r.predicates.find(x=>x.metric_id===id),o=e.observation||{},quarterly=quarterlyScreenPolicy(S.run.period_policy),seriesPath=quarterly?`/api/quarter-series?dataset_id=${encodeURIComponent(S.run.dataset_id)}&dataset_publication_id=${encodeURIComponent(S.run.dataset_publication_id)}&cik=${r.cik}&metric_id=${encodeURIComponent(id)}&limit=8`:`/api/series?dataset_id=${encodeURIComponent(S.run.dataset_id)}&dataset_publication_id=${encodeURIComponent(S.run.dataset_publication_id)}&cik=${r.cik}&metric_id=${encodeURIComponent(id)}`;const [series,trace]=await Promise.all([api(seriesPath+(latestScreenPolicy(S.run.period_policy)?"&latest=true":"")),S.run.run_id?api(`/api/runs/${encodeURIComponent(S.run.run_id)}/trace?cik=${r.cik}&metric_id=${encodeURIComponent(id)}`):Promise.resolve({evaluation:e})]),source=trace.evaluation?.observation||o,filings=source.source_filings||[],inputs=(m.input_metric_ids||[]).map(x=>metricById(x).label),basis=metricPresentation(m).period;$("#evidence-content").innerHTML=`<div class="financial-summary"><div><span>${esc(m.label)}</span><strong>${o.value===null||o.value===undefined?'—':numberMarkup(o.value,m)} ${unitLabel(m)}</strong></div><div><span>자료 기간</span><strong>${financialPeriodDisplay(o)}</strong></div></div><p>${esc(metricHelp(m))}</p>${inputs.length?`<p class="muted">계산 입력: ${inputs.map(esc).join(", ")}</p>`:""}<p>${esc(basis)} · ${esc(metricPresentation(m).source)}${quarterly?` · ${esc(quarterSourceLabel(o.source_kind))} · ${esc(fiscalLabel(o))}`:""}</p>${filings.length?`<p class="muted">관련 공시 ${filings.map(esc).join(", ")}</p>`:""}${o.value===null||o.value===undefined?`<p class="message error">${esc(businessReason(e.reason))}</p>`:""}`;$("#series-content").innerHTML=`<table class="series-table"><thead><tr><th>${quarterly?"종료 분기 · 회사 회계표시":"연도"}</th><th>실제 기간</th><th>${esc(m.label)} (${unitLabel(m)})</th>${quarterly?"<th>자료 성격</th>":""}</tr></thead><tbody>${series.observations.map(x=>`<tr><td>${quarterly?`${esc(quarterLabel(x))}<small>${esc(fiscalLabel(x))}</small>`:x.fiscal_year}</td><td>${financialPeriodDisplay(x)}</td><td>${x.value===null||x.value===undefined?`<span title="${esc(businessReason(x.reason))}">—</span>`:numberMarkup(x.value,m)}</td>${quarterly?`<td>${esc(quarterSourceLabel(x.source_kind))}</td>`:""}</tr>`).join("")}</tbody></table>`}
async function comparePeer(){const peer=$("#peer-company").value;if(!peer)throw new Error("비교 기업을 선택해 주세요.");const id=$("#evidence-metric").value,m=metricById(id),quarterly=quarterlyScreenPolicy(S.run.period_policy);const latest=latestScreenPolicy(S.run.period_policy);let path;if(quarterly){const p=S.run.period_policy;path=`/api/quarter-comparison?dataset_id=${encodeURIComponent(S.run.dataset_id)}&dataset_publication_id=${encodeURIComponent(S.run.dataset_publication_id)}&ciks=${S.evidenceRow.cik},${peer}&metric_id=${encodeURIComponent(id)}&${latestScreenPolicy(p)?"latest=true":`calendar_year=${p.calendar_year}&calendar_quarter=${p.calendar_quarter}`}`}else if(latest){path=`/api/company-comparison?${new URLSearchParams({dataset_id:S.run.dataset_id,dataset_publication_id:S.run.dataset_publication_id,ciks:`${S.evidenceRow.cik},${peer}`,metric_ids:id,latest:"true"})}`}else{const e=S.evidenceRow.predicates.find(x=>x.metric_id===id),year=e.observation?.fiscal_year;if(!year)throw new Error("비교할 기간 자료가 없습니다.");path=`/api/peer-comparison?dataset_id=${encodeURIComponent(S.run.dataset_id)}&dataset_publication_id=${encodeURIComponent(S.run.dataset_publication_id)}&ciks=${S.evidenceRow.cik},${peer}&metric_id=${encodeURIComponent(id)}&fiscal_year=${year}`}const response=await api(path),r=latest&&!quarterly?{warning:response.date_limitation,rows:response.companies.map(company=>({company,observation:response.rows[0].values[company.cik]}))}:response;$("#peer-comparison").innerHTML=`${r.warning?`<p>${esc(r.warning)}</p>`:""}<table class="series-table"><thead><tr><th>기업</th><th>${quarterly?"회사 회계표시":"기간"}</th><th>실제 기간</th><th>${esc(m.label)} (${unitLabel(m)})</th></tr></thead><tbody>${r.rows.map(x=>`<tr><td>${esc(x.company.ticker)}</td><td>${quarterly?esc(fiscalLabel(x.observation||{})):esc(x.observation?.fiscal_year||"—")}</td><td>${financialPeriodDisplay(x.observation||{})}</td><td>${x.observation?.value===null||x.observation?.value===undefined?'—':numberMarkup(x.observation.value,m)}</td></tr>`).join("")}</tbody></table>`}
async function saveDecision(){if(!S.run?.run_id)throw new Error("결과를 저장한 뒤 관심상태를 기록해 주세요.");const cik=$("#evidence").dataset.cik,r=$("#decision-rationale").value.trim();if(!r)throw new Error("판단 메모를 입력해 주세요.");await api("/api/decisions",{method:"POST",body:JSON.stringify({cik,state:$("#decision-state").value,rationale:r,run_id:S.run.run_id,actor:"local-user",evidence_ids:[S.run.run_id]})});await refreshDecisions();renderRows();renderTimeline();toast("관심상태를 기록했습니다.")}
async function openRun(id){const epoch=journalHistory.epoch;if(!id)throw new Error("결과를 선택해 주세요.");const r=await api(`/api/runs/${id}`),v=await api(`/api/revisions/${r.revision_id}`);if(epoch!==journalHistory.epoch||historyHidden("RUN",id))return;await openSavedScreenRecord(v,r.dataset_id);if(epoch!==journalHistory.epoch||historyHidden("RUN",id))return;S.revision=S.screens.find(x=>x.revision_id===v.revision_id)||null;$("#screen-name").readOnly=Boolean(S.revision);$("#saved-screen").value=S.revision?.revision_id||"";if(historyHidden("REVISION",v.revision_id))detachHistoryRevision();S.preview=null;setRun(r,v.content);showView("screening",true)}
async function compareRuns(){const a=$("#old-run").value,b=$("#new-run").value;if(!a||!b)throw new Error("두 실행을 선택해 주세요.");const d=await api(`/api/run-comparison?old_run_id=${encodeURIComponent(a)}&new_run_id=${encodeURIComponent(b)}`);$("#run-diff").textContent=d.differences.length?`${d.differences.length}개 기업의 결과 또는 값이 달라졌습니다.`:"기업 결과는 동일합니다."}
async function exportRun(scope,format){if(!S.run?.run_id)throw new Error("결과를 저장한 뒤 다운로드해 주세요.");const c=scope==="SELECTED"?[...S.selected]:null;if(scope==="SELECTED"&&!c.length)throw new Error("기업을 하나 이상 선택해 주세요.");const r=await api(`/api/runs/${S.run.run_id}/exports`,{method:"POST",body:JSON.stringify({scope,format,selected_ciks:c})}),a=document.createElement("a");a.href=r.download_url;a.download="";document.body.append(a);a.click();a.remove();toast("결과 다운로드를 시작했습니다.")}
function normalizeMetric(x){if(x.category!=="LEGACY_REPORTED")return x;const category=({revenue:"GROWTH",operating_income:"PROFITABILITY",net_income:"PROFITABILITY",cfo:"CASH_FLOW"})[x.metric_id]||"OTHER_REPORTED";return{...x,category}}
async function loadCatalog(id,token){let catalog;try{catalog=(await api(`/api/metric-catalog?dataset_id=${encodeURIComponent(id)}`)).map(normalizeMetric)}catch(e){catalog=[{metric_id:"revenue",label:"매출",category:"GROWTH",unit_kind:"MONEY",unit:"USD",definition_version:"annual-core-reported-v1",period_class:"FY",coverage:{}},{metric_id:"operating_income",label:"영업이익",category:"PROFITABILITY",unit_kind:"MONEY",unit:"USD",definition_version:"annual-core-reported-v1",period_class:"FY",coverage:{}},{metric_id:"net_income",label:"순이익",category:"PROFITABILITY",unit_kind:"MONEY",unit:"USD",definition_version:"annual-core-reported-v1",period_class:"FY",coverage:{}},{metric_id:"cfo",label:"영업활동 현금흐름",category:"CASH_FLOW",unit_kind:"MONEY",unit:"USD",definition_version:"annual-core-reported-v1",period_class:"FY",coverage:{}}]}if(token===S.contextToken)S.catalog=catalog}
function renderCompanyOptions(){const q=$("#company-query").value.trim().toLowerCase();$("#company-select").innerHTML=S.companies.filter(x=>!q||`${(x.tickers||[]).join(" ")} ${x.name||""}`.toLowerCase().includes(q)).map(x=>`<option value="${x.cik}" ${S.companySelection.has(x.cik)?"selected":""}>${esc((x.tickers||[])[0]||"")} · ${esc(x.name||"")}</option>`).join("")}
function syncCompanySelection(){[...$("#company-select").options].forEach(x=>x.selected?S.companySelection.add(x.value):S.companySelection.delete(x.value))}
async function loadCompanies(id,token){const r=await api(`/api/metadata?dataset_id=${encodeURIComponent(id)}&prepared=true&limit=500`);if(token!==S.contextToken)return;S.companies=r.rows;renderCompanyOptions();const a=[...new Map(S.companies.filter(x=>x.sic_code).map(x=>[x.sic_code,x.sic_description||"분류명 없음"])).entries()].sort((x,y)=>x[1].localeCompare(y[1]));$("#industry-select").innerHTML=a.map(([c,l])=>`<option value="${c}">${esc(l)}</option>`).join("")}
async function loadInputContext(id){const token=++S.contextToken;await Promise.all([loadCatalog(id,token),loadCompanies(id,token)])}
function mountAdmin(){if(!S.admin)return;const s=document.createElement("section");s.className="history";s.innerHTML='<div class="section-head"><div><span class="step">ADMIN</span><h2>자료 관리 진단</h2><p>수집·분류 담당자용 기업 메타데이터 조회입니다.</p></div></div><div class="compare"><label>기업명·티커·CIK 검색<input id="admin-query" type="search"></label><label>준비 상태<select id="admin-prepared"><option value="">전체</option><option value="true">준비됨</option><option value="false">미준비</option></select></label><button id="admin-search" type="button" class="quiet">조회</button></div><div id="admin-results" class="diff">검색 조건을 입력하거나 전체를 조회하세요.</div>';$("main").append(s);$("#admin-search").onclick=async()=>{try{const q=$("#admin-query").value,p=$("#admin-prepared").value,u=`/api/metadata?dataset_id=${encodeURIComponent($("#dataset").value)}&query=${encodeURIComponent(q)}&offset=0&limit=50${p?`&prepared=${p}`:""}`,r=await api(u);$("#admin-results").innerHTML=r.rows.length?r.rows.map(x=>`<p><b>${esc((x.tickers||[]).join(", ")||x.name)}</b> · ${esc(x.name)} · CIK ${esc(x.cik)} · SIC ${esc(x.sic_code||"UNKNOWN_SIC")} · ${x.financial_prepared?"ACTUAL_PREPARED":"NOT_PREPARED"}</p>`).join(""):"검색 결과가 없습니다."}catch(e){fail(e)}}}
const CORE_SHORT_LABELS={revenue:"매출",revenue_yoy:"매출 성장률",operating_margin:"영업이익률",net_income:"순이익",cfo:"영업현금흐름",standardized_fcf:"표준화 FCF",current_ratio:"유동비율",liabilities_to_assets:"부채/자산"};
function publishedConditionAccess(definition){
  const selected=S.catalog.find(item=>item.metric_id===definition?.metric_id&&item.definition_version===definition?.definition_version);
  if(!selected)return{allowed:false,reason:"이 상세 비교는 조건 카탈로그에 등록되지 않았습니다."};
  if(resultProfileSession.active)return{allowed:false,reason:"실행 결과의 전체 프로필은 조회 전용입니다. 결과로 돌아가 같은 발행물의 조건을 편집해 주세요."};
  if($("#dataset").value!==explorerDataset()?.dataset_id)return{allowed:false,reason:"같은 발행물의 스크리닝 조건을 먼저 선택해 주세요."};
  const dataset=explorerDataset(),scope=S.screenAvailability||S.run;if(!scope||scope.dataset_id!==dataset?.dataset_id||(scope.dataset_publication_id||scope.publication_id)!==(dataset?.publication_id||dataset?.dataset_publication_id)||scope.financial_as_of!==dataset?.financial_as_of)return{allowed:false,reason:"현재 조건의 발행물·재무 기준일을 같은 범위로 확인한 뒤 추가해 주세요."};
  const quarterly=$("#frequency").value==="QUARTERLY";
  if(quarterly!==(explorerBasis.profileBasis!=="ANNUAL"))return{allowed:false,reason:"같은 연간/분기·TTM 조건 빈도를 먼저 선택해 주세요."};
  return{allowed:true,definition:selected};
}
function addPublishedCondition(id){
  const definition=activeExplorerMetrics().find(item=>item.metric_id===id),access=publishedConditionAccess(definition);if(!access.allowed)throw new Error(access.reason);
  if($$(".predicate").some(row=>row.querySelector(".metric").value===id))throw new Error("이미 같은 지표가 조건에 있습니다.");
  const threshold=thresholdToApi("0",access.definition);clearResult();predicateRow({metric_id:id,operator:"GTE",threshold,definition_version:access.definition.definition_version});markDirty();showView("screening",true);toast("공표 지표를 0 이상 조건으로 추가했습니다. 기준값을 수정해 주세요.");
}
function conditionActionMarkup(definition){const access=publishedConditionAccess(definition);return`<button type="button" class="quiet published-condition-action" data-add-published-condition="${esc(definition.metric_id)}" ${access.allowed?"":"disabled"} title="${esc(access.allowed?"현재 조건에 0 이상으로 추가한 뒤 기준값을 수정할 수 있습니다.":access.reason)}">조건에 추가</button>${access.allowed?"":`<small>${esc(access.reason)}</small>`}`}
function syncResultProfileContext(){
  if(!resultProfileSession.active)return;const run=resultProfileSession.run;if(!run)return;
  const policy=run.period_policy||{},period=latestScreenPolicy(policy)?"회사별 최신":policy.mode==="FIXED_FISCAL_YEAR"?`FY${policy.fiscal_year}`:policy.mode==="FIXED_CALENDAR_QUARTER_END"?`${policy.calendar_year}Q${policy.calendar_quarter}`:"실행에 기록된 기간";
  $("#analysis-context").textContent=`${run.run_id?"저장 결과":"시험 실행"}의 전체 프로필 · ${period} · 발행물 고정`;
  $("#analysis-context").title=`${run.dataset_id} · ${run.dataset_publication_id} · 재무 기준일 ${run.financial_as_of}`;$("#analysis-company-scope").textContent=`실행 대상 ${run.rows.length}개 · 원래 실행 순서`;
}

// Shared display vocabulary. Definitions and observations remain governed upstream.
function metricPresentationUnit(definition){return definition?.unit_kind==="MONEY"?(definition.unit?`백만 ${definition.unit}`:"금액 단위 미정"):definition?.unit_kind==="RATIO"?"배":["pp","PERCENTAGE_POINT"].includes(definition?.unit)?"%p":definition?.unit_kind==="PERCENT"?"%":definition?.unit||"단위 미정"}
function metricComparisonLabel(definition){
  const id=definition?.metric_id;
  if(definition?.comparison_of)return definition.comparison_kind==="PERCENTAGE_POINT"?"전년 비율 변화 (%p)":definition.period_relationship==="PRIOR_FISCAL_YEAR"?"전년 대비 (YoY)":"전년 동기 대비 (YoY)";
  if(id==="quarter_revenue_qoq")return "전분기 대비 (QoQ)";
  if(id==="revenue_yoy")return "전년 대비 (YoY)";
  if(id==="quarter_revenue_yoy")return "전년 동기 대비 (YoY)";
  return "";
}
function metricPresentation(definition,{basis="",adjunct=false,catalog=[]}={}){
  const registered=!adjunct&&catalog.some(item=>item.metric_id===definition?.metric_id&&item.definition_version===definition?.definition_version);
  const period=definition?.observation_basis||definition?.period_class;
  const periodLabel=period==="TTM"?"최근 12개월 (TTM)":period==="INSTANT"?"기말 시점":period==="FY"?"연간":period==="QTD_3M"||period==="QUARTER"?"분기":basis==="TTM"?"TTM":basis==="QUARTERLY"?"분기":"연간";
  const kinds=definition?.source_kind?[definition.source_kind]:definition?.allowed_source_kinds||[],source=definition?.source_label||(kinds.length===1&&kinds[0]==="REPORTED"?"회사 보고":kinds.length===1&&kinds[0]==="DERIVED_METRIC"?"계산 지표":"공표 지표");
  return{name:definition?.label||definition?.metric_id||"지표",unit:metricPresentationUnit(definition),period:periodLabel,comparison:metricComparisonLabel(definition),source,
    condition:registered,capability:registered?"조회·조건 사용 가능":"상세 비교 전용 · 조건 미지원"};
}
function metricPresentationCaption(definition,options={}){const item=metricPresentation(definition,options);return[item.name,item.unit,item.period,item.comparison,item.source].filter(Boolean).join(" · ")}
function preparedChangeCaption(definition){
  if(definition?.unit_kind==="RATIO")return "배수 수준 · 변화 지표 미등록";
  const period=definition?.observation_basis||definition?.period_class,annual=!definition?.observation_basis&&(period==="FY"||period==="INSTANT"),instant=period==="INSTANT",ttm=period==="TTM";
  if(definition?.unit_kind==="MONEY"&&instant)return "기말잔액 YoY · 전년 같은 기준시점 (%)";
  if(definition?.unit_kind==="PERCENT"){const name=definition.metric_id==="quarter_revenue_qoq"?"QoQ":definition.metric_id==="quarter_revenue_yoy"||definition.metric_id==="revenue_yoy"?"매출 YoY":definition.label;return `${name}의 ${instant?"전년 같은 기준시점":annual?"전년":"전년 동기"} 변화 (%p)`}
  return ttm?"TTM 전년 동기 대비 (%)":annual?"전년 대비 (%)":"전년 동기 대비 (%)";
}
function orderedDisplayJson(value){return JSON.stringify(value,(_,item)=>item&&typeof item==="object"&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item)}
function samePublishedPeriod(left,right){return orderedDisplayJson(left??null)===orderedDisplayJson(right??null)}

const annualColumnSelection={order:null,scope:null,status:"",error:false,cache:new Map()};
function annualColumnScope(){const dataset=explorerDataset();return JSON.stringify([dataset?.dataset_id,dataset?.publication_id||dataset?.dataset_publication_id,(S.explorerCatalog?.metrics||[]).map(metric=>[metric.metric_id,metric.definition_version])])}
function annualMetricIds(){
  const definitions=S.explorerCatalog?.metrics||[],scope=annualColumnScope();
  if(annualColumnSelection.scope!==scope){annualColumnSelection.scope=scope;annualColumnSelection.order=null}
  const preset=$("#explorer-preset").value;
  if(preset==="ALL")return definitions.map(metric=>metric.metric_id);
  if(preset==="CUSTOM")return(annualColumnSelection.order||EXPLORER_PRESETS.CORE).filter(id=>definitions.some(metric=>metric.metric_id===id));
  return(EXPLORER_PRESETS[preset]||EXPLORER_PRESETS.CORE).filter(id=>!definitions.length||definitions.some(metric=>metric.metric_id===id));
}
function renderAnnualColumnPicker(){
  if(!$(".explorer-display-fields")?.append)return;
  if(!$("#explorer-column-picker")){
    const picker=document.createElement("details");picker.id="explorer-column-picker";picker.className="workflow-disclosure";
    picker.innerHTML='<summary>표시 지표 선택</summary><div class="column-picker-controls"><label>지표 검색<input id="explorer-column-query" type="search"></label><label>분류<select id="explorer-column-group"><option value="">전체 분류</option></select></label></div><div id="explorer-column-options"></div>';
    $(".explorer-display-fields").append(picker);
    const status=document.createElement("p");status.id="explorer-extra-status";status.setAttribute("role","status");$(".explorer-matrix").before(status);
    $("#explorer-column-query").oninput=renderAnnualColumnPicker;$("#explorer-column-group").onchange=renderAnnualColumnPicker;
  }
  const picker=$("#explorer-column-picker");picker.hidden=explorerBasis.basis!=="ANNUAL";if(picker.hidden)return;
  const definitions=S.explorerCatalog?.metrics||[],ids=annualMetricIds(),query=$("#explorer-column-query").value.trim().toLocaleLowerCase(),group=$("#explorer-column-group").value;
  if(![...$("#explorer-preset").options].some(option=>option.value==="CUSTOM")){const option=document.createElement("option");option.value="CUSTOM";option.textContent="직접 선택";$("#explorer-preset").append(option)}
  $("#explorer-column-group").innerHTML='<option value="">전체 분류</option>'+[...new Set(definitions.map(metric=>metric.category))].map(category=>`<option value="${esc(category)}">${esc(categoryLabel(category))}</option>`).join("");$("#explorer-column-group").value=group;
  $("#explorer-column-options").innerHTML=definitions.filter(metric=>(!group||metric.category===group)&&(!query||`${metric.label} ${metric.metric_id}`.toLocaleLowerCase().includes(query))).map(metric=>`<label title="${esc(metricPresentationCaption(metric))}"><input type="checkbox" data-explorer-column="${esc(metric.metric_id)}" ${ids.includes(metric.metric_id)?"checked":""}>${esc(metric.label)} <small>${esc(unitLabel(metric))}</small></label>`).join("")||'<p class="empty">검색 결과가 없습니다.</p>';
  picker.querySelector("summary").textContent=`표시 지표 ${ids.length}/${definitions.length}개`;
  picker.querySelectorAll('[data-explorer-column]').forEach(input=>input.onchange=()=>{
    const selected=annualMetricIds().slice(),id=input.dataset.explorerColumn,index=selected.indexOf(id);if(input.checked&&index<0)selected.push(id);else if(!input.checked&&index>=0)selected.splice(index,1);
    annualColumnSelection.order=selected;$("#explorer-preset").value="CUSTOM";updateExplorerSort();loadExplorer().catch(error=>explorerNotice(error.message,true));
  });
}
function annualExtraCacheKey(response,cik,id){const definition=annualExplorerMetric(id);return JSON.stringify([response.dataset_id,response.dataset_publication_id,response.financial_as_of,response.period_scope==="LATEST_COMPANY"?"LATEST":response.selected_fiscal_year,cik,id,definition.definition_version])}
function annualExtraBatches(rows){const groups=[];for(let index=0;index<rows.length;index+=4)groups.push(rows.slice(index,index+4));if(groups.length>1&&groups.at(-1).length===1)groups.at(-1).unshift(groups.at(-2).pop());return groups}
async function readAnnualExtraColumns(response,ids,current){
  const extra=ids.filter(id=>!EXPLORER_PRESETS.CORE.includes(id));if(!extra.length||!response.rows.length)return;
  const missing=response.rows.filter(row=>extra.some(id=>!annualColumnSelection.cache.has(annualExtraCacheKey(response,row.company.cik,id))));
  const batches=annualExtraBatches(missing),params={dataset_id:response.dataset_id,dataset_publication_id:response.dataset_publication_id,...(response.period_scope==="LATEST_COMPANY"?{latest:"true"}:{fiscal_year:String(response.selected_fiscal_year)})};
  let next=0;
  async function worker(){while(next<batches.length){const batch=batches[next++],ciks=batch.map(row=>row.company.cik);let cells=[];
    if(ciks.length===1){const payload=await api(`/api/company-profile?${new URLSearchParams({...params,cik:ciks[0]})}`);validateAnnualExtraScope(response,payload,true);if(response.period_scope==="LATEST_COMPANY"&&!samePublishedPeriod(batch[0].resolved_period,payload.resolved_period))throw new Error("추가 지표의 최신 실제 기간이 탐색 행과 다릅니다.");if(payload.company?.cik!==ciks[0])throw new Error("추가 지표의 기업 범위가 다릅니다.");cells=(payload.groups||[]).flatMap(group=>group.metrics||[]).filter(item=>extra.includes(item.definition?.metric_id)).map(item=>({cik:ciks[0],metric:item.definition,observation:item.observation}));}
    else{const payload=await api(`/api/company-comparison?${new URLSearchParams({...params,ciks:ciks.join(","),metric_ids:extra.join(",")})}`);validateAnnualExtraScope(response,payload);if(response.period_scope==="LATEST_COMPANY"&&batch.some(row=>!samePublishedPeriod(row.resolved_period,payload.actual_periods?.[row.company.cik])))throw new Error("추가 지표의 최신 실제 기간이 탐색 행과 다릅니다.");if(payload.companies?.length!==ciks.length||payload.companies.some(company=>!ciks.includes(company.cik)))throw new Error("추가 지표의 기업 범위가 다릅니다.");cells=(payload.rows||[]).flatMap(row=>ciks.map(cik=>({cik,metric:row.metric,observation:row.values?.[cik]})));}
    if(!current())return;
    for(const cik of ciks)for(const id of extra){const matched=cells.filter(cell=>cell.cik===cik&&cell.metric?.metric_id===id),definition=annualExplorerMetric(id);if(matched.length!==1||["definition_version","unit_kind","unit"].some(key=>matched[0].metric[key]!==definition[key])||!matched[0].observation)throw new Error("추가 지표의 공표 정의 또는 관측이 다릅니다.");const cell=matched[0].observation;if(cell.value!=null){if(typeof cell.value!=="string")throw new Error("정확한 공표 숫자 문자열이 아닙니다.");shiftDecimal(cell.value,0)}annualColumnSelection.cache.set(annualExtraCacheKey(response,cik,id),cell)}
  }}
  await Promise.all(Array.from({length:Math.min(3,batches.length)},worker));if(!current())return;
  for(const row of response.rows)for(const id of extra){const key=annualExtraCacheKey(response,row.company.cik,id);if(annualColumnSelection.cache.has(key))row.metrics[id]=annualColumnSelection.cache.get(key)}
  while(annualColumnSelection.cache.size>12000)annualColumnSelection.cache.delete(annualColumnSelection.cache.keys().next().value);
}
function validateAnnualExtraScope(expected,payload,profile=false){if(["dataset_id","dataset_publication_id","financial_as_of"].some(key=>payload[key]!==expected[key])||(expected.period_scope==="LATEST_COMPANY"?profile?(!payload.resolved_period||payload.selected_fiscal_year!==payload.resolved_period.fiscal_year):payload.period_scope!=="LATEST_COMPANY":payload.selected_fiscal_year!==expected.selected_fiscal_year))throw new Error("추가 지표 발행물·기준일·기간이 선택 범위와 다릅니다.")}

const EXPLORER_PRESETS={CORE:["revenue","revenue_yoy","operating_margin","net_income","cfo","standardized_fcf","current_ratio","liabilities_to_assets"],GROWTH_PROFIT:["revenue","revenue_yoy","operating_margin","net_income"],CASH_STABILITY:["cfo","standardized_fcf","current_ratio","liabilities_to_assets"]};
function showView(view,focus=false){if(resultProfileSession.active&&view!=="explorer")closeResultProfile(false);if(S.view==="explorer"&&view!=="explorer"){closeProfile(false);if(desktopExplorer.mounted)closeExplorerComparison(false)}S.view=view;$$('[data-task-view]').forEach(x=>x.hidden=x.dataset.taskView!==view);$$('[data-view]').forEach(x=>{const active=x.dataset.view===view;x.classList.toggle("active",active);if(active)x.setAttribute("aria-current","page");else x.removeAttribute("aria-current")});if(focus){const target=$(`#${({explorer:"explorer-title",library:"library-title",screening:"criteria-title",history:"history-title"})[view]}`);target?.setAttribute("tabindex","-1");target?.focus()}}
function annualExplorerMetric(id){const m=S.explorerCatalog?.metrics.find(x=>x.metric_id===id);if(!m)throw new Error(`탐색 지표 정의를 찾을 수 없습니다: ${id}`);return m}
function inclusiveEnd(value){if(!/^\d{4}-\d{2}-\d{2}$/.test(value||""))return value||"—";const d=new Date(`${value}T00:00:00Z`);d.setUTCDate(d.getUTCDate()-1);return d.toISOString().slice(0,10)}
function companyPeriodCaption(period){
  if(!period)return "준비된 기간 없음";
  if(period.bucket_status==="PERIOD_CONFLICT")return "실제 기간 확인 필요";
  if(period.bucket_status==="LATEST_SOURCE_PERIOD_NOT_PUBLISHED")return "최신 분기 조회 자료 미준비";
  const actual=period.period_end?actualPeriod(period):"실제 기간 미확인";
  const fiscal=period.fiscal_year?`FY${period.fiscal_year}${period.fiscal_quarter?" "+period.fiscal_quarter:""}`:"";
  const filed=period.filed_date?[period.filed_date]:period.source_filed_dates||[];
  return [fiscal,actual,filed.length?`공시일 ${filed.join(", ")}`:""].filter(Boolean).join(" · ");
}
function explorerPeriod(row){const p=row.actual_period;if(!p)return"선택 연도 자료 없음";const end=inclusiveEnd(p.context_end_date||p.period_end);return p.period_start?`${p.period_start} ~ ${end}`:`기준일 ${end}`}
function explorerValue(o,m){if(!o||o.value===null||o.value===undefined){const reason=(o?.reason_labels||[])[0]||"선택 연도 자료 없음";return`<span class="missing" title="${esc(reason)}" aria-label="자료 없음: ${esc(reason)}">—</span>`}return numberMarkup(o.value,m)}
function annualUpdateExplorerSort(){const current=$("#explorer-sort").value,ids=annualMetricIds();$("#explorer-sort").innerHTML='<option value="company">기업명</option>'+ids.map(id=>`<option value="${id}">${esc(explorerMetric(id).label)}</option>`).join("");if([...$("#explorer-sort").options].some(x=>x.value===current))$("#explorer-sort").value=current}
function renderAnnualExplorer(){const r=S.explorer,ids=annualMetricIds();if(!r)return;renderAnnualColumnPicker();registerExplorerCompanies(r.rows.map(row=>row.company));updateExplorerSort();$("#explorer-count").textContent=`${r.rows.length}개 기업 · ${r.period_scope==="LATEST_COMPANY"?"회사별 최신":`FY${r.selected_fiscal_year}`}`;$("#explorer-year-note").textContent=r.period_scope==="LATEST_COMPANY"?"회사별로 다른 실제 재무기간을 표시합니다.":`선택 연도 자료 ${r.selected_year_company_count}/${r.company_count} · 없는 기업도 목록에 유지합니다.`;renderExplorerHeaders(ids,"재무기간",true);$("#explorer-body").innerHTML=r.rows.length?r.rows.map((row,index)=>{const c=row.company;return`<tr><td><input type="checkbox" data-explorer-select="${index}" data-explorer-cik="${esc(c.cik)}" aria-label="${esc(c.ticker)} 비교 선택" ${S.explorerSelected.has(c.cik)?"checked":""}></td><td><button class="company" data-explorer-open="${index}" data-profile-cik="${esc(c.cik)}" aria-controls="company-profile"><strong>${esc(c.name||c.ticker)}</strong><span class="company-meta" title="${esc(c.ticker)} · ${esc(c.industry||"업종 정보 없음")}"><small>${esc(c.ticker)}</small><small class="industry">${esc(c.industry||"업종 정보 없음")}</small></span></button></td><td class="actual-period">${r.period_scope==="LATEST_COMPANY"?companyFinancialPeriodDisplay(row.resolved_period):compactFinancialCaption(explorerPeriod(row))}</td>${ids.map(id=>`<td>${explorerValue(row.metrics[id],explorerMetric(id))}</td>`).join("")}</tr>`}).join(""):`<tr><td colspan="${3+ids.length}" class="empty">검색 결과가 없습니다.</td></tr>`;$$('[data-explorer-select]').forEach(x=>x.onchange=()=>{const c=r.rows[Number(x.dataset.explorerSelect)].company;transitionExplorerSelection("toggle",c.cik,x.checked,c,x)});$$('[data-explorer-open]').forEach(x=>x.onclick=()=>openProfile(r.rows[Number(x.dataset.explorerOpen)].company.cik,x).catch(fail));updateCompareButton()}
function updateCompareButton(){const n=S.explorerSelected.size,b=$("#compare-selected");b.disabled=n<2||n>4||explorerBasis.readyKey!==explorerContextKey();b.textContent=n?`선택 기업 비교 (${n})`:"선택 기업 비교";syncExplorerSelectionUI();syncProfileTrigger()}

async function loadExplorerCatalog(d){const key=`${d.dataset_id}:${S.explorerYear}`;if(S.explorerCatalogKey===key&&S.explorerCatalog)return S.explorerCatalog;const token=++S.explorerCatalogToken,r=await api(`/api/metric-library?dataset_id=${encodeURIComponent(d.dataset_id)}&fiscal_year=${S.explorerYear}`);if(token!==S.explorerCatalogToken)return null;const current=S.explorerDataset||S.defaultDataset;if(current?.dataset_id!==d.dataset_id||Number(r.selected_fiscal_year)!==Number(S.explorerYear))return null;if(d.definition_count&&r.metrics.length!==d.definition_count)throw new Error("전체 탐색 지표 정의를 불러오지 못했습니다.");S.explorerCatalog=r;S.explorerCatalogKey=key;return r}

async function loadAnnualExplorer(year=null){const d=S.explorerDataset||S.defaultDataset;if(!d)return;const q=$("#explorer-query").value.trim(),sort=$("#explorer-sort").value||"company",direction=$("#explorer-direction").value||"asc",params=new URLSearchParams({dataset_id:d.dataset_id,dataset_publication_id:d.publication_id||d.dataset_publication_id,sort:EXPLORER_PRESETS.CORE.includes(sort)||sort==="company"?sort:"company",direction});if(explorerBasis.latestAnnual)params.set("latest","true");else if(year||S.explorerYear)params.set("fiscal_year",String(year||S.explorerYear));if(q)params.set("query",q);const token=++S.explorerToken,r=await api(`/api/explorer?${params}`);if(token!==S.explorerToken)return;S.explorer=r;S.explorerYear=r.selected_fiscal_year??r.default_fiscal_year;await loadExplorerCatalog(d);if(token!==S.explorerToken)return;$("#explorer-asof").textContent=r.financial_as_of;const y=$("#explorer-year");if(batchView.enabled||!y.options.length)y.innerHTML=(batchView.snapshot?'<option value="LATEST">회사별 최신</option>':"")+r.fiscal_years.map(x=>`<option value="${x.fiscal_year}">FY${x.fiscal_year} · ${x.companies_prepared}/${r.company_count}</option>`).join("");y.value=explorerBasis.latestAnnual?"LATEST":String(r.selected_fiscal_year);const current=()=>token===S.explorerToken&&explorerBasis.basis==="ANNUAL"&&explorerDataset().dataset_id===d.dataset_id;annualColumnSelection.status="";annualColumnSelection.error=false;try{await readAnnualExtraColumns(r,annualMetricIds(),current);if(!current())return;if(!EXPLORER_PRESETS.CORE.includes(sort)&&sort!=="company")r.rows=filterSortExplorerRows(r.rows,"",sort,direction)}catch(error){if(!current())return;annualColumnSelection.status=`추가 지표 조회 실패 · 추가 지표 정렬 미적용: ${error.message}`;annualColumnSelection.error=true}renderExplorer();const status=$("#explorer-extra-status");if(status){status.textContent=annualColumnSelection.status;status.hidden=!annualColumnSelection.status}}
const libraryWorkbench={scopes:new Map(),readyKey:null};
function libraryScopeKey(){const d=S.explorerDataset||S.defaultDataset;return JSON.stringify([d?.dataset_id,d?.dataset_publication_id??d?.publication_id,S.explorerYear])}
function libraryScope(){const key=libraryScopeKey();if(!libraryWorkbench.scopes.has(key))libraryWorkbench.scopes.set(key,{selected:null,drafts:new Map()});return libraryWorkbench.scopes.get(key)}
function guideDraftKey(m){return JSON.stringify([m.metric_id,m.definition_version])}
function renderLibrary(){
  const r=S.library;if(!r)return;if(libraryWorkbench.readyKey!==libraryScopeKey()){if($("#library-detail"))$("#library-detail").hidden=true;return}const state=libraryScope();
  $("#library-title").textContent=`${S.explorerCatalog?.metrics?.length??r.metrics.length}개 재무지표 안내`;
  $("#library-year-label").textContent=`연간 FY${r.selected_fiscal_year} · 자료 있음 ${r.selected_year_company_count}/${r.company_count}개 기업 · 검색 ${r.metrics.length}개 지표`;
  const list=$("#library-groups"),scrollTop=list.scrollTop;
  if(!$("#library-detail")){const shell=document.createElement("div");shell.className="library-workbench";list.before(shell);shell.append(list);const detail=document.createElement("article");detail.id="library-detail";shell.append(detail);if(!$("#library-status")){const status=document.createElement("p");status.id="library-status";status.setAttribute("role","status");shell.before(status)}}
  if(!state.selected&&r.metrics.length)state.selected=r.metrics[0].metric_id;
  list.innerHTML=r.categories.map(c=>{const metrics=r.metrics.filter(m=>m.category===c.code);return metrics.length?`<section class="library-category"><h3>${esc(c.label)} <small>${metrics.length}개</small></h3>${metrics.map(m=>`<button type="button" class="quiet library-item" data-library-select="${esc(m.metric_id)}" aria-pressed="${m.metric_id===state.selected}"><strong>${esc(m.label)}</strong><small>${esc(unitLabel(m))} · ${m.selected_year_coverage.companies_available}/${m.selected_year_coverage.companies_total}개 기업</small></button>`).join("")}</section>`:""}).join("")||'<p class="empty">검색 조건에 맞는 지표가 없습니다.</p>';
  list.scrollTop=scrollTop;
  const m=r.metrics.find(x=>x.metric_id===state.selected),detail=$("#library-detail");detail.hidden=!m;
  detail.innerHTML=m?`<span class="metric-kind">${esc(m.source_label)} · ${esc(m.period_label)} · ${esc(unitLabel(m))}</span><h3>${esc(m.label)}</h3><p class="metric-capability">${esc(metricPresentation(m,{catalog:r.metrics}).capability)}</p><h4>의미</h4><p>${esc(m.meaning)}</p><h4>활용</h4><p>${esc(m.use)}</p><p class="coverage">FY${r.selected_fiscal_year} · ${m.selected_year_coverage.companies_available}/${m.selected_year_coverage.companies_total}개 기업에서 자료 제공</p><div class="add-row"><label>조건값 (${esc(unitLabel(m))})<input data-guide-threshold="${esc(m.metric_id)}" inputmode="decimal" value="${esc(state.drafts.get(guideDraftKey(m))??"0")}"></label><button type="button" data-guide-add="${esc(m.metric_id)}">조건에 추가</button></div>`:"";
  list.querySelectorAll('[data-library-select]').forEach(button=>button.onclick=()=>{state.selected=button.dataset.librarySelect;renderLibrary();$('[data-library-select][aria-pressed="true"]')?.focus({preventScroll:true})});
  if(m){const input=detail.querySelector('input');input.oninput=()=>state.drafts.set(guideDraftKey(m),input.value);detail.querySelector('[data-guide-add]').onclick=()=>withBusy(()=>addGuideMetric(m.metric_id)).catch(error=>{$("#library-status").textContent=error.message})}
}

async function loadLibrary(){const d=S.explorerDataset||S.defaultDataset;if(!d)return;if(!$("#library-status")){const status=document.createElement("p");status.id="library-status";status.setAttribute("role","status");$("#library-groups").before(status)}const params=new URLSearchParams({dataset_id:d.dataset_id,fiscal_year:String(S.explorerYear)}),q=$("#library-query").value.trim(),c=$("#library-category").value;if(q)params.set("query",q);if(c)params.set("category",c);const scope=libraryScopeKey(),token=++S.libraryToken;if(libraryWorkbench.readyKey!==scope){if($("#library-detail"))$("#library-detail").hidden=true;$("#library-groups").innerHTML='<p class="empty">선택한 자료·회계연도의 지표 안내를 불러오는 중입니다.</p>'}try{await loadExplorerCatalog(d);if(token!==S.libraryToken)return;const r=await api(`/api/metric-library?${params}`);if(token!==S.libraryToken||scope!==libraryScopeKey())return;if(Number(r.selected_fiscal_year)!==Number(S.explorerYear))throw new Error("지표 안내의 회계연도가 선택 범위와 다릅니다.");S.library=r;libraryWorkbench.readyKey=scope;renderLibrary();$("#library-status").textContent="";updateExplorerSort()}catch(error){if(token!==S.libraryToken||scope!==libraryScopeKey())return;if(libraryWorkbench.readyKey!==scope)$("#library-groups").innerHTML='<p class="empty">선택한 자료·회계연도의 지표 안내를 불러오지 못했습니다.</p>';const status=$("#library-status");if(status)status.textContent=`지표 안내를 불러오지 못했습니다. ${error.message}`;else throw error}}

function guideCompatibility(content){const definitions=new Map((S.explorerCatalog?.metrics||[]).map(x=>[x.metric_id,x.definition_version]));return content.predicates.filter(x=>definitions.get(x.metric_id)!==x.definition_version)}

async function addGuideMetric(id){if(libraryWorkbench.readyKey!==libraryScopeKey())throw new Error("선택한 자료와 회계연도의 지표 안내를 불러온 뒤 추가해 주세요.");if($("#frequency").value==="QUARTERLY")throw new Error("연간 지표 안내입니다. 연간 조건으로 전환한 뒤 추가해 주세요.");const m=(S.library?.metrics||[]).find(x=>x.metric_id===id)||explorerMetric(id),input=$(`[data-guide-threshold="${id}"]`),threshold=input?.value.trim();if(!threshold)throw new Error("조건값을 입력해 주세요.");const raw=thresholdToApi(threshold,m),d=S.explorerDataset||S.defaultDataset,pristine=!S.revision&&!S.dirty&&!$("#screen-name").value&&$$(".predicate").length===1,duplicate=$$(".predicate").some(r=>r.querySelector(".metric").value===id);if(duplicate&&!pristine)throw new Error("이미 같은 지표가 조건에 있습니다.");const incompatible=$("#dataset").value!==d.dataset_id?guideCompatibility(revisionContent()):[];if(incompatible.length)throw new Error(`최신 자료와 정의가 다른 조건이 있습니다: ${incompatible.map(x=>x.metric_id).join(", ")}`);clearResult();let copied=false;if($("#dataset").value!==d.dataset_id){const content=revisionContent();const name=$("#screen-name").value;$("#dataset").value=d.dataset_id;$("#asof").textContent=d.financial_as_of;await loadInputContext(d.dataset_id);loadScreenRecord({name,content,revision_number:"복사본"});S.revision=null;S.dirty=true;$("#saved-screen").value="";$("#screen-name").readOnly=false;$("#screen-context").textContent=`${name||"새 조건"} · 저장 전 복사본`;$("#save-state").textContent="저장 전 · 저장 필요";setCriteriaCompact(false);copied=true}if(pristine&&!copied){$("#predicates").innerHTML="";$("#period-mode").value="FIXED_FISCAL_YEAR";togglePeriod();$("#fiscal-year").value=String(S.explorerYear)}predicateRow({metric_id:id,operator:"GTE",threshold:raw,definition_version:m.definition_version});markDirty();showView("screening",true);toast("지표를 현재 draft에 추가했습니다. 저장 전 상태입니다.")}
function profileObservationCell(o,m){if(o?.value===null||o?.value===undefined){const reason=(o?.reason_labels||[])[0]||"자료 없음";return`<span class="missing" title="${esc(reason)}" aria-label="자료 없음: ${esc(reason)}">—</span>`}const period=o.period_start?`${o.period_start} ~ ${inclusiveEnd(o.period_end)}`:`기준일 ${inclusiveEnd(o.period_end)}`,detail=`${m.source_label||""} · ${period}`;return`<strong title="${esc(detail)}">${numberMarkup(o.value,m)}</strong>`}
function renderProfileTrendData(){const p=S.profile,id=$("#profile-metric").value,item=p.groups.flatMap(x=>x.metrics).find(x=>x.definition.metric_id===id),m=item.definition,series=p.series[id]||[];S.profileMetric=id;const available=series.filter(x=>x.value!==null&&x.value!==undefined),values=available.map(x=>Number(x.value)),min=Math.min(...values),max=Math.max(...values),span=max-min||1,points=series.map((x,i)=>x.value===null||x.value===undefined?null:{x:38+i*(284/Math.max(series.length-1,1)),y:102-((Number(x.value)-min)/span)*62}),lines=points.slice(1).map((p2,i)=>p2&&points[i]?`<line class="line" x1="${points[i].x}" y1="${points[i].y}" x2="${p2.x}" y2="${p2.y}"/>`:"").join(""),marks=points.map((p2,i)=>p2?`<g><circle class="point" cx="${p2.x}" cy="${p2.y}" r="4"><title>${profileSeriesLabel(series[i])} ${esc(displayValue(series[i].value,m))}</title></circle>${explorerBasis.profileBasis==="ANNUAL"||i===points.findIndex(Boolean)||i===points.findLastIndex(Boolean)?`<text class="value-label" x="${p2.x}" y="${Math.max(p2.y-9,28)}">${esc(displayValue(series[i].value,m))}</text>`:""}</g>`:"").join(""),years=series.map((x,i)=>explorerBasis.profileBasis==="ANNUAL"?`<text class="year-label ${points[i]?"":"missing-year"}" x="${38+i*(284/Math.max(series.length-1,1))}" y="142">${profileSeriesLabel(x)}${points[i]?"":" · 없음"}</text>`:interimAxisCaption(x,38+i*(284/Math.max(series.length-1,1)),!points[i])).join("");$("#profile-chart").innerHTML=available.length?`<svg viewBox="0 0 360 158" role="img" aria-label="${esc(m.label)} ${explorerBasis.profileBasis==="ANNUAL"?"4개 회계연도":"8개 종료 분기"} 흐름. 단위 ${esc(unitLabel(m))}. 누락 연도는 연결하지 않습니다."><text class="chart-label" x="12" y="18">${esc(m.label)} · ${esc(unitLabel(m))}</text><line class="axis" x1="24" y1="116" x2="340" y2="116"/>${lines}${marks}${years}</svg>`:'<p class="empty">표시할 값이 없습니다.</p>';$("#profile-series").innerHTML=`<table class="series-table"><thead><tr><th>${explorerBasis.profileBasis==="ANNUAL"?"회계연도":"종료 분기 · 회사 회계표시"}</th><th>재무기간</th><th>${esc(m.label)} (${esc(unitLabel(m))})</th></tr></thead><tbody>${series.map(x=>`<tr><td>${profileSeriesLabel(x)}${explorerBasis.profileBasis!=="ANNUAL"?`<small>${esc(fiscalLabel(x))}</small>`:""}</td><td>${compactFinancialCaption(x.period_start?`${x.period_start} ~ ${inclusiveEnd(x.period_end)}`:`기준일 ${inclusiveEnd(x.period_end)}`)}</td><td>${x.value===null||x.value===undefined?`<span class="missing" title="${esc((x.reason_labels||[])[0]||"자료 없음")}">—</span>`:numberMarkup(x.value,m)}</td></tr>`).join("")}</tbody></table>`}
function renderCompanyDescription(d){const box=$("#profile-description"),copy=box.querySelector(".description-copy"),meta=box.querySelector(".description-meta");box.querySelectorAll("a").forEach(x=>x.remove());if(!d||d.status!=="AVAILABLE"||!d.text){box.hidden=true;copy.textContent="";meta.textContent="";return}box.hidden=false;copy.textContent=d.text;const checked=(d.checked_at||"").slice(0,10),fixture=d.content_fixture_kind==="SYNTHETIC_DESCRIPTION_FIXTURE"?" · 합성 소개 예시":"";meta.textContent=`현재 회사 정보 · ${d.provider_name||"출처 확인"}${checked?` · ${checked} 확인`:""}${fixture}`;if(d.profile_url){try{const u=new URL(d.profile_url);if(u.protocol==="https:"){const a=document.createElement("a");a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";a.textContent="원문 출처 열기";meta.append(" · ",a)}}catch(_){}}}
function profileMetricLedger(groups){
  return groups.map((group,index)=>`<section class="profile-group" aria-labelledby="profile-group-${index}">
    <h3 id="profile-group-${index}">${esc(group.label)}</h3>
    <dl class="profile-ledger">${group.metrics.map(({definition,observation})=>{
      const reason=observation?.value==null?(observation?.reason_labels?.[0]||"자료 없음"):"";
      return `<div class="profile-ledger-row"><dt>${esc(definition.label)}${reason?`<small class="profile-ledger-reason">${esc(reason)}</small>`:""}</dt>
        <dd class="profile-ledger-value">${profileObservationCell(observation,definition)}</dd>
        <dd class="profile-ledger-unit">${esc(unitLabel(definition))}</dd></div>`;
    }).join("")}</dl></section>`).join("");
}
function profileFiscalPrefix(profile){
  const year=profile.selected_fiscal_year;
  return year==null||profile.resolved_period?.fiscal_year===year?"":`FY${year} · `;
}
function financialMetricCaption(definition){
  return ["standardized_fcf","quarter_standardized_fcf","ttm_standardized_fcf"].includes(definition.metric_id)?"표준화 FCF":definition.label;
}
function renderProfile(){if($("#profile-summary-disclosure"))$("#profile-summary-disclosure").open=false;resetRevenueBreakdowns();const p=S.profile,definitions=p.groups.flatMap(x=>x.metrics.map(y=>y.definition));$("#profile-title").textContent=`${p.company.name||p.company.ticker} 재무 프로필`;$("#profile-intro").innerHTML=`<p><strong>${esc(p.company.ticker)}</strong> · ${esc(p.company.industry||"업종 정보 없음")}</p><p class="muted">재무 기준일 ${compactFinancialCaption(p.financial_as_of)} · ${esc(profileFiscalPrefix(p))}${p.resolved_period?companyFinancialPeriodDisplay(p.resolved_period):compactFinancialCaption(explorerPeriod({actual_period:p.actual_period}))}</p><p class="muted">금액은 백만 USD, 비율은 %로 표시합니다.</p>`;renderCompanyDescription(p.company_description);$("#profile-summary").innerHTML=p.summary.map(x=>`<div class="profile-card"><span>${esc(x.definition.label)} · ${esc(unitLabel(x.definition))}</span>${profileObservationCell(x.observation,x.definition)}</div>`).join("");$("#profile-metric").innerHTML=definitions.map(x=>`<option value="${x.metric_id}">${esc(x.label)}</option>`).join("");$("#profile-metric").value=definitions.some(x=>x.metric_id===S.profileMetric)?S.profileMetric:"revenue";$("#profile-all-metrics").innerHTML=profileMetricLedger(p.groups);const legacy=$("#profile-single-trend");if(legacy)legacy.open=false;else renderProfileTrend()}

async function openAnnualProfile(cik,button){const token=++explorerBasis.profileToken,key=explorerContextKey();S.lastFocus=button;const d=S.explorerDataset||S.defaultDataset;const profile=await api(`/api/company-profile?dataset_id=${encodeURIComponent(d.dataset_id)}&dataset_publication_id=${encodeURIComponent(d.publication_id||d.dataset_publication_id)}&cik=${encodeURIComponent(cik)}&${explorerBasis.latestAnnual?"latest=true":`fiscal_year=${S.explorerYear}`}`);if(token!==explorerBasis.profileToken||key!==explorerContextKey())return;explorerBasis.profileBasis="ANNUAL";S.profile=profile;S.profileMetric=explorerBasis.profileMetrics.ANNUAL;profileTrendCaption(false);renderProfile();showCompanyProfile()}
const comparisonPicker={mounted:false,query:"",category:"",timer:null,token:0};
function comparisonMetricOptions(){
  const definitions=new Map(activeExplorerMetrics().map(metric=>[metric.metric_id,metric]));
  return [...$("#comparison-metrics").options].map(option=>({id:option.value,label:definitions.get(option.value)?.label||option.textContent,
    category:definitions.get(option.value)?.category||"",selected:option.selected,definition:definitions.get(option.value)}));
}
function filteredComparisonMetrics(options,query,category){
  const text=query.trim().toLocaleLowerCase();
  return options.filter(option=>(!category||option.category===category)&&(!text||[option.label,option.id].some(value=>value.toLocaleLowerCase().includes(text))));
}
function cancelComparisonRefresh(){
  comparisonPicker.token++;
  if(comparisonPicker.timer!==null){clearTimeout(comparisonPicker.timer);comparisonPicker.timer=null}
}
function queueComparisonRefresh(){
  invalidateComparisonMulti();
  if(!comparisonPicker.mounted)return;
  cancelComparisonRefresh();explorerBasis.comparisonToken++;
  if($("#comparison-panel").hidden)return;
  const options=comparisonMetricOptions(),count=options.filter(option=>option.selected).length;
  if(S.explorerSelected.size<2||S.explorerSelected.size>4||!count){
    $("#comparison-result").textContent=!count?"비교할 지표를 하나 이상 선택해 주세요.":"기업을 2~4개 선택해 주세요.";return;
  }
  const token=comparisonPicker.token,key=explorerContextKey();
  $("#comparison-result").textContent="선택한 지표와 기업으로 비교를 갱신합니다…";
  comparisonPicker.timer=setTimeout(async()=>{
    comparisonPicker.timer=null;
    const current=()=>token===comparisonPicker.token&&key===explorerContextKey()&&!$("#comparison-panel").hidden&&S.view==="explorer";
    if(!current())return;
    try{await renderComparison();if(current())loadComparisonMulti()}catch(error){if(current())$("#comparison-result").innerHTML=`<p class="message error">${esc(error.message)}</p>`}
  },100);
}
function setComparisonMetric(id,selected){
  const option=[...$("#comparison-metrics").options].find(item=>item.value===id);if(!option)return;
  option.selected=selected;renderComparisonMetricPicker();queueComparisonRefresh();
}
function renderComparisonMetricPicker(){
  if(!comparisonPicker.mounted)return;
  const options=comparisonMetricOptions(),selected=options.filter(option=>option.selected),categories=[...new Set(options.map(option=>option.category).filter(Boolean))];
  const category=$("#comparison-metric-category");
  category.innerHTML='<option value="">전체 분류</option>'+categories.map(value=>`<option value="${esc(value)}">${esc(categoryLabel(value))}</option>`).join("");
  if(!categories.includes(comparisonPicker.category))comparisonPicker.category="";
  category.value=comparisonPicker.category;
  $("#comparison-metric-count").textContent=`${selected.length}개 선택`;
  $("#comparison-metric-choices").innerHTML=filteredComparisonMetrics(options,comparisonPicker.query,comparisonPicker.category).map(option=>`<label><input type="checkbox" data-comparison-metric="${esc(option.id)}" ${option.selected?"checked":""}><span>${esc(option.label)}${option.definition?`<small>${esc(unitLabel(option.definition))}</small>`:""}</span></label>`).join("")||'<p class="muted">검색한 지표가 없습니다. 선택한 지표는 유지됩니다.</p>';
  $("#comparison-metric-chips").innerHTML=selected.map(option=>`<li><button type="button" class="quiet" data-remove-comparison-metric="${esc(option.id)}" title="${esc(option.label)}" aria-label="${esc(option.label)} 비교에서 제외">${esc(option.label)} <span aria-hidden="true">×</span></button></li>`).join("");
  $("#comparison-metric-status").textContent=selected.length?"검색은 선택을 바꾸지 않습니다. 지표를 바꾸면 비교가 자동 갱신됩니다.":"비교할 지표를 하나 이상 선택해 주세요.";
  $("#run-comparison").disabled=!selected.length||S.explorerSelected.size<2||S.explorerSelected.size>4;
  $$('[data-comparison-metric]').forEach(input=>input.onchange=()=>{
    const id=input.dataset.comparisonMetric;setComparisonMetric(id,input.checked);
    $$('[data-comparison-metric]').find(node=>node.dataset.comparisonMetric===id)?.focus({preventScroll:true});
  });
  $$('[data-remove-comparison-metric]').forEach((button,index)=>button.onclick=()=>{
    setComparisonMetric(button.dataset.removeComparisonMetric,false);
    const remaining=$$('[data-remove-comparison-metric]');
    (remaining[Math.min(index,remaining.length-1)]||$("#comparison-metric-picker summary"))?.focus({preventScroll:true});
  });
  $("#comparison-company-chips").innerHTML=[...S.explorerSelected].map(cik=>{const company=explorerSelectedCompany(cik);return `<button type="button" class="quiet" data-comparison-remove-company="${esc(cik)}" aria-label="${esc(company.ticker||company.name)} 비교에서 제외">${esc(company.ticker||company.name)} ×</button>`}).join("");
  $$('[data-comparison-remove-company]').forEach((button,index)=>button.onclick=()=>{
    transitionExplorerSelection("remove",button.dataset.comparisonRemoveCompany,false,null,button);
    if(!$("#comparison-panel").hidden){
      const remaining=$$('[data-comparison-remove-company]');
      (remaining[Math.min(index,remaining.length-1)]||$("#close-comparison"))?.focus({preventScroll:true});
    }
  });
}
function arrangeComparisonAnalysis(){
  if(!comparisonPicker.mounted)return;
  let grid=$("#comparison-analysis-grid");
  if(!grid){grid=document.createElement("div");grid.id="comparison-analysis-grid";$(".comparison-metric-workspace").after(grid)}
  const trend=$("#comparison-trend");if(trend&&trend.parentElement!==grid)grid.append(trend);
  if($("#comparison-result").parentElement!==grid)grid.append($("#comparison-result"));
  const multi=$("#comparison-multi-board");if(multi){grid.classList.add("multi-comparison-ready");grid.prepend(multi);let legacy=$("#comparison-legacy-view");if(!legacy){legacy=document.createElement("details");legacy.id="comparison-legacy-view";legacy.className="workflow-disclosure";legacy.innerHTML="<summary>단일 금액 지표·공통 기준100 보기</summary>";grid.append(legacy)}if(trend&&trend.parentElement!==legacy)legacy.append(trend);grid.append($("#comparison-result"))}
}
function mountComparisonMetricPicker(){
  if(comparisonPicker.mounted)return;comparisonPicker.mounted=true;
  $("#comparison-metrics").closest("label").hidden=true;
  const section=document.createElement("section");section.className="comparison-metric-workspace";
  section.innerHTML='<div id="comparison-company-chips" aria-label="비교 기업"></div><details id="comparison-metric-picker"><summary>비교 지표 선택 <span id="comparison-metric-count"></span></summary><div class="comparison-metric-tools"><label>지표 검색<input type="search" id="comparison-metric-query" placeholder="지표명 검색"></label><label>분류<select id="comparison-metric-category"></select></label><button type="button" class="quiet" id="comparison-select-group">현재 분류 모두 선택</button></div><div id="comparison-metric-choices"></div></details><ul id="comparison-metric-chips" aria-label="선택한 비교 지표"></ul><p id="comparison-metric-status" class="muted" role="status"></p>';
  $("#comparison-panel .section-head").after(section);
  $("#comparison-metric-query").oninput=event=>{comparisonPicker.query=event.target.value;renderComparisonMetricPicker()};
  $("#comparison-metric-category").onchange=event=>{comparisonPicker.category=event.target.value;renderComparisonMetricPicker()};
  $("#comparison-select-group").onclick=()=>{for(const option of $("#comparison-metrics").options){const definition=activeExplorerMetrics().find(metric=>metric.metric_id===option.value);if(!comparisonPicker.category||definition?.category===comparisonPicker.category)option.selected=true}renderComparisonMetricPicker();queueComparisonRefresh()};
  $("#run-comparison").textContent="다시 비교";
  arrangeComparisonAnalysis();
}
const desktopExplorer={mounted:false,mode:"LIST",saved:null,density:"STANDARD",offset:null,companyToken:0};
function desktopExplorerCompanies(){
  const rows=explorerBasis.basis==="ANNUAL"?S.explorer?.rows:explorerBasis.visibleRows;
  return (rows||[]).map(row=>row.company);
}
function fitDesktopExplorerList(){
  if(!desktopExplorer.mounted||desktopExplorer.mode!=="LIST"||S.view!=="explorer")return;
  const matrix=$(".explorer-matrix"),offset=Math.ceil(Math.max(0,matrix.getBoundingClientRect().top)+16);
  if(offset!==desktopExplorer.offset){desktopExplorer.offset=offset;matrix.style.setProperty("--explorer-list-offset",offset+"px")}
}
function syncAnalysisCompany(){
  if(!desktopExplorer.mounted)return;
  const companies=desktopExplorerCompanies(),profile=desktopExplorer.mode==="PROFILE",cik=S.profile?.company.cik;
  const current=companies.findIndex(company=>company.cik===cik),select=$("#analysis-company");
  select.innerHTML=companies.map(company=>`<option value="${esc(company.cik)}">${esc(company.ticker)} · ${esc(company.name||company.ticker)}</option>`).join("");
  if(current<0&&profile&&S.profile?.company)select.insertAdjacentHTML("afterbegin",`<option value="${esc(cik)}">${esc(S.profile.company.ticker)} · ${esc(S.profile.company.name)}</option>`);
  select.value=cik||"";
  $("#analysis-company-controls").hidden=!profile;
  $("#analysis-company-prev").disabled=current<=0;$("#analysis-company-next").disabled=current<0||current>=companies.length-1;
  const period=latestExplorerPeriod()?"회사별 최신":explorerBasis.basis==="ANNUAL"?`FY${S.explorerYear}`:explorerBasis.periods[explorerBasis.basis];
  $("#analysis-context").textContent=`${profile?"기업 재무 분석":"선택 기업 비교"} · ${explorerBasisLabel()} · ${period}${batchView.snapshot?.mode==="PREPARED_SIMULATION"?" · 준비자료 가정":""}`;
  if(batchView.snapshot)$("#analysis-context").setAttribute("title",availabilityCaption(batchView.snapshot));
  $("#analysis-company-scope").textContent=profile?`현재 목록 ${companies.length}개 · 검색·정렬 순서`:`선택 기업 ${S.explorerSelected.size}개 · 재무 기준일 ${S.explorer?.financial_as_of||explorerBasis.snapshot?.financial_as_of||"—"}`;
}
function enterExplorerAnalysis(mode){
  if(!desktopExplorer.mounted)return;
  $("#analysis-status").hidden=true;$("#analysis-status").textContent="";
  if(desktopExplorer.mode==="LIST"){
    const matrix=$(".explorer-matrix");desktopExplorer.saved={top:matrix.scrollTop,left:matrix.scrollLeft,page:window.scrollY,mode,cik:mode==="PROFILE"?S.profile?.company.cik:null};
  }
  desktopExplorer.mode=mode;
  $(".explorer-view").classList.add("analysis-open");$("#explorer-analysis-bar").hidden=false;
  if(mode==="PROFILE")closeExplorerComparison(false);else closeProfile(false);
  syncAnalysisCompany();syncResultProfileContext();$("#explorer-analysis-bar").scrollIntoView({block:"start"});
}
function leaveExplorerAnalysis(mode,restorePage=false){
  if(!desktopExplorer.mounted||desktopExplorer.mode!==mode)return;
  $("#analysis-status").hidden=true;$("#analysis-status").textContent="";
  desktopExplorer.companyToken++;desktopExplorer.mode="LIST";$(".explorer-view").classList.remove("analysis-open");$("#explorer-analysis-bar").hidden=true;
  const matrix=$(".explorer-matrix"),saved=desktopExplorer.saved;
  if(saved){matrix.scrollTop=saved.top;matrix.scrollLeft=saved.left;if(restorePage)window.scrollTo({top:saved.page,left:0,behavior:"instant"})}
  fitDesktopExplorerList();
}
function backToExplorerList(){
  if(resultProfileSession.active){closeResultProfile(true);return}
  const mode=desktopExplorer.mode,cik=desktopExplorer.saved?.mode==="PROFILE"?desktopExplorer.saved.cik:S.profile?.company.cik;
  if(mode==="PROFILE")closeProfile(false);else closeExplorerComparison(false);
  if(desktopExplorer.saved){const matrix=$(".explorer-matrix");matrix.scrollTop=desktopExplorer.saved.top;matrix.scrollLeft=desktopExplorer.saved.left;window.scrollTo({top:desktopExplorer.saved.page,left:0,behavior:"instant"})}
  const target=mode==="PROFILE"?$$('[data-profile-cik]').find(button=>button.dataset.profileCik===cik)||$("#explorer-query"):$("#compare-selected");
  (target&&!target.disabled?target:$("#explorer-query")).focus({preventScroll:true});
}
async function switchAnalysisCompany(cik){
  const token=++desktopExplorer.companyToken,key=explorerContextKey();$("#analysis-status").hidden=true;
  try{await openProfile(cik,$$('[data-profile-cik]').find(button=>button.dataset.profileCik===cik),true)}
  catch(error){if(token===desktopExplorer.companyToken&&key===explorerContextKey()&&desktopExplorer.mode==="PROFILE"){syncAnalysisCompany();$("#analysis-status").textContent=`기업 자료를 불러오지 못했습니다. 현재 표시한 기업을 유지합니다. ${error.message}`;$("#analysis-status").hidden=false}}
}
function mountDesktopExplorer(){
  if(desktopExplorer.mounted)return;desktopExplorer.mounted=true;
  const bar=document.createElement("section");bar.id="explorer-analysis-bar";bar.className="explorer-analysis-bar";bar.hidden=true;
  bar.innerHTML='<button type="button" class="quiet" id="explorer-back-to-list">← 목록으로</button><strong id="analysis-context"></strong><div id="analysis-company-controls"><button type="button" class="quiet" id="analysis-company-prev" aria-label="현재 목록의 이전 기업">이전</button><label class="sr-only" for="analysis-company">분석 기업</label><select id="analysis-company"></select><button type="button" class="quiet" id="analysis-company-next" aria-label="현재 목록의 다음 기업">다음</button></div><small id="analysis-company-scope"></small><p id="analysis-status" role="status" hidden></p>';
  $(".explorer-matrix").before(bar);
  $("#explorer-back-to-list").onclick=backToExplorerList;
  $("#analysis-company").onchange=event=>switchAnalysisCompany(event.target.value);
  for(const [id,step] of [["#analysis-company-prev",-1],["#analysis-company-next",1]])$(id).onclick=()=>{
    const companies=desktopExplorerCompanies(),index=companies.findIndex(company=>company.cik===S.profile?.company.cik),next=companies[index+step];if(next)switchAnalysisCompany(next.cik);
  };
  const density=document.createElement("label");density.innerHTML='행 밀도<select id="explorer-density"><option value="STANDARD">표준</option><option value="COMPACT">촘촘</option></select>';
  $(".explorer-display-fields").append(density);
  $("#explorer-density").onchange=event=>{desktopExplorer.density=event.target.value;$(".explorer-view").dataset.rowDensity=desktopExplorer.density;fitDesktopExplorerList()};
  window.addEventListener("resize",fitDesktopExplorerList);
  $(".explorer-tools").addEventListener("toggle",fitDesktopExplorerList,true);
  if(typeof ResizeObserver!=="undefined"){
    const observer=new ResizeObserver(fitDesktopExplorerList);
    for(const node of [$(".explorer-tools"),$(".explorer-summary"),$("#explorer-selection-tray")])observer.observe(node);
  }
  fitDesktopExplorerList();
}
function syncProfileTrigger(){
  const cik=$("#company-profile").hidden?null:S.profile?.company?.cik;
  for(const button of $$('[data-profile-cik]')){
    const expanded=button.dataset.profileCik===cik;
    button.setAttribute("aria-expanded",String(expanded));
    button.closest("tr").classList.toggle("profile-current",expanded);
  }
}
function showCompanyProfile(){
  const profile=$("#company-profile");
  profile.hidden=false;
  enterExplorerAnalysis("PROFILE");
  syncProfileTrigger();
  beginFinancialProfileBoard();
  profile.focus({preventScroll:true});
  $("#profile-title").scrollIntoView({block:"nearest"});
}
function closeProfile(returnFocus=true){
  if(returnFocus&&resultProfileSession.active){closeResultProfile(true);return}
  explorerBasis.profileToken++;
  explorerBasis.seriesToken++;
  const profile=$("#company-profile");
  profile.hidden=true;
  syncProfileTrigger();
  resetRevenueBreakdowns();
  leaveExplorerAnalysis("PROFILE",returnFocus);
  if(!returnFocus)return;
  const cik=desktopExplorer.saved?.mode==="PROFILE"?desktopExplorer.saved.cik:S.profile?.company?.cik;
  const replacement=$$('[data-profile-cik]').find(button=>button.dataset.profileCik===cik);
  const target=replacement||$("#explorer-query");
  target.focus({preventScroll:true});
}

function comparisonPeriodKind(observation,metric){
  return observation?.period_class||metric.observation_basis||metric.period_class;
}
function comparisonDate(value){
  if(typeof value!=="string"||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;
  const date=new Date(value+"T00:00:00Z");
  return Number.isFinite(date.getTime())&&date.toISOString().slice(0,10)===value?value:null;
}
function comparisonPeriod(observation,kind){
  if(!observation||observation.bucket_status==="PERIOD_CONFLICT")return null;
  const periodEnd=comparisonDate(observation.period_end);
  if(observation.period_end&&(!periodEnd||(observation.end_convention&&observation.end_convention!=="EXCLUSIVE")))return null;
  const recordedEnd=periodEnd||comparisonDate(observation.context_end_date);
  if(!recordedEnd)return null;
  const exclusive=periodEnd||observation.context_end_convention==="SOURCE_CONTEXT_END_EXCLUSIVE";
  const end=exclusive?inclusiveEnd(recordedEnd):recordedEnd;
  const start=kind==="INSTANT"||kind==="ANCHOR"?null:comparisonDate(observation.period_start);
  if(kind!=="INSTANT"&&kind!=="ANCHOR"&&(!["FY","QTD_3M","TTM"].includes(kind)||!start||start>=end))return null;
  return {kind,start,end,year:observation.fiscal_year,quarter:observation.fiscal_quarter};
}
function sharedComparisonPeriod(cells,anchor,basis){
  if(anchor?.bucket_status==="PERIOD_CONFLICT")return null;
  if(basis==="ANNUAL"){
    const annual=comparisonPeriod(anchor,"FY");
    if(annual)return annual;
  }
  const kind={ANNUAL:"FY",QUARTERLY:"QTD_3M",TTM:"TTM"}[basis];
  const available=cells.flatMap(({observation,metric})=>{
    if(observation?.availability_status!=="AVAILABLE"||observation.value==null||observation.quality_blocking||observation.quality_status==="BLOCK")return [];
    const period=comparisonPeriod(observation,comparisonPeriodKind(observation,metric));
    return period?[period]:[];
  });
  const spans=available.filter(period=>period.kind===kind);
  const candidates=spans.length?spans:basis==="TTM"?[]:available.filter(period=>period.kind==="INSTANT");
  const counts=new Map();
  let shared=null,maximum=0;
  for(const period of candidates){
    const key=JSON.stringify(period),count=(counts.get(key)||0)+1;
    counts.set(key,count);
    if(count>maximum){shared=period;maximum=count}
  }
  return shared||comparisonPeriod(anchor,"ANCHOR");
}
function comparisonPeriodCaption(period){
  if(!period)return "실제 기간 확인 불가";
  const end=period.end;
  const fiscal=period.year?`FY${period.year}${period.quarter?" "+period.quarter:""}`:"";
  const caption=period.start?`${({FY:"연간",QTD_3M:"분기",TTM:"TTM"})[period.kind]} ${period.start} ~ ${end}`
    :`${period.kind==="INSTANT"?"기준일":"기준 종료일"} ${end}`;
  return fiscal?`${caption} · ${fiscal}`:caption;
}
function comparisonValue(observation,metric,shared,basis){
  const value=basis==="ANNUAL"?observation:preparedExplorerObservation(observation);
  if(value?.value==null){
    const reason=observation?.reason||observation?.unavailable_reason||observation?.reason_codes?.[0];
    const message=({
      REQUIRED_ITEM_NOT_IN_PREPARED_DATA:"준비 자료에서 항목을 확인할 수 없음",
      INPUTS_NOT_COMPATIBLE:basis==="TTM"?"분기 합계 조건을 충족하지 않음":null,
      SEMANTIC_IDENTITY_MISMATCH:"보고 항목 기준이 다름",
    })[reason];
    const blocked=observation?.quality_blocking||observation?.quality_status==="BLOCK";
    return explorerValue(message&&!blocked?{...value,value:null,reason_labels:[message]}:value,metric);
  }
  const period=comparisonPeriod(observation,comparisonPeriodKind(observation,metric));
  const sameKindAndStart=period?.kind===shared?.kind&&period?.start===shared?.start;
  const labeledInstant=period?.kind==="INSTANT"&&comparisonPeriodKind(null,metric)==="INSTANT";
  const differs=period&&(!shared||period.end!==shared.end||
    (!sameKindAndStart&&!labeledInstant)||
    (period.year&&shared.year&&period.year!==shared.year)||
    (period.quarter&&shared.quarter&&period.quarter!==shared.quarter));
  const exception=differs?`<small class="comparison-period-exception">${compactFinancialCaption(comparisonPeriodCaption(period))}</small>`:"";
  return explorerValue(value,metric)+exception;
}
function comparisonTable(companies,rows,periods,basis){
  return `<table><thead><tr><th scope="col">지표 · 단위</th>${companies.map(company=>`<th scope="col">${esc([company.name,company.ticker===company.name?null:company.ticker].filter(Boolean).join(" · "))}<small class="comparison-company-period">${compactFinancialCaption(comparisonPeriodCaption(periods.get(company.cik)))}</small></th>`).join("")}</tr></thead><tbody>${rows.map(({metric,values})=>{
    const instant=comparisonPeriodKind(null,metric)==="INSTANT";
    const unit=unitLabel(metric)+(instant?" · 기말 기준":"");
    return `<tr><th scope="row">${esc(metric.label)}<small>${esc(unit)}</small></th>${companies.map(company=>`<td>${comparisonValue(values[company.cik],metric,periods.get(company.cik),basis)}</td>`).join("")}</tr>`;
  }).join("")}</tbody></table>`;
}
async function renderAnnualComparison(){const token=++explorerBasis.comparisonToken,key=explorerContextKey();const ids=[...$("#comparison-metrics").selectedOptions].map(x=>x.value),ciks=[...S.explorerSelected];if(ciks.length<2||ciks.length>4)throw new Error("비교할 기업을 2~4개 선택해 주세요.");if(!ids.length)throw new Error("비교 지표를 하나 이상 선택해 주세요.");const d=S.explorerDataset||S.defaultDataset,params=new URLSearchParams({dataset_id:d.dataset_id,dataset_publication_id:d.publication_id||d.dataset_publication_id,ciks:ciks.join(","),metric_ids:ids.join(","),...(explorerBasis.latestAnnual?{latest:"true"}:{fiscal_year:String(S.explorerYear)})}),r=await api(`/api/company-comparison?${params}`);if(token!==explorerBasis.comparisonToken||key!==explorerContextKey())return;const periods=new Map(r.companies.map(company=>{
  const anchor=r.actual_periods[company.cik];
  const period=sharedComparisonPeriod(r.rows.map(row=>({metric:row.metric,observation:row.values[company.cik]})),anchor,"ANNUAL");
  return [company.cik,period&&!period.year?{...period,year:r.selected_fiscal_year}:period];
}));$("#comparison-result").innerHTML=`<p>${esc(r.date_limitation)}</p>`+comparisonTable(r.companies,r.rows,periods,"ANNUAL")}
function comparisonInitialMetricIds(definitions,basis){const ids=basis==="ANNUAL"?["revenue","operating_income","cfo","standardized_fcf"]:basis==="TTM"?["ttm_revenue","ttm_operating_income","ttm_cfo","ttm_standardized_fcf"]:["quarter_revenue","quarter_operating_income","quarter_cfo","quarter_standardized_fcf"];return ids.filter(id=>definitions.some(definition=>definition.metric_id===id))}
function openAnnualComparison(){const metrics=S.explorerCatalog?.metrics||[];if(!metrics.length)throw new Error("전체 탐색 지표 정의를 불러오지 못했습니다.");$("#comparison-metrics").innerHTML=metrics.map(x=>`<option value="${x.metric_id}" ${comparisonInitialMetricIds(metrics,"ANNUAL").includes(x.metric_id)?"selected":""}>${esc(x.label)}</option>`).join("");$("#comparison-panel").hidden=false;$("#comparison-panel").scrollIntoView({block:"nearest"})}
function bindAnnualExplorer(){$$('[data-view]').forEach(x=>x.onclick=e=>{e.preventDefault();window.history.replaceState(null,"",x.getAttribute("href"));showView(x.dataset.view,true)});$("#explorer-year").onchange=async()=>{explorerBasis.latestAnnual=$("#explorer-year").value==="LATEST";if(!explorerBasis.latestAnnual)S.explorerYear=Number($("#explorer-year").value);await loadExplorer(explorerBasis.latestAnnual?null:S.explorerYear);await loadLibrary()};$("#explorer-query").oninput=()=>loadExplorer().catch(fail);$("#explorer-preset").onchange=()=>{updateExplorerSort();loadExplorer().catch(fail)};$("#explorer-sort").onchange=()=>loadExplorer().catch(fail);$("#explorer-direction").onchange=()=>loadExplorer().catch(fail);$("#library-query").oninput=()=>loadLibrary().catch(fail);$("#library-category").onchange=()=>loadLibrary().catch(fail);$("#compare-selected").onclick=openComparison;$("#close-comparison").onclick=()=>$("#comparison-panel").hidden=true;$("#run-comparison").onclick=()=>renderComparison().catch(fail);$("#close-profile").onclick=()=>closeProfile();$("#profile-metric").onchange=renderProfileTrend;$("#company-profile").addEventListener("keydown",event=>{
    if(event.key==="Escape"&&!event.defaultPrevented){event.preventDefault();closeProfile()}
  })
}


// Explorer-only contexts. Annual guide, screening criteria, and saved runs retain their own state.
const explorerBasis={basis:"ANNUAL",latestAnnual:false,loading:false,readyKey:null,version:0,loadToken:0,profileToken:0,seriesToken:0,comparisonToken:0,inventoryKey:null,inventoryPromise:null,inventory:null,snapshots:new Map(),snapshot:null,metrics:[],periods:{QUARTERLY:null,TTM:null},views:{ANNUAL:null,QUARTERLY:{preset:"CORE",sort:"company",direction:"asc"},TTM:{preset:"ALL",sort:"company",direction:"asc"}},profileBasis:"ANNUAL",profileMetrics:{ANNUAL:"revenue",QUARTERLY:"quarter_revenue",TTM:"ttm_revenue"},unavailableReason:""};
function explorerDataset(){return S.explorerDataset||S.defaultDataset}
function latestExplorerPeriod(){return explorerBasis.basis==="ANNUAL"?explorerBasis.latestAnnual:explorerBasis.periods[explorerBasis.basis]==="LATEST"}
function explorerContextKey(){return`${explorerDataset()?.dataset_id}:${explorerBasis.basis}:${explorerBasis.basis==="ANNUAL"?(explorerBasis.latestAnnual?"LATEST":S.explorerYear):explorerBasis.periods[explorerBasis.basis]}`}
function explorerBasisLabel(){return({ANNUAL:"연간",QUARTERLY:"분기",TTM:"TTM"})[explorerBasis.basis]}
function explorerNotice(message="",error=false){const node=$("#explorer-message");if(!node)return;node.textContent=message||explorerBasis.unavailableReason;node.classList.toggle("explorer-error",error);node.hidden=!node.textContent}
function periodCoordinate(row){return`${row.calendar_year}Q${row.calendar_quarter}`}
function chooseExplorerPeriod(inventory){
  const companies=new Set(inventory.rows.map(row=>row.cik)),available=new Map();
  for(const row of inventory.rows)if(row.bucket_status==="PERIOD_AVAILABLE"){
    const key=periodCoordinate(row);if(!available.has(key))available.set(key,new Set());available.get(key).add(row.cik);
  }
  const descending=[...inventory.spine].sort((a,b)=>b.calendar_year-a.calendar_year||b.calendar_quarter-a.calendar_quarter);
  const common=descending.find(row=>companies.size>0&&available.get(periodCoordinate(row))?.size===companies.size);
  const latest=descending.find(row=>available.get(periodCoordinate(row))?.size>0);
  return{selected:common||latest,available,total:companies.size};
}
async function ensureExplorerInventory(){
  const dataset=explorerDataset(),key=dataset?.dataset_id;if(!key)return null;
  if(explorerBasis.inventoryKey===key)return explorerBasis.inventoryPromise;
  explorerBasis.inventoryKey=key;
  explorerBasis.inventoryPromise=(async()=>{
    try{
      const value=await api(`/api/quarter-periods?dataset_id=${encodeURIComponent(key)}`);
      if(explorerDataset()?.dataset_id!==key)return null;
      if(!Array.isArray(value.spine)||!Array.isArray(value.rows))throw new Error("분기 기간 자료를 확인할 수 없습니다.");
      const chosen=chooseExplorerPeriod(value);if(!chosen.selected)throw new Error("준비된 분기 기간이 없습니다.");
      explorerBasis.inventory=value;explorerBasis.unavailableReason="";
      for(const basis of ["QUARTERLY","TTM"])if(!explorerBasis.periods[basis])explorerBasis.periods[basis]=batchView.snapshot?"LATEST":periodCoordinate(chosen.selected);
      $("#explorer-quarter").innerHTML=(batchView.snapshot?'<option value="LATEST">회사별 최신</option>':"")+value.spine.map(row=>{const period=periodCoordinate(row);return`<option value="${period}">${period} · 준비 ${chosen.available.get(period)?.size||0}/${chosen.total}</option>`}).join("");
      for(const option of $("#explorer-basis").options)option.disabled=false;
      if(!explorerBasis.loading)explorerNotice();return value;
    }catch(error){
      if(explorerDataset()?.dataset_id!==key)return null;
      explorerBasis.unavailableReason="분기·TTM 자료가 준비되지 않아 연간 보기만 사용할 수 있습니다.";
      for(const option of $("#explorer-basis").options)option.disabled=option.value!=="ANNUAL";
      if(!explorerBasis.loading)explorerNotice();return null;
    }
  })();return explorerBasis.inventoryPromise;
}
function invalidateExplorerDetails(){
  invalidateCompanyTrend();
  explorerBasis.version++;explorerBasis.profileToken++;explorerBasis.seriesToken++;explorerBasis.comparisonToken++;S.explorerToken++;
  leaveExplorerAnalysis(desktopExplorer.mode,false);cancelComparisonRefresh();
  resetRevenueBreakdowns();$("#company-profile").hidden=true;$("#comparison-panel").hidden=true;$("#comparison-result").replaceChildren();
  $("#explorer-body").innerHTML='<tr><td colspan="12" class="empty">선택한 자료를 불러오는 중입니다…</td></tr>';
}
function explorerViewState(){return{preset:$("#explorer-preset").value,sort:$("#explorer-sort").value,direction:$("#explorer-direction").value}}
async function switchExplorerBasis(){
  const requested=$("#explorer-basis").value,previous=explorerBasis.basis;
  explorerBasis.views[previous]=explorerViewState();invalidateExplorerDetails();explorerBasis.basis=requested;
  $("#explorer-year").closest("label").hidden=requested!=="ANNUAL";$("#explorer-quarter").closest("label").hidden=requested==="ANNUAL";
  const all=$("#explorer-preset option[value='ALL']");if(requested==="ANNUAL")all?.remove();else if(!all)$("#explorer-preset").insertAdjacentHTML("beforeend",'<option value="ALL">모든 지표</option>');
  for(const option of $("#explorer-preset").options)option.textContent=requested==="TTM"?({CORE:"TTM 핵심 금액",GROWTH_PROFIT:"TTM 수익성",CASH_STABILITY:"TTM 현금흐름",ALL:"TTM 전체 지표"})[option.value]:explorerBasis.annualPresetLabels?.[option.value]||(option.value==="ALL"?"모든 지표":option.textContent);
  const view=explorerBasis.views[requested];$("#explorer-preset").value=view.preset;$("#explorer-direction").value=view.direction;
  if(requested!=="ANNUAL")$("#explorer-quarter").value=explorerBasis.periods[requested];
  if(requested==="ANNUAL"){annualUpdateExplorerSort();$("#explorer-sort").value=view.sort}
  const version=explorerBasis.version,key=explorerContextKey(),pending=loadExplorer(),token=explorerBasis.loadToken;
  await pending;
  if(explorerBasis.basis!==requested||version!==explorerBasis.version||token!==explorerBasis.loadToken||key!==explorerContextKey()||explorerBasis.loading||explorerBasis.readyKey!==key)return;
  $("#explorer-sort").value=[...$("#explorer-sort").options].some(option=>option.value===view.sort)?view.sort:"company";
  if(requested!=="ANNUAL")renderExplorer();
}
function activeExplorerMetrics(){return explorerBasis.basis==="ANNUAL"?S.explorerCatalog?.metrics||[]:explorerBasis.metrics}
function explorerMetric(id){if(explorerBasis.basis==="ANNUAL")return annualExplorerMetric(id);const definition=explorerBasis.metrics.find(item=>item.metric_id===id);if(!definition)throw new Error(`탐색 지표 정의를 찾을 수 없습니다: ${id}`);return definition}
function interimMetricIds(){
  const definitions=explorerBasis.metrics,preset=$("#explorer-preset").value;
  if(preset==="ALL")return definitions.map(item=>item.metric_id);
  if(explorerBasis.basis==="TTM"){
    const groups={CORE:["ttm_revenue","ttm_operating_income","ttm_net_income","ttm_cfo","ttm_standardized_fcf"],GROWTH_PROFIT:["ttm_revenue","ttm_operating_income","ttm_net_income","ttm_gross_margin","ttm_operating_margin","ttm_net_margin"],CASH_STABILITY:["ttm_cfo","ttm_standardized_fcf","ttm_fcf_margin"]};
    return(groups[preset]||groups.CORE).filter(id=>definitions.some(item=>item.metric_id===id));
  }
  const wanted=(EXPLORER_PRESETS[preset]||EXPLORER_PRESETS.CORE).map(id=>"quarter_"+id);
  return wanted.filter(id=>definitions.some(item=>item.metric_id===id));
}
function updateExplorerSort(){
  if(explorerBasis.basis==="ANNUAL")return annualUpdateExplorerSort();
  const current=$("#explorer-sort").value;$("#explorer-sort").innerHTML='<option value="company">기업명</option>'+interimMetricIds().map(id=>`<option value="${id}">${esc(explorerMetric(id).label)}</option>`).join("");
  if([...$("#explorer-sort").options].some(option=>option.value===current))$("#explorer-sort").value=current;
}
function explorerHeaderSortDirection(key){
  return $("#explorer-sort").value===key?($("#explorer-direction").value==="asc"?"desc":"asc"):key==="company"?"asc":"desc";
}
function explorerSortHeader(key,label,caption=label,unit=""){
  const selected=$("#explorer-sort").value===key,direction=$("#explorer-direction").value;
  const order=selected?(direction==="desc"?"descending":"ascending"):"none";
  const next=explorerHeaderSortDirection(key)==="asc"?"오름차순":"내림차순";
  return `<th scope="col" aria-sort="${order}" title="${esc(label)}"><button type="button" class="explorer-header-sort" data-explorer-sort="${esc(key)}" aria-label="${esc(label)}: ${next} 정렬">
    <span>${esc(caption)}</span><span class="explorer-sort-arrow" aria-hidden="true">${selected?(direction==="desc"?"↓":"↑"):"↕"}</span>${unit?`<small>${esc(unit)}</small>`:""}</button></th>`;
}
function renderExplorerHeaders(ids,periodCaption,annual){
  const focused=document.activeElement?.dataset?.explorerSort;
  $("#explorer-head").innerHTML=`<tr><th scope="col"><span class="sr-only">비교 선택</span></th>${explorerSortHeader("company","기업명","기업")}<th scope="col">${esc(periodCaption)}</th>${ids.map(id=>{
    const metric=explorerMetric(id),caption=annual?CORE_SHORT_LABELS[id]||metric.label:explorerMetricCaption(metric);
    return explorerSortHeader(id,metric.label,caption,unitLabel(metric));
  }).join("")}</tr>`;
  const buttons=$$('[data-explorer-sort]');
  buttons.forEach(button=>button.onclick=()=>sortExplorerByHeader(button.dataset.explorerSort));
  if(focused)buttons.find(button=>button.dataset.explorerSort===focused)?.focus({preventScroll:true});
}
async function sortExplorerByHeader(key){
  if(![...$("#explorer-sort").options].some(option=>option.value===key))return;
  const direction=explorerHeaderSortDirection(key);
  $("#explorer-sort").value=key;$("#explorer-direction").value=direction;
  explorerBasis.views[explorerBasis.basis]=explorerViewState();
  await loadExplorer();
}
function preparedExplorerObservation(observation){
  if(observation&&observation.availability_status==="AVAILABLE"&&observation.value!==null&&observation.value!==undefined&&!observation.quality_blocking&&observation.quality_status!=="BLOCK")return observation;
  const reason=["PERIOD_CONFLICT","PERIOD_MISMATCH"].includes(observation?.reason)?"실제 기간 확인 필요":observation?.quality_blocking||observation?.quality_status==="BLOCK"?"품질 검토가 필요한 자료입니다.":businessReason(observation?.reason||"자료가 준비되지 않았습니다.");
  return{...observation,value:null,reason_labels:[reason]};
}
function compareExplorerDecimals(a,b){
  const left=shiftDecimal(a,0),right=shiftDecimal(b,0),negativeLeft=left.startsWith("-"),negativeRight=right.startsWith("-");
  if(negativeLeft!==negativeRight)return negativeLeft?-1:1;
  const [li,lf=""]=(negativeLeft?left.slice(1):left).split("."),[ri,rf=""]=(negativeRight?right.slice(1):right).split(".");
  const fractionLength=Math.max(lf.length,rf.length),result=li.length-ri.length||li.localeCompare(ri)||lf.padEnd(fractionLength,"0").localeCompare(rf.padEnd(fractionLength,"0"));
  return negativeLeft?-result:result;
}
function filterSortExplorerRows(rows,query,sort,direction){
  const text=query.trim().toLocaleLowerCase(),companyOrder=(a,b)=>(a.company.name||a.company.ticker||"").localeCompare(b.company.name||b.company.ticker||"")||a.company.cik.localeCompare(b.company.cik);
  return rows.filter(row=>[row.company.name,row.company.ticker,row.company.industry,row.company.sic_description,row.company.sic].filter(Boolean).join(" ").toLocaleLowerCase().includes(text)).slice().sort((a,b)=>{
    if(sort==="company")return(direction==="desc"?-1:1)*companyOrder(a,b);
    const left=preparedExplorerObservation(a.metrics[sort]),right=preparedExplorerObservation(b.metrics[sort]);
    if(left.value===null||right.value===null)return left.value===right.value?companyOrder(a,b):left.value===null?1:-1;
    return(direction==="desc"?-1:1)*compareExplorerDecimals(left.value,right.value)||companyOrder(a,b);
  });
}
function cachedExplorerSnapshot(dataset,period){
  const key=`${dataset}:${period}`;if(explorerBasis.snapshots.has(key))return explorerBasis.snapshots.get(key);
  const latest=period==="LATEST",coordinate=period.match(/^(\d{4})Q([1-4])$/);if(!latest&&!coordinate)throw new Error("종료 분기를 선택해 주세요.");
  const pending=api(`/api/quarter-explorer?dataset_id=${encodeURIComponent(dataset)}&include_evidence=false&${latest?"latest=true":`calendar_year=${coordinate[1]}&calendar_quarter=${coordinate[2]}`}`).then(value=>{
    if((latest?value.period_scope!=="LATEST_COMPANY":periodCoordinate(value)!==period)||!Array.isArray(value.rows)||!Array.isArray(value.metrics))throw new Error("분기 응답의 기간이 선택과 다릅니다.");return value;
  }).catch(error=>{if(explorerBasis.snapshots.get(key)===pending)explorerBasis.snapshots.delete(key);throw error});
  explorerBasis.snapshots.set(key,pending);while(explorerBasis.snapshots.size>2)explorerBasis.snapshots.delete(explorerBasis.snapshots.keys().next().value);return pending;
}
async function loadExplorer(year=null){
  const token=++explorerBasis.loadToken,version=explorerBasis.version,dataset=explorerDataset();if(!dataset||(batchView.enabled&&!batchView.snapshot&&!batchView.fixedOnly))return;
  explorerBasis.loading=true;explorerBasis.readyKey=null;$("#compare-selected").disabled=true;explorerNotice(`${explorerBasisLabel()} 자료를 불러오는 중입니다…`);$("#explorer-table").setAttribute("aria-busy","true");
  try{
    if(explorerBasis.basis==="ANNUAL"){await loadAnnualExplorer(year);if(token!==explorerBasis.loadToken||version!==explorerBasis.version)return;}
    else{
      const inventory=await ensureExplorerInventory();if(!inventory)throw new Error(explorerBasis.unavailableReason);
      const basis=explorerBasis.basis,period=explorerBasis.periods[basis],snapshot=await cachedExplorerSnapshot(dataset.dataset_id,period);
      if(token!==explorerBasis.loadToken||version!==explorerBasis.version)return;
      explorerBasis.snapshot=snapshot;$("#explorer-quarter").value=period;explorerBasis.metrics=snapshot.metrics.filter(metric=>(metric.observation_basis==="TTM"||metric.metric_id.startsWith("ttm_"))===(basis==="TTM"));
      if(!explorerBasis.metrics.length)throw new Error("선택한 보기 기준의 지표가 준비되지 않았습니다.");renderExplorer();
    }
    explorerBasis.readyKey=explorerContextKey();explorerNotice();
  }catch(error){if(token===explorerBasis.loadToken&&version===explorerBasis.version){$("#explorer-body").innerHTML='<tr><td colspan="12" class="empty">선택한 자료를 표시할 수 없습니다.</td></tr>';explorerNotice(error.message,true)}}
  finally{if(token===explorerBasis.loadToken){explorerBasis.loading=false;$("#explorer-table").setAttribute("aria-busy","false");updateCompareButton();fitDesktopExplorerList();if(explorerBasis.readyKey!==explorerContextKey())$("#compare-selected").disabled=true}}
}
function interimPrimaryObservation(row){const id=explorerBasis.basis==="TTM"?"ttm_revenue":"quarter_revenue";return preparedExplorerObservation(row.metrics[id])}
function interimPeriodCaption(observation){return observation?.period_end?`${actualPeriod(observation)} · ${fiscalLabel(observation)}`:"자료 기간 없음"}
function renderExplorer(){
  if($("#explorer-column-picker"))$("#explorer-column-picker").hidden=explorerBasis.basis!=="ANNUAL";
  if(explorerBasis.basis==="ANNUAL")return renderAnnualExplorer();
  const snapshot=explorerBasis.snapshot;if(!snapshot)return;registerExplorerCompanies(snapshot.rows.map(row=>row.company));updateExplorerSort();
  const ids=interimMetricIds(),rows=filterSortExplorerRows(snapshot.rows,$("#explorer-query").value,$("#explorer-sort").value,$("#explorer-direction").value);explorerBasis.visibleRows=rows;
  $("#explorer-count").textContent=`${rows.length}개 기업 · ${latestExplorerPeriod()?"회사별 최신":explorerBasis.periods[explorerBasis.basis]} ${explorerBasisLabel()}`;
  $("#explorer-year-note").textContent=`${explorerBasis.metrics.length}개 지표 · 실제 기간과 회사 회계표시는 기업·지표마다 다릅니다. 미제공은 —입니다.`;$("#explorer-asof").textContent=snapshot.financial_as_of;
  renderExplorerHeaders(ids,"실제 기간 · 회사 회계표시",false);
  $("#explorer-body").innerHTML=rows.length?rows.map((row,index)=>`<tr><td><input type="checkbox" data-explorer-select="${index}" data-explorer-cik="${esc(row.company.cik)}" aria-label="${esc(row.company.ticker)} 비교 선택" ${S.explorerSelected.has(row.company.cik)?"checked":""}></td><td><button class="company" data-explorer-open="${index}" data-profile-cik="${esc(row.company.cik)}" aria-controls="company-profile"><strong>${esc(row.company.name||row.company.ticker)}</strong><span class="company-meta" title="${esc(row.company.ticker)} · ${esc(row.company.sic_description||row.company.industry||"업종 정보 없음")}"><small>${esc(row.company.ticker)}</small><small class="industry">${esc(row.company.sic_description||row.company.industry||"업종 정보 없음")}</small></span></button></td><td class="actual-period">${latestExplorerPeriod()?companyFinancialPeriodDisplay(row.period):compactFinancialCaption(interimPeriodCaption(interimPrimaryObservation(row)))}</td>${ids.map(id=>`<td>${explorerValue(preparedExplorerObservation(row.metrics[id]),explorerMetric(id))}</td>`).join("")}</tr>`).join(""):`<tr><td colspan="${ids.length+3}" class="empty">검색 결과가 없습니다.</td></tr>`;
  $$('[data-explorer-select]').forEach(node=>node.onchange=()=>{const cik=rows[Number(node.dataset.explorerSelect)].company.cik;transitionExplorerSelection("toggle",cik,node.checked,rows[Number(node.dataset.explorerSelect)].company,node)});
  $$('[data-explorer-open]').forEach(node=>node.onclick=()=>openProfile(rows[Number(node.dataset.explorerOpen)].company.cik,node).catch(error=>explorerNotice(error.message,true)));updateCompareButton();
}
function interimAxisCaption(row,x,missing){return`<text class="year-label ${missing?"missing-year":""}" x="${x}" y="126"><tspan x="${x}">${esc(row.calendar_year)}</tspan><tspan x="${x}" dy="12">Q${esc(row.calendar_quarter)}</tspan>${missing?`<tspan x="${x}" dy="12">없음</tspan>`:""}</text>`}
function explorerMetricCaption(metric){const id=metric.metric_id.replace(/^(quarter_|ttm_)/,"");return CORE_SHORT_LABELS[id]||({operating_income:"영업이익",gross_profit:"매출총이익",gross_margin:"매출총이익률",net_margin:"순이익률",fcf_margin:"FCF 마진"})[id]||metric.label}
function profileSeriesLabel(row){return explorerBasis.profileBasis==="ANNUAL"?`FY${row.fiscal_year}`:periodCoordinate(row)}
function profileTrendCaption(interim){const label=$("#profile-metric").closest("label");if(label.firstChild?.nodeType===Node.TEXT_NODE)label.firstChild.textContent=interim?"8개 종료 분기 흐름":"4개 회계연도 흐름"}
async function openProfile(cik,button,surfaceError=false,deferShow=false){
  if(explorerBasis.basis==="ANNUAL"){
    const key=explorerContextKey(),pending=openAnnualProfile(cik,button),token=explorerBasis.profileToken;
    try{return await pending}catch(error){if(token===explorerBasis.profileToken&&key===explorerContextKey()){if(surfaceError)throw error;explorerNotice(error.message,true)}return}
  }
  const row=explorerBasis.snapshot?.rows.find(item=>item.company.cik===cik);if(!row)return;
  const token=++explorerBasis.profileToken,key=explorerContextKey(),basis=explorerBasis.basis;S.lastFocus=button;explorerBasis.profileBasis=basis;
  const definitions=explorerBasis.metrics,groups=[...new Set(definitions.map(item=>item.category))].map(category=>({label:categoryLabel(category),metrics:definitions.filter(item=>item.category===category).map(definition=>({definition,observation:preparedExplorerObservation(row.metrics[definition.metric_id])}))}));
  S.profile={company:{...row.company,industry:row.company.sic_description||row.company.industry},financial_as_of:explorerBasis.snapshot.financial_as_of,selected_fiscal_year:row.period?.fiscal_year||explorerBasis.snapshot.calendar_year,actual_period:interimPrimaryObservation(row),latestAnchor:latestExplorerPeriod()?row.period:undefined,summary:interimMetricIds().slice(0,8).map(id=>({definition:explorerMetric(id),observation:preparedExplorerObservation(row.metrics[id])})),groups,series:{}};
  S.profileMetric=explorerBasis.profileMetrics[basis];if(!definitions.some(item=>item.metric_id===S.profileMetric))S.profileMetric=definitions[0].metric_id;
  explorerBasis.profileKey=key;renderProfile();profileTrendCaption(true);$("#profile-metric").value=S.profileMetric;
  $("#profile-intro").innerHTML=`<p><strong>${esc(row.company.ticker)}</strong> · ${esc(row.company.sic_description||row.company.industry||"업종 정보 없음")}</p><p class="muted">${latestExplorerPeriod()?"회사별 최신":explorerBasis.periods[basis]} ${explorerBasisLabel()} · ${latestExplorerPeriod()?companyFinancialPeriodDisplay(row.period):compactFinancialCaption(interimPeriodCaption(interimPrimaryObservation(row)))}</p><p class="muted">재무 기준일 ${compactFinancialCaption(S.profile.financial_as_of)} · 금액은 백만 USD, 비율은 %입니다.</p>`;
  if(token===explorerBasis.profileToken&&key===explorerContextKey()&&!deferShow)showCompanyProfile()
}
async function renderProfileTrend(){
  const basis=explorerBasis.profileBasis,id=$("#profile-metric").value;explorerBasis.profileMetrics[basis]=id;
  if(basis==="ANNUAL")return renderProfileTrendData();
  const token=++explorerBasis.seriesToken,key=explorerContextKey(),profile=S.profile;if(explorerBasis.profileKey!==key)return;
  S.profileMetric=id;$("#profile-chart").innerHTML='<p class="empty">분기 흐름을 불러오는 중입니다…</p>';$("#profile-series").replaceChildren();
  try{
    const result=await api(`/api/quarter-series?dataset_id=${encodeURIComponent(explorerDataset().dataset_id)}&cik=${encodeURIComponent(profile.company.cik)}&metric_id=${encodeURIComponent(id)}&limit=8${profile.latestAnchor!==undefined?"&latest=true":""}`);
    if(token!==explorerBasis.seriesToken||key!==explorerContextKey()||profile!==S.profile)return;
    profile.series[id]=result.observations.filter(row=>profile.latestAnchor===undefined||profile.latestAnchor&&periodCoordinate(row)<=periodCoordinate(profile.latestAnchor)).map(preparedExplorerObservation);renderProfileTrendData();
  }catch(error){if(token===explorerBasis.seriesToken&&key===explorerContextKey())$("#profile-chart").innerHTML=`<p class="message error">${esc(error.message)}</p>`}
}
function openComparison(){
  if(explorerBasis.readyKey!==explorerContextKey())throw new Error("선택한 탐색 자료를 먼저 불러와 주세요.");
  if(explorerBasis.basis==="ANNUAL"){openAnnualComparison();enterExplorerAnalysis("COMPARE");renderComparisonMetricPicker();mountCompanyTrend();arrangeComparisonAnalysis();queueComparisonRefresh();return}
  const ids=comparisonInitialMetricIds(explorerBasis.metrics,explorerBasis.basis);$("#comparison-metrics").innerHTML=explorerBasis.metrics.map(metric=>`<option value="${metric.metric_id}" ${ids.includes(metric.metric_id)?"selected":""}>${esc(metric.label)}</option>`).join("");
  $("#comparison-result").replaceChildren();$("#comparison-panel").hidden=false;$("#comparison-panel").scrollIntoView({block:"nearest"});enterExplorerAnalysis("COMPARE");renderComparisonMetricPicker();mountCompanyTrend();arrangeComparisonAnalysis();queueComparisonRefresh();
}
async function renderComparison(){
  if(explorerBasis.basis==="ANNUAL"){
    const key=explorerContextKey(),pending=renderAnnualComparison(),token=explorerBasis.comparisonToken;
    try{return await pending}catch(error){if(token===explorerBasis.comparisonToken&&key===explorerContextKey())$("#comparison-result").innerHTML=`<p class="message error">${esc(error.message)}</p>`;return}
  }
  const token=++explorerBasis.comparisonToken,key=explorerContextKey(),ids=[...$("#comparison-metrics").selectedOptions].map(option=>option.value),ciks=[...S.explorerSelected],period=explorerBasis.periods[explorerBasis.basis],coordinate=period.match(/^(\d{4})Q([1-4])$/);
  if(ciks.length<2||ciks.length>4||!ids.length)throw new Error("기업 2~4개와 비교 지표를 선택해 주세요.");
  $("#comparison-result").textContent="비교 자료를 불러오는 중입니다…";
  try{
    const results=await Promise.all(ids.map(metric_id=>api(`/api/quarter-comparison?${new URLSearchParams({dataset_id:explorerDataset().dataset_id,ciks:ciks.join(","),metric_id,...(period==="LATEST"?{latest:"true"}:{calendar_year:coordinate[1],calendar_quarter:coordinate[2]})})}`)));
    if(token!==explorerBasis.comparisonToken||key!==explorerContextKey())return;
    if(results.some((result,index)=>result.metric_id!==ids[index]||(period==="LATEST"?result.period_scope!=="LATEST_COMPANY":periodCoordinate(result)!==period)||result.rows.length!==ciks.length||result.rows.some(row=>!ciks.includes(row.company.cik))))throw new Error("비교 응답의 범위가 선택과 다릅니다.");
    const companies=results[0].rows.map(row=>row.company),basis=explorerBasis.basis;
    const rows=results.map((result,index)=>({
      metric:explorerMetric(ids[index]),
      values:Object.fromEntries(result.rows.map(row=>[row.company.cik,row.observation])),
    }));
    const periods=new Map(companies.map(company=>{
      const anchor=period==="LATEST"
        ?results[0].rows.find(row=>row.company.cik===company.cik)?.period
        :explorerBasis.inventory?.rows.find(row=>row.cik===company.cik&&periodCoordinate(row)===period);
      const cells=rows.map(row=>({metric:row.metric,observation:row.values[company.cik]}));
      return [company.cik,sharedComparisonPeriod(cells,anchor,basis)];
    }));
    $("#comparison-result").innerHTML=`<p>${period==="LATEST"?"회사별 최신":period} ${explorerBasisLabel()} · 기업마다 실제 공시 기간과 회계표시가 다릅니다.</p>`+comparisonTable(companies,rows,periods,basis);
  }catch(error){if(token===explorerBasis.comparisonToken&&key===explorerContextKey())$("#comparison-result").innerHTML=`<p class="message error">${esc(error.message)}</p>`}
}
// Ordered display selection and plot geometry shared by the two profile boards.
const PROFILE_BOARD_LIMIT=8;
const PROFILE_BOARD_STYLES=[
  ["#075e8a",""],["#32634f","7 4"],["#8b5a12","2 3"],["#795787","10 3 2 3"],
  ["#a03f42","5 3"],["#106b72","12 4"],["#5f593c","4 2 1 2"],["#45487e","1 3"],
];
function createProfileBoard(ids=[]){
  return {order:ids.slice(),colors:new Map(ids.map((id,index)=>[id,index]))};
}
function changeProfileBoard(board,id,action){
  const index=board.order.indexOf(id);
  if(action==="add"&&index<0&&board.order.length<PROFILE_BOARD_LIMIT){
    board.order.push(id);
    const used=new Set(board.colors.values());
    board.colors.set(id,PROFILE_BOARD_STYLES.findIndex((_,slot)=>!used.has(slot)));
  }else if(action==="remove"&&index>=0){
    board.order.splice(index,1);board.colors.delete(id);
  }else if((action==="up"||action==="down")&&index>=0){
    const target=index+(action==="up"?-1:1);
    if(target>=0&&target<board.order.length)[board.order[index],board.order[target]]=[board.order[target],id];
  }
}
function profileBoardSwatch(index){
  const [color,dash]=PROFILE_BOARD_STYLES[index];
  return `<svg class="board-swatch" viewBox="0 0 28 12" aria-hidden="true" focusable="false"><line x1="1" x2="27" y1="6" y2="6" stroke="${color}" stroke-dasharray="${dash}"/><circle cx="14" cy="6" r="2.5" stroke="${color}"/></svg>`;
}
function renderProfileBoardSelection(host,board,options,onChange){
  const list=host.querySelector(".profile-board-choices"),order=host.querySelector(".profile-board-order");
  const status=host.querySelector(".profile-board-count"),labels=new Map(options.map(item=>[item.id,item.label]));
  status.textContent=`${board.order.length}/${PROFILE_BOARD_LIMIT}개 선택`;
  const capped=board.order.length>=PROFILE_BOARD_LIMIT;
  list.innerHTML=options.map(({id,label})=>`<label><input type="checkbox" data-board-choice="${esc(id)}" ${board.colors.has(id)?"checked":capped?"disabled":""}> <span>${esc(label)}</span></label>`).join("")||"<p>선택할 항목이 없습니다.</p>";
  order.innerHTML=board.order.map((id,index)=>{
    const label=labels.get(id);
    const button=(action,title,disabled=false)=>`<button type="button" class="quiet" data-board-action="${action}" data-board-id="${esc(id)}" aria-label="${esc(label)} ${title}" ${disabled?"disabled":""}>${title}</button>`;
    return `<li>${profileBoardSwatch(board.colors.get(id))}<span>${esc(label)}</span><div class="board-order-actions">${button("up","위로",index===0)}${button("down","아래로",index===board.order.length-1)}${button("remove","삭제")}</div></li>`;
  }).join("");
  function apply(id,action,fromList){
    changeProfileBoard(board,id,action);
    renderProfileBoardSelection(host,board,options,onChange);
    onChange();
    const choice=[...list.querySelectorAll("[data-board-choice]")].find(node=>node.dataset.boardChoice===id);
    const actions=[...order.querySelectorAll("[data-board-action]:not([disabled])")];
    const matching=actions.filter(node=>node.dataset.boardId===id);
    const target=fromList?choice:matching.find(node=>node.dataset.boardAction===action)||matching[0]||actions[0]||host.querySelector("summary");
    target?.focus({preventScroll:true});
  }
  list.querySelectorAll("[data-board-choice]").forEach(node=>node.onchange=()=>apply(node.dataset.boardChoice,node.checked?"add":"remove",true));
  order.querySelectorAll("[data-board-action]").forEach(node=>node.onclick=()=>apply(node.dataset.boardId,node.dataset.boardAction,false));
}
const PROFILE_BOARD_SELECTION=`<details class="profile-board-picker"><summary>항목 선택·순서 <span class="profile-board-count"></span></summary>
  <div class="profile-board-choices"></div><ol class="profile-board-order" aria-label="선택 항목과 표시 순서"></ol></details>`;

function profileBoardExact(value,definition){
  return definition.unit_kind==="MONEY"?`${shiftDecimal(value,0)} USD`:
    `${shiftDecimal(value,0)}${definition.unit_kind==="PERCENT"?(["pp","PERCENTAGE_POINT"].includes(definition.unit)?" %p":" %"):definition.unit_kind==="RATIO"?" 배":""}`;
}
function profileBoardUnit(definition){if(["pp","PERCENTAGE_POINT"].includes(definition.unit))return "%p";return definition.unit_kind==="RATIO"?"배":unitLabel(definition)}
function profileBoardValue(value,definition,reason="준비된 값이 없습니다.",exact=false){
  if(value==null)return `<span class="missing" title="${esc(reason)}" aria-label="${esc(reason)}">—</span>`;
  const raw=esc(profileBoardExact(value,definition));
  const text=definition.unit_kind==="RATIO"||["pp","PERCENTAGE_POINT"].includes(definition.unit)?esc(displayValue(value,definition)):null;
  const number=text===null?numberMarkup(value,definition):
    `<span class="display-number" aria-label="${text} ${profileBoardUnit(definition)}">${text}</span>`;
  return `<span title="${raw}">${number}</span>${exact?`<small>공표값 ${raw}</small>`:""}`;
}
function profileBoardPeriodX(index,count,width=570){
  const left=width===570?94:80,span=width===570?448:width-left-30;
  return left+(count===1?span/2:span*index/(count-1));
}
function profileBoardDomain(data,includeZero,unitKind){
  let lower=Math.min(...data),upper=Math.max(...data);
  if(includeZero){lower=Math.min(0,lower);upper=Math.max(0,upper)}
  const flat=lower===upper;
  const padding=flat?(Math.abs(lower)*.05||(unitKind==="MONEY"?1000000:1)):(upper-lower)*.07;
  const target=(upper-lower+2*padding)/4;
  const power=10**Math.floor(Math.log10(target));
  const step=[1,2,2.5,5,10].find(factor=>factor*power>=target)*power;
  const first=Math.floor((includeZero&&lower===0&&!flat?0:lower-padding)/step);
  const last=Math.ceil((includeZero&&upper===0&&!flat?0:upper+padding)/step);
  const ticks=Array.from({length:last-first+1},(_,index)=>(first+index)*step);
  return {lower:ticks[0],upper:ticks.at(-1),ticks,step};
}
function profileBoardTick(value,_step,definition){
  return displayValue(String(value),definition);
}
function profileBoardPlot({periods,series,definition,label,active=null,interactive=false,includeZero=false,type="LINE",showPeriods=true,width=570,height=null}){
  const data=series.flatMap(line=>line.points.map(point=>point?.value==null?NaN:Number(point.value))).filter(Number.isFinite);
  if(!data.length)return '<div class="board-context" role="status" tabindex="0" hidden></div><p class="board-empty">이 범위에 표시할 값이 없습니다.</p>';
  const columns=type==="COLUMN",domain=profileBoardDomain(data,columns||includeZero,definition.unit_kind);
  const plotHeight=height??(showPeriods?154:134),bottom=plotHeight-(showPeriods?(width<500?32:28):8),left=width===570?88:74,right=width-18;
  const x=index=>profileBoardPeriodX(index,periods.length,width);
  const y=value=>bottom-(value-domain.lower)*(bottom-16)/(domain.upper-domain.lower);
  const tickLabels=new Set();
  const grid=domain.ticks.map(value=>{
    const label=profileBoardTick(value,domain.step,definition),visible=!tickLabels.has(label);
    tickLabels.add(label);
    return `<line class="board-grid${value===0?" board-zero":""}" x1="${left}" x2="${right}" y1="${y(value)}" y2="${y(value)}"/>${visible?`<text class="board-y" x="${left-6}" y="${y(value)+4}">${esc(label)}</text>`:""}`;
  }).join("");
  const paths=series.map(line=>{
    const [color,dash]=PROFILE_BOARD_STYLES[line.color];
    const points=line.points.map((point,index)=>point?.value!=null&&Number.isFinite(Number(point.value))?
      {x:x(index),y:y(Number(point.value)),...point}:null);
    const segments=type==="LINE"?points.slice(1).map((point,index)=>{
      const previous=points[index];
      return point&&previous&&point.connect?`<line class="board-line" x1="${previous.x}" y1="${previous.y}" x2="${point.x}" y2="${point.y}"/>`:"";
    }).join(""):"";
    const marks=points.map((point,index)=>{
      if(!point)return "";
      const hit=interactive?`data-board-period="${index}"`:"";
      const title=`<title>${esc(line.label)} · ${esc(periods[index].label)} · ${esc(profileBoardExact(point.value,definition))}${point.basis?` · 분모 ${esc(point.basis)}`:""}</title>`;
      if(!columns)return `<circle class="board-point" ${hit} cx="${point.x}" cy="${point.y}" r="4">${title}</circle>`;
      const zero=y(0),width=22;
      if(point.y===zero)return `<line class="board-column-zero" ${hit} x1="${point.x-width/2}" x2="${point.x+width/2}" y1="${zero}" y2="${zero}">${title}</line>`;
      return `<rect class="board-column ${point.y<zero?"board-column-positive":"board-column-negative"}" ${hit} x="${point.x-width/2}" y="${Math.min(point.y,zero)}" width="${width}" height="${Math.abs(point.y-zero)}">${title}</rect>`;
    }).join("");
    return `<g data-board-item="${esc(line.id||line.label)}" stroke="${color}" stroke-dasharray="${dash}">${segments}${marks}</g>`;
  }).join("");
  const labels=periods.map((period,index)=>{
    const label=period.short||period.label,quarter=width<500&&label.match(/^(?:20)?(\d{2})Q([1-4])$/u);
    return `<text class="board-x" x="${x(index)}" y="${plotHeight-(quarter?16:8)}">${quarter?`<tspan x="${x(index)}">${quarter[1]}</tspan><tspan x="${x(index)}" dy="11">Q${quarter[2]}</tspan>`:esc(label)}</text>`;
  }).join("");
  const marker=active==null?"":`<line class="board-active-period" x1="${x(active)}" x2="${x(active)}" y1="12" y2="${bottom+1}"/>`;
  const hits=interactive?periods.map((_,index)=>{
    const hitWidth=periods.length===1?right-left:(right-left)/(periods.length-1);
    return `<rect class="board-period-hit" data-board-period="${index}" x="${Math.max(left,x(index)-hitWidth/2)}" y="0" width="${Math.min(right,x(index)+hitWidth/2)-Math.max(left,x(index)-hitWidth/2)}" height="${plotHeight}"/>`;
  }).join(""):"";
  const precisionNote=tickLabels.size<domain.ticks.length?'<span title="같은 반올림 눈금은 한 번 표시합니다. 정확한 값은 근거 표에서 확인하세요."> · 반올림 눈금</span>':"";
  const axisNote=`<p class="board-axis-note">${columns?"0 기준":domain.lower>0||domain.upper<0?"자동 범위 · 0 생략":"0 포함"}${precisionNote}</p>`;
  const chartType=columns?"세로 막대":type==="DOT"?"점":"선";
  return `${axisNote}<div class="board-context" role="status" tabindex="0" hidden></div><div class="board-plot-canvas" tabindex="0" role="region" aria-label="${esc(label)} ${chartType} 차트 · 좌우 키로 기간 선택, Enter 또는 Space 고정, Esc 해제"><svg class="${width===570&&height===null?"":"board-adaptive"}" viewBox="0 0 ${width} ${plotHeight}" role="img" aria-label="${esc(label)} · ${chartType} · ${esc(profileBoardUnit(definition))}">${grid}${marker}${hits}${paths}${showPeriods?labels:""}</svg></div>`;
}

function profileBoardContextLine(label,period,value,definition,reason,detail=""){
  return `<strong>${esc(label)}</strong><span>${esc(period)} · ${profileBoardValue(value,definition,reason)} ${esc(profileBoardUnit(definition))}</span>${value==null?`<small>${esc(reason)}</small>`:""}${detail?`<small>${esc(detail)}</small>`:""}`;
}
function bindProfileBoardPeriod(host,selectPeriod,activePeriod,interaction={}){
  let pinned=false,item=null,context=null,key=null,order=null,anchor=null,suppressFocus=false;
  const clear=()=>{
    pinned=false;item=null;context=null;anchor=null;
    host.removeAttribute?.("data-board-pinned");
    host.querySelectorAll(".board-context").forEach(node=>{node.hidden=true;node.innerHTML=""});
    host.querySelectorAll(".board-item-active").forEach(node=>node.classList.remove("board-item-active"));
  };
  const synchronize=()=>{
    const current=interaction.key?.(),selection=interaction.order?.();
    if(current!==key||selection!==order){clear();key=current;order=selection}
    if(interaction.valid&&!interaction.valid()){clear();return false}
    return true;
  };
  const containerFor=location=>[...host.querySelectorAll("[data-board-mode]")].find(node=>{
    if(node.dataset.boardMode!==location.mode||node.closest?.("[hidden]"))return false;
    const card=node.closest?.("[data-financial-card]");
    const comparison=node.closest?.("[data-comparison-board-metric]");
    return (!card||card.dataset.financialCard===location.item)&&(!comparison||comparison.dataset.comparisonBoardMetric===location.item?.split("|")[0]);
  });
  const present=(location,target)=>{
    const container=target||containerFor(location);
    context=container?.querySelector(".board-context");
    const markup=interaction.describe?.(location.item,location.index,location.mode);
    host.querySelectorAll(".board-context").forEach(node=>{node.hidden=node!==context});
    host.querySelectorAll("[data-board-item]").forEach(node=>node.classList.toggle("board-item-active",Boolean(location.item)&&node.dataset.boardItem===location.item));
    if(!context||!markup)return false;
    const html=markup+'<small class="board-context-hint">클릭 또는 Enter/Space로 고정 · Esc 해제</small><button type="button" class="quiet board-context-clear" data-board-clear>설명 닫기 · Esc</button>';
    if(context.innerHTML!==html)context.innerHTML=html;
    context.hidden=false;return true;
  };
  host.profileBoardInteraction={clear,
    beforeRender(root){
      synchronize();
      const active=document.activeElement;
      if(!active||!root.contains?.(active))return null;
      const canvas=active.closest?.(".board-plot-canvas"),legend=active.closest?.("button[data-board-item]"),close=active.closest?.("[data-board-clear]");
      if(!canvas&&!legend&&!close)return null;
      return {focus:{kind:legend?"legend":close?"close":"canvas",item:legend?.dataset.boardItem||active.closest?.("[data-financial-card]")?.dataset.financialCard||anchor?.item||null,
        mode:active.closest?.("[data-board-mode]")?.dataset.boardMode||anchor?.mode}};
    },
    afterRender(snapshot){
      if(!synchronize())return;
      if(pinned&&anchor){
        if(anchor.index<0||anchor.index>=(interaction.count?.()||0)||interaction.items&&!interaction.items().includes(anchor.item)&&anchor.item!==null){clear()}
        else {selectPeriod(anchor.index,true);if(!present(anchor))clear()}
      }else {context=null;item=null;host.querySelectorAll(".board-context").forEach(node=>{node.hidden=true})}
      const focus=snapshot?.focus,container=focus&&containerFor(focus);
      const target=focus?.kind==="legend"?[...container?.querySelectorAll("button[data-board-item]")||[]].find(node=>node.dataset.boardItem===focus.item):
        focus?.kind==="close"?container?.querySelector("[data-board-clear]"):container?.querySelector(".board-plot-canvas");
      suppressFocus=true;target?.focus({preventScroll:true});suppressFocus=false;
    },
  };
  const choose=(event,force=false)=>{
    if(!synchronize()||pinned&&!force)return;
    const period=event.target.closest?.("[data-board-period]"),canvas=event.target.closest?.(".board-plot-canvas");
    const identity=event.target.closest?.("[data-board-item]");
    if(!period&&!canvas&&!identity)return;
    const index=period?Number(period.dataset.boardPeriod):activePeriod();if(index==null)return;
    item=identity?.dataset.boardItem||event.target.closest?.("[data-financial-card]")?.dataset.financialCard||interaction.defaultItem?.(event.target)||null;
    const mode=event.target.closest?.("[data-board-mode]")?.dataset.boardMode||interaction.defaultMode;
    anchor={item,index,mode};selectPeriod(index);
    const container=event.target.closest?.("[data-board-mode]")||canvas?.parentElement||event.target.closest?.(".financial-board-card,.revenue-board-plot");
    present(anchor,container||{querySelector:selector=>host.querySelector(selector)});
    return true;
  };
  host.addEventListener("pointerover",event=>{if(event.pointerType!=="touch")choose(event)});
  host.addEventListener("pointerleave",()=>{if(!pinned)clear()});
  host.addEventListener("focusin",event=>{if(!suppressFocus)choose(event)});
  host.addEventListener("focusout",event=>{if(!pinned&&!host.contains?.(event.relatedTarget))clear()});
  host.addEventListener("click",event=>{
    if(event.target.closest?.("[data-board-clear]")){
      const canvas=event.target.closest?.("[data-board-mode]")?.querySelector(".board-plot-canvas");
      clear();suppressFocus=true;canvas?.focus?.({preventScroll:true});suppressFocus=false;return;
    }
    if(!event.target.closest?.("[data-board-period],.board-plot-canvas,[data-board-item]"))return;
    if(choose(event,true)){
      pinned=true;host.setAttribute("data-board-pinned","true");
      event.target.closest?.(".board-plot-canvas")?.focus?.({preventScroll:true});
    }
  });
  host.addEventListener("keydown",event=>{
    if(event.key==="Escape"){
      if(pinned||item||context&&!context.hidden){event.preventDefault();event.stopPropagation()}
      const canvas=event.target.closest?.(".board-context")?event.target.closest?.("[data-board-mode]")?.querySelector(".board-plot-canvas"):null;
      clear();suppressFocus=true;canvas?.focus?.({preventScroll:true});suppressFocus=false;return;
    }
    const canvas=event.target.closest?.(".board-plot-canvas");if(!canvas)return;
    if(["ArrowLeft","ArrowRight","Home","End"].includes(event.key)){
      event.preventDefault();
      const count=interaction.count?.()||0,index=event.key==="Home"?0:event.key==="End"?count-1:Math.max(0,Math.min(count-1,activePeriod()+(event.key==="ArrowRight"?1:-1)));
      if(index>=0){selectPeriod(index,true);choose(event,true)}
    }else if(event.key==="Enter"||event.key===" "){
      event.preventDefault();if(choose(event,true)){pinned=true;host.setAttribute("data-board-pinned","true")}
    }
  });
  host.addEventListener("scroll",event=>{
    const canvas=event.target;if(!canvas.matches?.(".board-plot-canvas"))return;
    const offset=canvas.scrollLeft;
    for(const sibling of host.querySelectorAll(".board-plot-canvas")){
      if(sibling!==canvas&&sibling.clientWidth&&Math.abs(sibling.scrollLeft-offset)>1)sibling.scrollLeft=offset;
    }
  },true);
  window.addEventListener("resize",()=>{
    const index=activePeriod();if(index!=null&&!host.closest("[hidden]"))selectPeriod(index,true);
  });
}

function markProfileBoardPeriod(host,index,count){
  host.querySelectorAll(".board-active-period").forEach(marker=>{
    const x=profileBoardPeriodX(index,count,marker.ownerSVGElement.viewBox.baseVal.width);
    marker.setAttribute("x1",x);marker.setAttribute("x2",x);
    const canvas=marker.closest(".board-plot-canvas");
    const svg=marker.ownerSVGElement,position=x/svg.viewBox.baseVal.width*svg.clientWidth;
    if(position<canvas.scrollLeft||position>canvas.scrollLeft+canvas.clientWidth){
      canvas.scrollLeft=position-canvas.clientWidth/2;
    }
  });
}

const FINANCIAL_GROWTH_RULE="signed-prepared-financial-yoy-v1";
const FINANCIAL_GROWTH_BASE=new Map(
  ["","quarter_","ttm_"].flatMap(prefix=>["operating_income","cfo","standardized_fcf"].map(id=>[prefix+id,id]))
);
const financialGrowthCache=new Map();
let financialGrowthCapability;
const BOARD_RATE={label:"전년비",unit_kind:"PERCENT",unit:"%"};
const BOARD_PP={label:"전년 대비 변화",unit_kind:"PERCENT",unit:"pp"};
const BOARD_USD={unit_kind:"MONEY",unit:"USD"};
const BOARD_AXIS_OPTIONS='<option value="AUTO">자동 범위</option><option value="ZERO">0 포함</option>';

function financialComparisonEligible(definition){return !definition?.comparison_of&&["MONEY","PERCENT"].includes(definition?.unit_kind)}
function financialComparisonMetric(definition){return definition.unit_kind==="PERCENT"?BOARD_PP:BOARD_RATE}
function auxiliaryOwnerPayload(response,requested,dataset,expectedSource=null){
  if(response?.schema_version!=="screening-auxiliary-owner-response-v1"){
    if(dataset?.auxiliary_manifest_sha256||response?.auxiliary_owner)throw new Error("통합 자료의 공시 출처 증거를 확인할 수 없습니다.");
    return response;
  }
  const {request_scope:query,source_scope:source,owner_proof:proof,data}=response;
  const keys=["dataset_id","dataset_publication_id","financial_as_of","dataset_manifest_sha256"];
  if(!/^[0-9a-f]{64}$/u.test(dataset?.auxiliary_manifest_sha256||"")||!query||!source||!proof||!data||
      Object.keys(requested).some(key=>query[key]!==requested[key])||
      query.dataset_manifest_sha256!==dataset.auxiliary_manifest_sha256||
      proof.union_manifest_sha256!==dataset.auxiliary_manifest_sha256||proof.cik!==requested.cik||
      !/^[0-9a-f]{64}$/u.test(source.dataset_manifest_sha256||"")||
      proof.source_manifest_sha256!==source.dataset_manifest_sha256||source.financial_as_of!==requested.financial_as_of||
      data.cik!==requested.cik||keys.some(key=>data[key]!==source[key])||
      expectedSource&&keys.some(key=>source[key]!==expectedSource[key])){
    throw new Error("통합 자료와 원본 공시 발행물의 범위가 다릅니다.");
  }
  return {...data,auxiliary_owner:{request_scope:query,source_scope:source,owner_proof:proof}};
}

function requestFinancialGrowth(model){
  if(model.growth||!model.slots.length||!model.selection.order.some(id=>financialComparisonEligible(model.definitions.get(id))&&!financialProfileGrowth(id,model.definitions)))return;
  const scope={dataset_id:model.context.dataset,dataset_publication_id:model.context.publication,
    financial_as_of:model.context.financialAsOf,cik:model.profile.company.cik};
  if(Object.values(scope).some(value=>typeof value!=="string"||!value)){
    model.growth={error:"부모 자료의 발행 범위를 확인할 수 없습니다."};
    return;
  }
  model.growth={loading:true};
  financialGrowthCapability??=api("/api/financial-growth").catch(error=>{
    financialGrowthCapability=undefined;
    throw error;
  });
  financialGrowthCapability.then(capability=>{
    if(!ownsFinancialProfileBoard(model))return;
    const {cik,...dataset}=scope;
    const selected=explorerDataset();
    const ownerContext=(capability.owner_contexts||[]).find(context=>
      Object.keys(dataset).every(key=>dataset[key]===context.request_scope?.[key])&&
      context.request_scope.dataset_manifest_sha256===selected?.auxiliary_manifest_sha256&&
      context.available_ciks?.includes(cik));
    if(!capability.configured||(!ownerContext&&Object.keys(dataset).some(key=>dataset[key]!==capability[key]))){
      throw new Error("이 기업 발행물의 전년 비교 자료가 준비되지 않았습니다. 수준 값은 그대로 조회할 수 있습니다.");
    }
    const sourceContext=ownerContext?.source_scope||capability;
    const query=new URLSearchParams(scope).toString();
    let pending=financialGrowthCache.get(query);
    if(!pending){
      pending=api(`/api/financial-growth?${query}`).then(response=>{
        const data=auxiliaryOwnerPayload(response,scope,selected,ownerContext?.source_scope||null);
        const expectedScope=data.auxiliary_owner?{...data.auxiliary_owner.source_scope,cik}:scope;
        if(!((data.schema_version==="screening-financial-growth-v1"&&data.rule_version===FINANCIAL_GROWTH_RULE)||(data.schema_version==="screening-financial-growth-v2"&&data.rule_version==="catalog-prepared-financial-comparison-v2"))||data.period_end_convention!=="EXCLUSIVE"||
            Object.keys(scope).some(key=>expectedScope[key]!==data[key])||data.dataset_manifest_sha256!==sourceContext.dataset_manifest_sha256||
            !data.definitions||!data.series){
          throw new Error("전년 비교 발행물의 범위가 선택과 다릅니다.");
        }
        return data;
      }).catch(error=>{
        if(financialGrowthCache.get(query)===pending)financialGrowthCache.delete(query);
        throw error;
      });
      financialGrowthCache.set(query,pending);
      if(financialGrowthCache.size>16)financialGrowthCache.delete(financialGrowthCache.keys().next().value);
    }
    return pending;
  }).then(data=>{
    if(data&&ownsFinancialProfileBoard(model)){model.growth={data};renderFinancialProfileBoard(model)}
  },error=>{
    if(ownsFinancialProfileBoard(model)){model.growth={error:error.message};renderFinancialProfileBoard(model)}
  });
}
function financialGrowthReason(reason){
  return ({
    CURRENT_UNAVAILABLE:"이 기간의 값을 비교할 수 없습니다.",
    SUPPORTED_LINEAGE_NOT_PREPARED:"공표값은 있으나 비교에 필요한 준비된 입력 계보가 없습니다.",
    PRIOR_NOT_PREPARED:"전년 비교 기간이 준비되지 않았습니다.",
    PRIOR_UNAVAILABLE:"전년 비교값을 사용할 수 없습니다.",
    AMBIGUOUS_FISCAL_PERIOD:"회계기간의 관측값을 하나로 확인할 수 없습니다.",
    INCOMPATIBLE_SCOPE:"전년과 정의, 단위 또는 보고 기준을 맞출 수 없습니다.",
    INCOMPATIBLE_PERIOD:"전년과 실제 기간을 맞출 수 없습니다.",
    INCOMPATIBLE_SEMANTICS:"전년과 공시 항목의 의미를 맞출 수 없습니다.",
    INCOMPATIBLE_TTM_LINEAGE:"두 TTM의 연속 분기 또는 공시 기준을 확인할 수 없습니다.",
  })[reason]||"이 기간에 발행된 전년 비교가 없습니다.";
}
function financialGrowthStatus(id,status){
  const metric=FINANCIAL_GROWTH_BASE.get(id);
  const negative={operating_income:"영업손실",cfo:"영업현금 순유출",standardized_fcf:"음수 FCF 규모"}[metric]||"음수 규모";
  return ({
    POSITIVE_TURN:{operating_income:"흑자전환",cfo:"영업현금 순유입 전환",standardized_fcf:"FCF 양수 전환"}[metric]||"양수 전환",
    NEGATIVE_TURN:{operating_income:"적자전환",cfo:"영업현금 순유출 전환",standardized_fcf:"FCF 음수 전환"}[metric]||"음수 전환",
    NEGATIVE_MAGNITUDE_REDUCED:`${negative} 축소`,
    NEGATIVE_MAGNITUDE_EXPANDED:`${negative} 확대`,
    NEGATIVE_MAGNITUDE_UNCHANGED:`${negative} 유지`,
    ZERO_REACHED:"0 도달",ZERO_BASE:"전년 0 · 비율 없음",ZERO_UNCHANGED:"두 기간 모두 0",
  })[status]||"";
}
function financialGrowthPoints(model,definition,levels){
  const {data,error,loading}=model.growth||{};
  const declared=data?.definitions[definition.metric_id];
  const basis=definition.observation_basis==="TTM"?"TTM":model.context.basis==="ANNUAL"?"FY":"QTD_3M";
  const bound=declared?.basis===basis&&declared.definition_version===definition.definition_version;
  return model.slots.map((slot,index)=>{
    const row=bound?data.series[definition.metric_id]?.[slot.key]:null,level=levels[index];
    const reason=error||(loading?"전년 비교 자료를 불러오는 중입니다…":financialGrowthReason(row?.reason));
    if(!row||row.status==="UNAVAILABLE"||level.value==null)return {value:null,reason};
    const current=row.current,observationId=level.row?.metric_observation_id||level.row?.observation_id;
    if(!current||current.value==null||shiftDecimal(current.value,0)!==shiftDecimal(level.value,0)||
        observationId&&observationId!==current.observation_id||
        ["period_start","period_end","fiscal_year","fiscal_quarter"].some(key=>(current[key]??null)!==(level.row?.[key]??null))){
      return {value:null,reason:"전년 비교의 현재 관측, 금액 또는 실제 기간이 준비된 수준과 다릅니다."};
    }
    const status=financialGrowthStatus(definition.metric_id,row.status);
    return {value:declared.comparison_kind==="PERCENTAGE_POINT"?row.change_pp:row.yoy,reason:status||reason,connect:level.connect,evidence:row,status,definition,rule:data.rule_version,formula:declared.formulas?.change_pp?.expression};
  });
}
function financialGrowthEvidence(point,exact=false){
  const record=point.evidence;
  if(!record)return "";
  const status=point.status?`<span class="financial-growth-status" data-growth-status="${esc(record.status)}">${esc(point.status)}</span>`:"";
  const amount=(value,definition,unit)=>exact?esc(profileBoardExact(value,definition)):`${profileBoardValue(value,definition)} ${unit}`;
  const publishedMagnitude=record.negative_magnitude_change;
  const expanded=record.status==="NEGATIVE_MAGNITUDE_EXPANDED";
  const direction=expanded?"확대 규모":record.status==="NEGATIVE_MAGNITUDE_REDUCED"?"축소 규모":"음수 규모 변화";
  const magnitude=publishedMagnitude==null?"":exact?
    `<small>음수 규모 축소율 ${amount(publishedMagnitude,BOARD_RATE,"%")} · (전년 절댓값 − 현재 절댓값) ÷ 전년 절댓값 × 100</small>`:
    `<small>${direction} ${amount(expanded?publishedMagnitude.replace(/^-/u,""):publishedMagnitude,BOARD_RATE,"%")}</small>`;
  const percent=point.definition?.comparison_kind==="PERCENTAGE_POINT"||(!point.definition?.comparison_of&&point.definition?.unit_kind==="PERCENT");
  const delta=percent?"":`<small>금액 증감 ${amount(record.delta,BOARD_USD,"백만 USD")}</small>`;
  if(!exact)return status+magnitude+delta+(record.basis_assurance==="ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"?'<small>산술 비교 · 재작성 비교성 미검증</small>':"");
  const sourceDefinition=point.definition?.comparison_of?(percent?BOARD_RATE:BOARD_USD):point.definition||BOARD_USD;
  const evidence=(label,input)=>input?`<small>${label} ${esc(profileBoardExact(input.value,sourceDefinition))} · ${esc(actualPeriod(input))}<br>관측 ${esc(input.observation_id)}</small>`:`<small>${label} 관측 미준비</small>`;
  const assurance=record.basis_assurance==="ARITHMETIC_ONLY_NOT_RECAST_VALIDATED"?
    "산술 비교 · 재작성 기준 검증 없음":`선언 기준 ${record.basis_assurance?.replace(/^DECLARED_BASIS:/u,"")||"—"}`;
  const legs=record.ttm_input_ids?`<small>현재 분기 관측 ${esc(record.ttm_input_ids.current.join(", "))}<br>전년 분기 관측 ${esc(record.ttm_input_ids.prior.join(", "))}</small>`:"";
  const formula=percent?`<small>변화 공식: 현재 비율 − 전년 비율${point.formula?` · ${esc(point.formula)}`:""}</small>`:"";
  return status+magnitude+delta+formula+evidence("현재",record.current)+evidence("전년",record.prior)+legs+
    `<small>${esc(assurance)} · 규칙 ${esc(point.rule||FINANCIAL_GROWTH_RULE)}</small>`;
}

function financialGrowthPeriodStatuses(rates,slots,active){
  const statuses=rates.map((rate,index)=>rate.status?`<li><button type="button" class="quiet financial-growth-period"
    data-board-period="${index}" data-growth-status="${esc(rate.evidence.status)}" aria-pressed="${index===active}">
    <strong>${esc(slots[index].label)}</strong> ${esc(rate.status)}</button></li>`:"").join("");
  return statuses?`<ul class="financial-growth-periods" aria-label="기간별 전년 비교 상태">${statuses}</ul>`:"";
}

const PROFILE_GROWTH={"revenue":"revenue_yoy","quarter_revenue":"quarter_revenue_yoy"};
const PROFILE_BOARD_DEFAULTS={
  ANNUAL:["revenue","operating_income","cfo","standardized_fcf"],
  QUARTERLY:["quarter_revenue","quarter_operating_income","quarter_cfo","quarter_standardized_fcf"],
  TTM:["ttm_revenue","ttm_operating_income","ttm_cfo","ttm_standardized_fcf"],
};
function financialBoardGroups(definitions,defaults){
  const options=[...definitions].map(([id,definition])=>({id,label:definition.label}));
  const core=defaults.filter(id=>definitions.has(id));
  const groups=new Map([["CORE",{label:"핵심",options:options.filter(item=>core.includes(item.id)),selection:createProfileBoard(core)}]]);
  for(const category of ["GROWTH","PROFITABILITY","CASH_FLOW","FINANCIAL_STABILITY","OTHER_REPORTED"]){
    const members=options.filter(item=>definitions.get(item.id).category===category);
    groups.set(category,{label:categoryLabel(category),options:members,selection:createProfileBoard(members.slice(0,PROFILE_BOARD_LIMIT).map(item=>item.id))});
  }
  groups.set("CUSTOM",{label:"사용자 선택",options,selection:createProfileBoard(core)});
  return groups;
}
function activateFinancialBoardGroup(model,key){
  const group=model.groups.get(key);if(!group)return;
  model.group=key;model.selection=group.selection;
  $("#financial-board-group").value=key;
  $("#financial-board-group-label").textContent=`현재 그룹: ${group.label}`;
  renderProfileBoardSelection(financialProfileBoardHost,group.selection,group.options,()=>updateFinancialProfileBoard(model));
  updateFinancialProfileBoard(model);
}
function observeProfileBoardWidth(host,render,current){
  if(typeof ResizeObserver==="undefined")return;
  host.profileBoardObserver?.disconnect();
  let width=null,frame=0;
  host.profileBoardObserver=new ResizeObserver(entries=>{
    const next=Math.round(entries[0].contentRect.width);
    if(next===width||next<1)return;width=next;
    if(frame)cancelAnimationFrame(frame);
    frame=requestAnimationFrame(()=>{frame=0;if(current())render()});
  });
  host.profileBoardObserver.observe(host);
}
function financialBoardPlotWidth(host){
  const available=host.clientWidth||760,columns=Math.min(4,Math.max(1,Math.floor((available+12)/372)));
  return Math.max(320,Math.floor((available-12*(columns-1))/columns)-26);
}
let financialProfileBoardHost,financialProfileBoard=null;
function mountFinancialProfileBoard(overview){
  const section=document.createElement("section");
  section.className="financial-profile-board";
  section.innerHTML=`<h3>재무 비교 보드</h3><p class="muted">금액은 수준과 전년비, 백분율은 수준과 전년 대비 %p 변화를 비교합니다. 각 지표의 세로축은 독립적입니다.</p>
    ${PROFILE_BOARD_SELECTION}
    <div class="financial-board-controls">
      <label>지표 그룹<select id="financial-board-group"></select></label><span id="financial-board-group-label" class="sr-only"></span>
      <label>같이 볼 기간<select id="financial-board-period"></select></label>
      <label>수준 차트<select id="financial-board-chart-type"><option value="DOT">점</option><option value="LINE">선</option></select></label>
      <label>수준 세로축<select id="financial-board-y-scale">${BOARD_AXIS_OPTIONS}</select></label>
    </div>
    <div class="financial-board-panels"></div>`;
  $("#profile-summary").after(section);
  if(!$("#profile-summary-disclosure")){
    const summary=document.createElement("details");summary.id="profile-summary-disclosure";summary.className="profile-summary-disclosure";
    summary.innerHTML='<summary>주요 지표 값 보기</summary>';
    $("#profile-summary").before(summary);summary.append($("#profile-summary"));
  }
  const single=document.createElement("details");
  single.id="profile-single-trend";
  single.className="profile-board-picker";
  single.innerHTML="<summary>개별 지표의 기존 흐름과 기간표</summary>";
  const trend=overview.querySelector(".profile-trend");
  trend.before(single);single.append(trend);
  single.addEventListener("toggle",()=>{if(single.open&&S.profile&&!$("#company-profile").hidden)renderProfileTrend()});
  financialProfileBoardHost=section;
  $("#financial-board-group").onchange=event=>{
    if(ownsFinancialProfileBoard(financialProfileBoard))activateFinancialBoardGroup(financialProfileBoard,event.target.value);
  };
  observeProfileBoardWidth(section.querySelector(".financial-board-panels"),()=>renderFinancialProfileBoard(financialProfileBoard),()=>ownsFinancialProfileBoard(financialProfileBoard));
  $("#financial-board-chart-type").onchange=event=>{
    if(ownsFinancialProfileBoard(financialProfileBoard)){
      financialProfileBoard.chartType=event.target.value;
      renderFinancialProfileBoard(financialProfileBoard);
    }
  };
  $("#financial-board-y-scale").onchange=event=>{
    if(ownsFinancialProfileBoard(financialProfileBoard)){
      financialProfileBoard.includeZero=event.target.value==="ZERO";
      renderFinancialProfileBoard(financialProfileBoard);
    }
  };
  $("#financial-board-period").onchange=event=>updateFinancialBoardPeriod(financialProfileBoard,Number(event.target.value));
  bindProfileBoardPeriod(section,(index,force)=>updateFinancialBoardPeriod(financialProfileBoard,index,force),()=>financialProfileBoard?.active,{
    valid:()=>ownsFinancialProfileBoard(financialProfileBoard),key:()=>financialProfileBoard?`${financialProfileBoard.profile.company.cik}:${financialProfileBoard.key}:${financialProfileBoard.group}:${financialProfileBoard.selection.order.join(",")}`:null,
    count:()=>financialProfileBoard?.slots.length||0,describe:financialBoardContext,defaultMode:"level",items:()=>financialProfileBoard?.selection.order||[],
  });
}
function financialBoardContext(id,index,mode){
  const model=financialProfileBoard,definition=model?.definitions.get(id);if(!definition||!model.slots[index])return "";
  const levels=financialProfilePoints(model,definition),level=levels[index],published=financialProfileGrowth(id,model.definitions);
  const growth=published||financialComparisonMetric(definition),rate=published?financialProfilePoints(model,published)[index]:financialGrowthPoints(model,definition,levels)[index];
  const point=mode==="growth"?rate:level,metric=mode==="growth"?growth:definition;
  const reference=point.evidence?.current||point.row||level.row;
  const rationale=mode==="growth"?`${preparedChangeCaption(definition)} · ${["pp","PERCENTAGE_POINT"].includes(growth.unit)?"공표된 현재 비율 − 전년 비율":"발행된 비교 · 비교 불가 상태는 근거 표 확인"}`:"";
  const detail=[reference?actualPeriod(reference):"",rationale].filter(Boolean).join(" · ");
  return profileBoardContextLine(definition.label,model.slots[index].label,point.value,metric,point.reason,detail)+(mode==="growth"?financialGrowthEvidence(rate):"");
}
function financialProfileGrowth(id,definitions){
  const level=definitions.get(id);if(!level||level.comparison_of)return null;
  const registered=[...definitions.values()].filter(item=>item.comparison_of===id&&item.source_definition_version===level.definition_version&&
    item.comparison_kind===(level.unit_kind==="PERCENT"?"PERCENTAGE_POINT":"YOY")&&item.unit===(level.unit_kind==="PERCENT"?"PERCENTAGE_POINT":"PERCENT"));
  const definition=registered.length===1?registered[0]:registered.length?null:definitions.get(PROFILE_GROWTH[id]);
  return ["MONEY","PERCENT"].includes(level.unit_kind)&&definition?.unit_kind==="PERCENT"&&
    level.period_class===definition.period_class&&level.observation_basis===definition.observation_basis?definition:null;
}
function beginFinancialProfileBoard(){
  if(financialProfileBoardHost&&!financialProfileBoardHost.dataset.conditionActions){financialProfileBoardHost.dataset.conditionActions="true";financialProfileBoardHost.addEventListener("click",event=>{const button=event.target.closest?.("[data-add-published-condition]");if(button){try{addPublishedCondition(button.dataset.addPublishedCondition)}catch(error){toast(error.message)}}})}
  if(!financialProfileBoardHost)return;
  const profile=S.profile,basis=explorerBasis.profileBasis,dataset=explorerDataset();
  const definitions=new Map(profile.groups.flatMap(group=>group.metrics.map(({definition})=>[definition.metric_id,definition])));
  const defaults=PROFILE_BOARD_DEFAULTS[basis].filter(id=>definitions.has(id));
  const selection=createProfileBoard(defaults.length?defaults:[...definitions.keys()].slice(0,1));
  const annual=basis==="ANNUAL",latest=!annual&&latestExplorerPeriod();
  const end=annual?profile.selected_fiscal_year:latest?
    (profile.latestAnchor?periodCoordinate(profile.latestAnchor):null):explorerBasis.periods[basis];
  const context={basis,end,ends:latest?{[profile.company.cik]:end}:null,
    dataset:dataset.dataset_id,publication:dataset.publication_id,financialAsOf:profile.financial_as_of,
    spine:companyTrendSpine(latest),annualYears:profile.prepared_years||[],companies:[profile.company]};
  const slots=end==null?[]:companyTrendSlots(context,annual?[{preparedYears:profile.prepared_years||[]}]:[])
    .map(slot=>({...slot,short:annual?slot.label:slot.label.slice(2)}));
  const model={profile,selection,groups:financialBoardGroups(definitions,defaults),group:"CORE",definitions,context,slots,series:new Map(),active:Math.max(0,slots.length-1),key:explorerContextKey()};
  financialProfileBoard=model;
  $("#financial-board-y-scale").value="AUTO";
  $("#financial-board-chart-type").value="DOT";
  const select=$("#financial-board-period");
  select.innerHTML=slots.map((slot,index)=>`<option value="${index}">${esc(slot.label)}</option>`).join("");
  select.disabled=!slots.length;
  const groups=$("#financial-board-group");
  groups.innerHTML=[...model.groups].map(([key,group])=>`<option value="${key}" ${group.options.length?"":"disabled"}>${esc(group.label)}</option>`).join("");
  activateFinancialBoardGroup(model,model.groups.get("CORE").options.length?"CORE":"CUSTOM");
}
function ownsFinancialProfileBoard(model){
  return model&&financialProfileBoard===model&&model.profile===S.profile&&
    model.key===explorerContextKey()&&!$("#company-profile").hidden;
}
function updateFinancialProfileBoard(model){
  if(!ownsFinancialProfileBoard(model))return;
  const {profile,selection,definitions,context,series}=model;
  for(const id of selection.order){
    const growth=financialProfileGrowth(id,definitions);
    for(const definition of [definitions.get(id),growth].filter(Boolean)){
      const key=definition.metric_id;
      if(series.has(key))continue;
      if(context.basis==="ANNUAL"){
        series.set(key,{rows:profile.series?.[key]||[]});
        continue;
      }
      if(!model.slots.length){series.set(key,{rows:[]});continue}
      series.set(key,{loading:true});
      cachedCompanyTrendSeries({...context,definition},profile.company.cik).then(result=>{
        if(ownsFinancialProfileBoard(model)){series.set(key,result);renderFinancialProfileBoard(model)}
      },error=>{
        if(ownsFinancialProfileBoard(model)){series.set(key,{error:error.message});renderFinancialProfileBoard(model)}
      });
    }
  }
  requestFinancialGrowth(model);
  renderFinancialProfileBoard(model);
}
function financialProfilePoints(model,definition){
  const record=model.series.get(definition.metric_id);
  const annual=model.context.basis==="ANNUAL";
  const rows=new Map((record?.rows||[]).map(row=>[annual?row.fiscal_year:periodCoordinate(row),row]));
  return model.slots.map((slot,index)=>{
    const row=rows.get(slot.key),previous=model.slots[index-1];
    return {value:row?.value??null,connect:previous?.ordinal===slot.ordinal-1,
      reason:record?.error||row?.reason_labels?.[0]||businessReason(row?.unavailable_reason||row?.reason)||"이 기간에 준비된 값이 없습니다.",row,
      ...(row?.comparison_evidence?{evidence:row.comparison_evidence,status:financialGrowthStatus(definition.comparison_of||definition.metric_id,row.comparison_evidence.status),definition,
        rule:definition.comparison_engine,formula:definition.formula}: {})};
  });
}
function renderFinancialProfileBoard(model){
  const host=financialProfileBoardHost.querySelector(".financial-board-panels");
  const restore=financialProfileBoardHost.profileBoardInteraction?.beforeRender(host);
  // Keep each open evidence disclosure through late arrivals and order changes.
  const expanded=new Set([...host.querySelectorAll("details[open]")].map(node=>node.dataset.financialDetails));
  const active=document.activeElement,card=active?.closest?.("[data-financial-card]");
  const focused=card?.dataset.financialCard;
  const plotIndex=card?[...card.querySelectorAll(".board-plot-canvas")].indexOf(active):-1;
  host.innerHTML=model.selection.order.map(id=>{
    const definition=model.definitions.get(id),published=financialProfileGrowth(id,model.definitions),color=model.selection.colors.get(id);
    const adjunct=financialComparisonEligible(definition)&&!published,growth=published||(adjunct?financialComparisonMetric(definition):null);
    const levels=financialProfilePoints(model,definition);
    const rates=published?financialProfilePoints(model,published):adjunct?financialGrowthPoints(model,definition,levels):null;
    const chart=(metric,points,label,type,record=model.series.get(metric.metric_id))=>{
      const content=record?.loading?'<p class="board-empty" role="status">자료를 불러오는 중입니다…</p>':
        record?.error?`<p class="board-empty explorer-error">${esc(record.error)}</p>`:
        profileBoardPlot({periods:model.slots,series:[{id,label:metric.label,color,points}],definition:metric,label,type,active:model.active,interactive:true,includeZero:model.includeZero,showPeriods:label!=="수준"||!growth,width:financialBoardPlotWidth(host),height:label==="수준"?142:108});
      return `<div class="financial-board-plot" data-board-mode="${label==="수준"?"level":"growth"}"><h5>${label==="수준"&&metric.unit_kind==="MONEY"?"금액":label==="수준"?"수준":esc(preparedChangeCaption(definition).replace(/\s*\(%p?\)$/u,""))} · ${esc(profileBoardUnit(metric))}${label==="수준"?` · ${esc(metricPresentation(definition).period)}`:""}</h5>${content}</div>`;
    };
    return `<article class="financial-board-card" data-financial-card="${esc(id)}"><h4 data-board-item="${esc(id)}" title="${esc(definition.label)}" aria-label="${esc(definition.label)}">${esc(financialMetricCaption(definition))}</h4>
      ${chart(definition,levels,"수준",model.chartType||"DOT")}
      ${growth?chart(growth,rates,["pp","PERCENTAGE_POINT"].includes(growth.unit)?"전년 대비 변화":"전년비","COLUMN",adjunct?model.growth:undefined):`<div class="financial-board-plot" data-board-mode="growth"><p class="board-empty">${definition.unit_kind==="MONEY"?"이 지표에 대응하는 전년비가 발행되지 않았습니다.":"이 지표는 수준으로 표시합니다. 대응하는 전년비가 발행되지 않았습니다."}</p></div>`}
      <div class="metric-condition-capability"><small>${esc(metricPresentation(definition).source)}</small>${published?`${conditionActionMarkup(published)} <small>공표된 ${esc(published.label)} · 조건 등록 지표</small>`:adjunct?'<small>상세 비교 전용 · 조건 미지원</small>':""}</div>
      <p class="financial-board-readout" data-financial-readout="${esc(id)}"></p>
      ${growth?financialGrowthPeriodStatuses(rates,model.slots,model.active):""}
      <details data-financial-details="${esc(id)}" ${expanded.has(id)?"open":""}><summary>기간별 값과 실제 기간</summary>
        <div class="table-wrap" tabindex="0" role="region" aria-label="${esc(definition.label)} 기간별 값">
          <table class="series-table"><thead><tr><th scope="col">기간</th><th scope="col">수준 · ${esc(profileBoardUnit(definition))}</th>${growth?`<th scope="col">${esc(preparedChangeCaption(definition))}</th>`:""}</tr></thead>
          <tbody>${model.slots.map((slot,index)=>{
            const level=levels[index],rate=rates?.[index],caption=point=>point?.row?`<small>${esc(actualPeriod(point.row))}${point.row.fiscal_quarter?` · ${esc(fiscalLabel(point.row))}`:""}${point.row.continuity_evidence?` · 전년 비교 공시 ${esc(compactFinancialDate(point.row.continuity_evidence.proof_available_on))}`:""}</small>`:"";
            return `<tr><th scope="row">${esc(slot.label)}</th><td>${profileBoardValue(level.value,definition,level.reason,true)}${caption(level)}</td>${growth?`<td>${profileBoardValue(rate.value,growth,rate.reason,true)}${caption(rate)}${rate.evidence?financialGrowthEvidence(rate,true):""}</td>`:""}</tr>`;
          }).join("")}</tbody></table></div>
      </details></article>`;
  }).join("")||'<p class="board-empty">비교할 재무 지표를 선택해 주세요.</p>';
  if(focused&&!restore?.focus){
    const current=[...host.querySelectorAll("[data-financial-card]")].find(node=>node.dataset.financialCard===focused);
    const target=plotIndex<0?current?.querySelector("summary"):current?.querySelectorAll(".board-plot-canvas")[plotIndex];
    target?.focus({preventScroll:true});
  }
  updateFinancialBoardPeriod(model,model.active,true);
  financialProfileBoardHost.profileBoardInteraction?.afterRender(restore);
}
function updateFinancialBoardPeriod(model,index,force=false){
  if(!model?.slots[index]||!force&&index===model.active)return;
  model.active=index;
  $("#financial-board-period").value=String(index);
  markProfileBoardPeriod(financialProfileBoardHost,index,model.slots.length);
  for(const button of financialProfileBoardHost.querySelectorAll(".financial-growth-period")){
    button.setAttribute("aria-pressed",String(Number(button.dataset.boardPeriod)===index));
  }
  for(const target of financialProfileBoardHost.querySelectorAll("[data-financial-readout]")){
    const id=target.dataset.financialReadout,definition=model.definitions.get(id),published=financialProfileGrowth(id,model.definitions);
    const levels=financialProfilePoints(model,definition),level=levels[index],adjunct=financialComparisonEligible(definition)&&!published;
    const rate=published?financialProfilePoints(model,published)[index]:adjunct?financialGrowthPoints(model,definition,levels)[index]:null;
    const growth=published||financialComparisonMetric(definition);
    target.innerHTML=`<strong>${esc(model.slots[index].label)}</strong>
      · 수준 ${profileBoardValue(level.value,definition,level.reason)} ${esc(profileBoardUnit(definition))}
      ${rate?` · ${esc(preparedChangeCaption(definition).replace(/\s*\(%p?\)$/u,""))} ${profileBoardValue(rate.value,growth,rate.reason)} ${esc(profileBoardUnit(growth))}${rate?.evidence?financialGrowthEvidence(rate):""}`:""}
      ${level.value==null?`<small>${esc(level.reason)}</small>`:""}
      ${rate?.value==null&&!rate?.status?`<small>${esc(rate.reason)}</small>`:""}
      ${level.row?`<small>${financialPeriodDisplay(level.row)}</small>`:""}`;
  }
}

function mountExplorerLayout(){
  const profile=$("#company-profile"),nav=$(".task-nav");
  document.body.classList.add("explorer-v2");
  nav.insertAdjacentHTML("afterbegin",'<div class="workbench-brand"><strong>SEC XBRL</strong><span>INVESTOR WORKBENCH</span></div>');
  for(const [view,label] of [["explorer","기업 탐색"],["history","저장 이력"]]){
    $(`[data-view="${view}"]`).textContent=label;
  }
  $("#explorer-title").textContent="기업 탐색";
  $(".explorer-matrix").after(profile);
  profile.querySelector(".aside-head .step").textContent="기업 재무 프로필";
  $("#close-profile").textContent="상세 닫기";

  const overview=document.createElement("div");
  overview.id="profile-overview";
  overview.append($("#profile-summary"),$("#profile-description"),profile.querySelector(".profile-trend"),$("#profile-all-metrics"));
  $("#profile-intro").after(overview);
  mountFinancialProfileBoard(overview);

  const actions=document.createElement("div");
  actions.className="profile-view-actions";
  actions.setAttribute("role","group");
  actions.setAttribute("aria-label","기업 상세 보기");
  actions.innerHTML=`<button id="profile-show-overview" type="button" class="quiet" aria-controls="profile-overview" aria-pressed="true">재무 요약</button>
    <button id="profile-show-revenue" type="button" class="quiet" aria-controls="profile-revenue-breakdowns" aria-pressed="false">매출 구성과 흐름</button>`;
  $("#profile-intro").after(actions);
  $("#profile-show-overview").onclick=()=>showProfileSection(false);
  $("#profile-show-revenue").onclick=()=>showProfileSection(true);
}
function showProfileSection(revenue){
  $("#profile-overview").hidden=revenue;
  $("#profile-revenue-breakdowns").hidden=!revenue;
  $("#profile-show-overview").setAttribute("aria-pressed",String(!revenue));
  $("#profile-show-revenue").setAttribute("aria-pressed",String(revenue));
  if(revenue)loadRevenueBreakdowns();
  else if(ownsFinancialProfileBoard(financialProfileBoard))updateFinancialBoardPeriod(financialProfileBoard,financialProfileBoard.active,true);
}
function bindExplorer(){
  mountExplorerLayout();
  bindAnnualExplorer();explorerBasis.annualPresetLabels=Object.fromEntries([...$("#explorer-preset").options].map(option=>[option.value,option.textContent]));const tools=$(".explorer-tools"),basis=document.createElement("label"),period=document.createElement("label"),notice=document.createElement("p");
  basis.innerHTML='재무 빈도<select id="explorer-basis"><option value="ANNUAL">연간</option><option value="QUARTERLY" disabled>분기</option><option value="TTM" disabled>TTM</option></select>';tools.querySelector("label").after(basis);
  period.innerHTML='재무 기간<select id="explorer-quarter"></select>';period.hidden=true;$("#explorer-year").closest("label").after(period);
  $(".explorer-view .section-head p").textContent="기업별 실제 재무기간과 지표를 비교하고 공시 근거를 확인하세요.";
  const yearLabel=$("#explorer-year").closest("label");
  yearLabel.firstChild.textContent="재무 기간";
  const display=document.createElement("details");
  display.className="explorer-display workflow-disclosure";
  display.innerHTML='<summary>표시·정렬</summary><div class="explorer-display-fields"></div>';
  tools.append(display);
  display.lastElementChild.append(...["#explorer-preset","#explorer-sort","#explorer-direction"].map(id=>$(id).closest("label")));
  notice.id="explorer-message";notice.className="explorer-message";notice.setAttribute("role","status");notice.setAttribute("aria-live","polite");notice.hidden=true;tools.after(notice);
  $("#explorer-basis").onchange=()=>switchExplorerBasis().catch(error=>explorerNotice(error.message,true));
  $("#explorer-quarter").onchange=()=>{explorerBasis.periods[explorerBasis.basis]=$("#explorer-quarter").value;invalidateExplorerDetails();loadExplorer()};
  $("#explorer-year").onchange=async()=>{invalidateExplorerDetails();explorerBasis.latestAnnual=$("#explorer-year").value==="LATEST";if(!explorerBasis.latestAnnual)S.explorerYear=Number($("#explorer-year").value);await loadExplorer(explorerBasis.latestAnnual?null:S.explorerYear);await loadLibrary()};
  $("#explorer-query").oninput=()=>loadExplorer();$("#explorer-preset").onchange=()=>{updateExplorerSort();loadExplorer()};$("#explorer-sort").onchange=()=>loadExplorer();$("#explorer-direction").onchange=()=>loadExplorer();
  $("#compare-selected").onclick=()=>{try{openComparison()}catch(error){explorerNotice(error.message,true)}};
  $("#run-comparison").onclick=()=>renderComparison().catch(error=>{$("#comparison-result").innerHTML=`<p class="message error">${esc(error.message)}</p>`});
  tools.addEventListener("change",event=>{if(event.target.id!=="explorer-basis")explorerBasis.views[explorerBasis.basis]=explorerViewState()});
  mountExplorerSelection();
  mountRevenueBreakdowns();
  ensureExplorerInventory();
  mountDesktopExplorer();
  mountComparisonMetricPicker();
}

const revenueBreakdowns={token:0,context:null,data:null,boards:new Map(),board:null};
const REVENUE_MONEY={unit_kind:"MONEY",unit:"USD"},REVENUE_PERCENT={unit_kind:"PERCENT",unit:"PERCENT"};

function mountRevenueBreakdowns(){
  const panel=document.createElement("section");
  panel.id="profile-revenue-breakdowns";
  panel.hidden=true;
  panel.setAttribute("aria-labelledby","revenue-breakdown-title");
  panel.className="profile-revenue-breakdowns";
  panel.innerHTML=`<h3 id="revenue-breakdown-title">매출 구성과 흐름</h3>
    <p id="revenue-breakdown-status" class="muted" role="status"></p>
    <div id="revenue-breakdown-content" hidden>
      <div class="revenue-breakdown-controls">
        <label>재무 빈도<select id="revenue-breakdown-frequency"><option value="annual">연간</option><option value="quarterly">분기</option></select></label>
        <label>구성 구분<select id="revenue-breakdown-kind"><option value="segments">사업부문</option><option value="products">제품·서비스</option><option value="geography">지역</option></select></label>
        <label>표의 회계기간<select id="revenue-breakdown-period"></select></label>
        <a class="revenue-board-jump" href="#revenue-breakdown-trend-title">항목별 추이로 이동 ↓</a>
      </div>
      <div class="revenue-breakdown-layout">
        <div class="revenue-breakdown-worksheet">
          <div class="table-wrap" id="revenue-breakdown-table" role="region" aria-label="매출 구성표" tabindex="0"></div>
          <p class="muted">비중은 연결 매출 또는 해당 부문 소계를 기준으로 계산합니다. 전년비는 같은 공시의 전년 비교값을 사용하므로 추이의 전년 금액과 다를 수 있습니다.</p>
        </div>
        <section class="revenue-breakdown-trend" aria-labelledby="revenue-breakdown-trend-title">
          <h4 id="revenue-breakdown-trend-title" tabindex="-1">항목별 추이</h4>
          <div class="revenue-board-grid">
          <div class="revenue-board-options">
          ${PROFILE_BOARD_SELECTION}
          <div class="revenue-board-controls">
            <label>같이 볼 회계기간<select id="revenue-board-period"></select></label>
            <label>세로축<select id="revenue-board-y-scale">${BOARD_AXIS_OPTIONS}</select></label>
            <label class="revenue-board-check"><input type="checkbox" id="revenue-board-share-toggle"> 비중 보기</label>
          </div>
          <div id="revenue-board-readout" class="revenue-board-readout"></div>
          </div>
          <div class="revenue-board-panels">
          <div class="revenue-board-plot"><h5>매출 금액 · 백만 USD</h5><div id="revenue-breakdown-chart"></div></div>
          <div class="revenue-board-plot"><h5>같은 공시 전년비 · %</h5><div id="revenue-breakdown-growth"></div></div>
          <p class="muted">전년비의 비교값은 같은 공시에서 가져옵니다. 추이의 전년 금액과 다를 수 있습니다.</p>
          <div id="revenue-share-panel" class="revenue-board-plot" hidden>
            <h5>항목별 비중 · %</h5><div id="revenue-breakdown-share"></div>
            <p class="muted">항목마다 분모를 확인하세요. 항목 비중은 서로 겹칠 수 있으며 합계를 표시하지 않습니다.</p>
          </div>
          </div>
          </div>
          <details id="revenue-board-evidence" class="profile-board-picker">
            <summary>선택 항목의 전체 기간 값</summary>
            <div id="revenue-board-values" class="table-wrap" tabindex="0" role="region" aria-label="선택 항목의 전체 기간 값"></div>
          </details>
          <p class="muted">누락, 공시 기준 변경, 비중 분모 변경 구간에서 선이 끊깁니다.</p>
        </section>
      </div>
      <p class="revenue-breakdown-note">연결 매출과 부문 소계는 각각 준비된 값입니다. 구성 항목은 서로 겹칠 수 있습니다. 확인 가능한 기준값이 없으면 —로 표시합니다.</p>
    </div>`;
  $("#profile-overview").after(panel);
  $("#revenue-breakdown-frequency").onchange=()=>renderRevenueBreakdowns();
  $("#revenue-breakdown-kind").onchange=()=>renderRevenueBreakdowns(true);
  $("#revenue-breakdown-period").onchange=()=>renderRevenueBreakdownTable();
  mountRevenueBoardControls();
  $(".revenue-board-panels").after($("#revenue-board-readout"));
}
function resetRevenueBreakdowns(){
  const panel=$("#profile-revenue-breakdowns");
  if(!panel)return;
  revenueBreakdowns.token++;
  revenueBreakdowns.context=null;
  revenueBreakdowns.data=null;
  revenueBreakdowns.boards.clear();revenueBreakdowns.board=null;
  if($("#profile-show-overview"))showProfileSection(false);
  $("#revenue-breakdown-status").textContent="";
  $("#revenue-breakdown-content").hidden=true;
}
async function loadRevenueBreakdowns(){
  const panel=$("#profile-revenue-breakdowns"),profile=S.profile,dataset=explorerDataset();
  if(!panel||panel.hidden||!profile||!dataset)return;
  const status=$("#revenue-breakdown-status"),cik=profile.company.cik;
  if(!dataset.publication_id||!comparisonDate(profile.financial_as_of)){
    status.textContent="선택한 자료 발행물과 재무 기준일을 확인할 수 없습니다.";
    return;
  }
  if(revenueBreakdowns.context?.profile===profile&&revenueBreakdowns.data){
    updateRevenueBoardPeriod(revenueBreakdowns.board?.active,true);
    return;
  }
  const context={profile,key:explorerContextKey(),token:++revenueBreakdowns.token};
  revenueBreakdowns.context=context;
  const scope={dataset_id:dataset.dataset_id,dataset_publication_id:dataset.publication_id,financial_as_of:profile.financial_as_of,cik};
  const current=()=>context.token===revenueBreakdowns.token&&context.profile===S.profile&&context.key===explorerContextKey()&&!panel.hidden;
  status.textContent="매출 구성 자료를 불러오는 중입니다…";
  try{
    const data=auxiliaryOwnerPayload(await api(`/api/revenue-breakdowns?${new URLSearchParams(scope)}`),scope,dataset);
    if(!current())return;
    const expectedScope=data.auxiliary_owner?{...data.auxiliary_owner.source_scope,cik}:scope;
    if(Object.keys(scope).some(key=>expectedScope[key]!==data[key])||data.schema_version!=="screening-revenue-breakdowns-v1"){
      throw new Error("선택한 발행물과 매출 구성 자료가 다릅니다.");
    }
    revenueBreakdowns.data=data;
    $("#revenue-breakdown-frequency").value=explorerBasis.profileBasis==="ANNUAL"?"annual":"quarterly";
    $("#revenue-breakdown-kind").value="segments";
    $("#revenue-breakdown-content").hidden=false;
    renderRevenueBreakdowns();
  }catch(error){
    if(current())status.textContent=error.message;
  }
}
function revenuePeriodLabel(period,frequency){
  return `FY${period.fiscal_year}${frequency==="quarterly"?" Q"+period.fiscal_quarter:""}`;
}
const REVENUE_VIEW_DEFAULTS=[{id:"segments",label:"사업부문"},{id:"products",label:"제품·서비스"},{id:"geography",label:"지역"}];
function revenueViewDescriptors(view){
  return Array.isArray(view?.views)&&view.views.length?view.views:REVENUE_VIEW_DEFAULTS;
}
function revenueView(){
  const frequency=$("#revenue-breakdown-frequency").value;
  const select=$("#revenue-breakdown-kind"),view=revenueBreakdowns.data?.[frequency];
  if(!view)return null;
  const descriptors=revenueViewDescriptors(view),previous=select.value;
  select.innerHTML=descriptors.map(item=>`<option value="${esc(item.id)}">${esc(item.label)}</option>`).join("");
  select.value=descriptors.some(item=>item.id===previous)?previous:descriptors[0].id;
  const kind=select.value;
  return {frequency,kind,periods:view.periods||[],rows:view.groups?.[kind]||[],segments:view.groups?.segments||[],totals:view.totals||[],productHierarchy:view.product_hierarchy||[],availability:view.availability?.[kind]||[]};
}
function renderRevenueBreakdowns(keepPeriod=false){
  const view=revenueView();
  if(!view)return;
  const {frequency,periods}=view;
  const periodSelect=$("#revenue-breakdown-period"),previous=periodSelect.value;
  periodSelect.innerHTML=periods.map((period,index)=>`<option value="${index}">${esc(revenuePeriodLabel(period,frequency))}</option>`).join("");
  periodSelect.disabled=!periods.length;
  if(periods.length)periodSelect.value=keepPeriod&&periods[Number(previous)]?previous:String(periods.length-1);
  $("#revenue-breakdown-status").textContent=periods.length?
    `재무 기준일 ${revenueBreakdowns.data.financial_as_of} · 최근 ${periods.length}개 ${frequency==="annual"?"회계연도":"회계분기"} · 백만 USD`:
    "이 발행물에는 준비된 회계기간이 없습니다.";
  renderRevenueBreakdownTable();
  configureRevenueBoard(view);
  renderRevenueBreakdownTrend();
}
function revenueSourceLinks(sources,cik){
  if(!/^\d{10}$/u.test(cik))return "";
  const unique=new Map(sources.filter(source=>/^\d{10}-\d{2}-\d{6}$/u.test(source.accession)).map(source=>[source.accession,source]));
  return [...unique.values()].map(source=>{
    const accession=source.accession,folder=accession.replaceAll("-","");
    return `<a href="https://www.sec.gov/Archives/edgar/data/${cik.replace(/^0+/u,"")}/${folder}/${accession}-index.html" target="_blank" rel="noopener noreferrer" title="${esc(accession)} · ${esc(source.filed_date||"미확인")}" aria-label="공시 ${esc(source.filed_date||"미확인")} · ${esc(accession)}">공시 ${esc(compactFinancialDate(source.filed_date))}</a>`;
  }).join(" ");
}
function revenueScopeLabel(scope){
  if(!scope)return "";
  return scope.split(":").at(-1).replace(/Member$/u,"").replace(/([a-z0-9])([A-Z])/gu,"$1 $2");
}
const REVENUE_GAP_LABELS={
  MAPPING_EPOCH_NOT_ACTIVE:"다른 공시 분류 기간",MAPPING_REVIEW_REQUIRED:"항목 연결 확인 필요",Q4_MAPPING_REVIEW_REQUIRED:"Q4 항목 연결 확인 필요",
  NO_SCOPED_OBSERVATION_IN_PREPARED_INPUT:"이 범위의 입력 자료 없음",NO_PREPARED_ROWS_FOR_VIEW:"준비된 보기 행 없음",
  UNSUPPORTED_DIMENSION_SCOPE:"추가 분류 확인 필요",Q4_MISSING_ANNUAL_INPUT:"Q4 연간 입력 없음",Q4_MISSING_YTD9_INPUT:"Q4 9개월 입력 없음",
  Q4_AMBIGUOUS_INPUTS:"Q4 입력 충돌",Q4_INPUT_SCOPE_OR_PERIOD_MISMATCH:"Q4 범위·기간 불일치",
  Q4_INPUT_QUALITY_OR_CONTINUITY_HELD:"Q4 품질·연속성 검토",Q4_INPUTS_OR_MAPPING_NOT_PREPARED:"Q4 범위 연결 미확인",Q4_SCOPE_NOT_CONNECTED:"Q4 범위 연결 미확인",
  COMPETING_PREPARED_SCOPE:"범위 충돌",PREPARED_OBSERVATION_HELD:"준비값 검토",SOURCE_NOT_PREPARED:"출처 미준비",
};
function revenueGapLabel(reason){return REVENUE_GAP_LABELS[reason]||"준비 입력 확인 필요"}
function revenueAvailability(view,index){
  const scope=view.availability?.[index],reasons=Object.entries(scope?.gap_counts||{});
  if(!reasons.length)return "";
  return `<details class="muted"><summary>빈 항목 사유 · 준비된 범위별 확인</summary><ul>${reasons.map(([reason,count])=>`<li>${esc(revenueGapLabel(reason))} · ${count}건</li>`).join("")}</ul><p>선택한 기간의 준비 행과 고정된 공시 입력 범위만 확인한 결과입니다. 공시 전체의 부재를 뜻하지 않습니다.</p></details>`;
}
function renderRevenueBreakdownTable(){
  const view=revenueView(),table=$("#revenue-breakdown-table");
  if(!view||!view.periods.length){table.textContent="";return}
  const index=Number($("#revenue-breakdown-period").value),period=view.periods[index];
  if(!period){table.textContent="";return}
  const entries=view.rows.map(row=>({row,cell:row.cells[index]}))
    .filter(({cell})=>cell&&(cell.value!=null||cell.reason==="COMPETING_PREPARED_SCOPE"));
  const caption=period.period_end?`${period.period_start} ~ ${inclusiveEnd(period.period_end)}`:"실제 기간을 확인할 수 없습니다.";
  const groups=new Map();
  for(const entry of entries){
    const scope=view.kind==="products"?entry.row.scope:null;
    if(!groups.has(scope))groups.set(scope,[]);
    groups.get(scope).push(entry);
  }
  const details=[...groups].map(([scope,items],scopeIndex)=>{
    const subtotal=scope?revenueSegmentSubtotal(view.segments,scope,index):null;
    const scopeHeadingId=`revenue-scope-heading-${scopeIndex}`;
    const heading=scope?`<tr class="revenue-subtotal" data-revenue-depth="0"><th scope="rowgroup" id="${scopeHeadingId}">부문 소계<small>${esc(revenueScopeLabel(scope))}</small></th>
      ${revenueBreakdownValueCells(subtotal,"이 기간에 확인된 부문 매출이 없습니다.","연결 매출")}</tr>`:"";
    const firstDepth=scope?1:0,scopeLabel=revenueScopeLabel(scope);
    const layout=view.productHierarchy[index]?.find(group=>group.scope===scope);
    const scopeDescription=scope&&layout?.mode==="DISCLOSURES"?` aria-describedby="${scopeHeadingId}"`:"";
    const renderRow=({row,cell},depth=firstDepth,parent=false)=>{
      const parts=row.label.split(" / ");
      const label=scopeLabel&&parts.length===2&&parts[0]===scopeLabel?parts[1]:row.label;
      return `<tr data-revenue-depth="${depth}"${parent?' class="revenue-hierarchy-parent" data-revenue-subtotal':""}><th scope="row"${scopeDescription}>${esc(label)}${Object.keys(row.fixed_axis_members||{}).length?`<small>공시 범위 · ${esc(Object.values(row.fixed_axis_members).map(revenueScopeLabel).join(" / "))}</small>`:""}${parent?"<small>공시 소계</small>":""}</th>
        ${revenueBreakdownValueCells(cell,"같은 범위의 준비 자료가 일치하지 않습니다.",Object.keys(row.fixed_axis_members||{}).length?"같은 공시 범위의 보고 매출":scope?"부문 소계":"연결 매출")}</tr>`;
    };
    const presentation=view.kind==="products"?revenueProductPresentation(layout,items,renderRow,firstDepth,heading):"";
    if(presentation)return presentation;
    const cue=view.kind==="products"?'<tr class="revenue-hierarchy-note"><td colspan="5">합산 범위 미확인 · 공시 항목별로 표시합니다.</td></tr>':"";
    return `<tbody>${heading}${cue}${items.map(item=>renderRow(item)).join("")}</tbody>`;
  }).join("");
  const derivedNote=entries.some(({cell})=>cell.derivation_rule_version)?'<details class="muted revenue-derived-note"><summary>계산값 안내</summary><p>계산값은 연간 매출에서 9개월 누적 매출을 차감한 값입니다. 재작성 비교성은 검증하지 않았습니다. 현재 비중·전년비는 직접 공시값만 계산 대상으로 사용합니다.</p></details>':"";
  table.innerHTML=`<table class="series-table"><caption>${compactFinancialCaption(caption)}</caption>
    <thead><tr><th scope="col">공시 항목</th><th scope="col">매출</th><th scope="col">검토 비중 (%)</th><th scope="col">전년비 (%)</th><th scope="col">자료·출처</th></tr></thead>
    <tbody><tr class="revenue-consolidated" data-revenue-depth="0"><th scope="row">연결 매출</th>
      ${revenueBreakdownValueCells(view.totals[index],"이 기간에 확인된 연결 매출이 없습니다.")}</tr></tbody>
    ${details}</table>${derivedNote}${revenueAvailability(view,index)}${view.kind==="geography"?'<p class="muted">원래 공시의 지역 구분입니다. 국가·지역은 서로 겹칠 수 있으며 전체 지역의 합계나 소재지·청구지·고객 위치의 동일 기준을 뜻하지 않습니다. 고정된 공시 범위의 보고 매출을 확인할 수 있을 때만 그 범위의 비중을 표시합니다.</p>':""}${entries.length?(view.kind==="segments"?'<p class="muted">연결 매출에는 부문 간 거래 제거 등 조정이 포함될 수 있습니다. 공시 범위가 완전하지 않으면 표의 부문별 금액만으로 연결 매출을 확인할 수 없습니다.</p>':""):'<p class="muted">이 회계기간의 매출 구성 자료가 준비되지 않았습니다.</p>'}`;
}
function revenueProductPresentation(layout,items,renderRow,firstDepth,scopeHeading){
  if(!["DISCLOSURES","RECONCILED","VERIFIED"].includes(layout?.mode)||!Array.isArray(layout.groups))return "";
  const byId=new Map(items.map(item=>[item.row.id,item]));
  const seen=new Set();
  const take=id=>{
    const item=byId.get(id);
    if(!item||seen.has(id))return null;
    seen.add(id);
    return item;
  };
  const groups=[];
  const disclosures=layout.mode==="DISCLOSURES";
  const note=layout.mode==="RECONCILED"?"같은 공시에서 하위 항목의 합계가 소계와 일치합니다.":disclosures?"같은 매출을 보는 별도 공시 분류입니다. 분류 간 항목은 더하지 않습니다.":"";
  const noteRow=note?`<tr class="revenue-hierarchy-note"><td colspan="5">${note}</td></tr>`:"";
  if(!disclosures&&layout.groups.length!==1)return "";
  for(const group of layout.groups){
    if(!Array.isArray(group?.rows)||!group.rows.length)return "";
    const label=String(group.label||"").replace(/^\d+\s*-\s*(?:Statement|Disclosure)\s*-\s*/iu,"");
    if(disclosures&&!label)return "";
    let rows="";
    for(const row of group.rows){
      const item=take(row?.id);
      if(!item||!Array.isArray(row.children))return "";
      rows+=renderRow(item,firstDepth,row.children.length>0);
      for(const child of row.children){
        const entry=take(child?.id);
        if(!entry||child.children?.length)return "";
        rows+=renderRow(entry,firstDepth+1);
      }
    }
    const heading=disclosures?`<tr class="revenue-disclosure-title"><th colspan="5" scope="rowgroup">공시 분류 · ${esc(label)}</th></tr>`:scopeHeading+noteRow;
    groups.push(`<tbody data-revenue-layout="${layout.mode}"${disclosures?" data-revenue-disclosure":""}>${heading}${rows}</tbody>`);
  }
  if(seen.size!==items.length)return "";
  return (disclosures?`<tbody>${scopeHeading}${noteRow}</tbody>`:"")+groups.join("");
}
function revenueSegmentSubtotal(segments,scope,index){
  const matches=segments.filter(row=>row.member===scope).map(row=>row.cells[index]).filter(Boolean);
  const available=matches.filter(cell=>cell.value!=null);
  if(available.length>1||matches.some(cell=>cell.reason==="COMPETING_PREPARED_SCOPE")){
    return {value:null,reason:"COMPETING_PREPARED_SCOPE",sources:[]};
  }
  return available[0];
}
function revenueBreakdownValueCells(cell,missingReason,expectedDenominator){
  const present=cell?.value!=null,conflict=cell?.reason==="COMPETING_PREPARED_SCOPE";
  const reason=conflict?"같은 범위의 준비 자료가 일치하지 않습니다.":cell?.reason?revenueGapLabel(cell.reason):missingReason;
  const share=cell?.ratios?.share,yoy=cell?.ratios?.yoy;
  const denominator=({CONSOLIDATED:"연결 매출",SEGMENT_SUBTOTAL:"부문 소계",FIXED_SCOPE_REPORTED:"같은 공시 범위의 보고 매출"})[share?.denominator];
  const priorCaption=yoy?`${yoy.prior_period_start} ~ ${inclusiveEnd(yoy.prior_period_end)}`:"";
  const shareReason=cell?.ratio_hold_reason?"매출은 연간−9개월 누적 계산값이며, 현재 비중·전년비는 직접 공시값만 계산 대상으로 사용합니다.":expectedDenominator?`같은 공시에서 비중을 계산할 수 있는 분모가 확인되지 않았습니다. 기준은 ${expectedDenominator}입니다.`:"연결 매출은 비중 계산의 기준입니다.";
  return `<td>${present?numberMarkup(cell.value,REVENUE_MONEY):revenueRate(null,reason)}</td>
    <td>${revenueRate(cell?.share,shareReason)}${denominator?`<small title="비중의 분모">${denominator}</small>`:""}</td>
    <td>${revenueRate(cell?.yoy,cell?.ratio_hold_reason?"매출은 연간−9개월 누적 계산값이며, 현재 비중·전년비는 직접 공시값만 계산 대상으로 사용합니다.":"같은 공시에 비교할 수 있는 전년 자료가 확인되지 않았습니다.")}${priorCaption?`<small title="${esc(priorCaption)}" aria-label="전년 비교 기간 ${esc(priorCaption)}">같은 공시</small>`:""}</td>
    <td${present&&cell.derivation_rule_version?' data-revenue-derived':""}>${present?(cell.status==="REPORTED"?"공시값":cell.derivation_rule_version?'<span class="revenue-source-kind">계산값 · 연간−9개월</span>':"계산값")+(revenueSourceLinks(cell.sources||[],revenueBreakdowns.data.cik)):(conflict?"범위 확인 필요":"자료 없음")}</td>`;
}
function revenueRate(value,reason){
  return value==null?`<span class="missing" tabindex="0" title="${esc(reason)}" aria-label="${esc(reason)}">—</span>`:numberMarkup(value,REVENUE_PERCENT);
}
function revenueTrendSeries(rows,periodCount){
  const groups=new Map();
  for(const row of rows){
    const axes=Object.entries(row.axis_members||{}).sort(([left],[right])=>left.localeCompare(right));
    if(!axes.length)continue;
    const id=JSON.stringify([row.scope??null,axes]);
    if(!groups.has(id))groups.set(id,{id,scope:row.scope,fixedAxisMembers:row.fixed_axis_members,axes,label:row.label,slots:Array.from({length:periodCount},()=>[]),reasons:Array(periodCount)});
    const group=groups.get(id);
    for(const [index,cell] of row.cells.slice(0,periodCount).entries()){
      if(cell.value!=null||cell.reason==="COMPETING_PREPARED_SCOPE")group.slots[index].push({row,cell});
      else if(cell.reason&&(!group.reasons[index]||group.reasons[index]==="PERIOD_NOT_PREPARED"))group.reasons[index]=cell.reason;
    }
  }
  return [...groups.values()].map(group=>{
    const slots=group.slots.map(items=>items.length===1&&items[0].cell.value!=null?items[0]:null);
    const last=slots.findLastIndex(Boolean);
    const gapReasons=group.slots.map((items,index)=>items.length>1?"COMPETING_PREPARED_SCOPE":items[0]?.cell.reason||group.reasons[index]);
    return {id:group.id,scope:group.scope,fixedAxisMembers:group.fixedAxisMembers,axes:group.axes,slots,gapReasons,label:slots[last]?.row.label||group.label};
  });
}
function revenueBoardLines(view){
  const lines=revenueTrendSeries(view.rows,view.periods.length);
  if(view.totals?.length){
    // The consolidated observations carry sources but no component mapping epoch.
    const row={label:"연결 매출"};
    lines.push({id:"consolidated",label:row.label,total:true,scope:null,axes:[],
      slots:view.periods.map((_,index)=>view.totals[index]?.value!=null?{row,cell:view.totals[index]}:null),
      gapReasons:view.periods.map((_,index)=>view.totals[index]?.reason)});
  }
  return lines;
}
function revenueBoardPoint(line,index,mode){
  if(line.total&&mode==="share")return {value:null,connect:false,reason:"연결 매출은 비중 계산의 기준입니다.",basis:"연결 매출"};
  const item=line.slots[index],previous=line.slots[index-1],cell=item?.cell;
  const metric=mode==="amount"?"value":mode;
  const denominator=cell?.ratios?.share?.denominator;
  const denominatorKey=entry=>{
    const type=entry?.cell.ratios?.share?.denominator;
    return type==="FIXED_SCOPE_REPORTED"?`${type}:${JSON.stringify(line.axes)}`:type==="CONSOLIDATED"?type:type==="SEGMENT_SUBTOTAL"&&line.scope?`${type}:${line.scope}`:null;
  };
  const sameDenominator=mode!=="share"||denominatorKey(item)&&denominatorKey(item)===denominatorKey(previous);
  const connected=previous?.row===item?.row&&item?.row.mapping_epoch&&!item.row.mapping_review_required&&sameDenominator;
  const gap=line.gapReasons?.[index];
  const missingReasons={
    COMPETING_PREPARED_SCOPE:"같은 범위의 준비 자료가 일치하지 않습니다.",
    PREPARED_OBSERVATION_HELD:"준비 자료가 검토 상태여서 표시할 수 없습니다.",
    SOURCE_NOT_PREPARED:"공시 근거가 준비되지 않았습니다.",
  };
  const reason=!cell?missingReasons[gap]||REVENUE_GAP_LABELS[gap]||"이 기간에 준비된 자료가 없습니다.":
    mode==="yoy"?"같은 공시에 비교할 수 있는 전년 자료가 확인되지 않았습니다.":
    mode==="share"?"같은 공시의 비중 분모가 확인되지 않았습니다.":"준비된 매출 값이 없습니다.";
  const basis=denominator==="FIXED_SCOPE_REPORTED"?"같은 공시 범위의 보고 매출":denominator==="CONSOLIDATED"?"연결 매출":denominator==="SEGMENT_SUBTOTAL"?`부문 소계 · ${revenueScopeLabel(line.scope)}`:"분모 확인 불가";
  return {value:cell?.[metric]??null,connect:Boolean(connected),reason,basis,sources:cell?.sources||[]};
}
function revenueBoardLabel(line){
  return line.label+(line.fixedAxisMembers&&Object.keys(line.fixedAxisMembers).length?` · 공시 범위 ${Object.values(line.fixedAxisMembers).map(revenueScopeLabel).join(" / ")}`:"")+(line.scope?` · ${revenueScopeLabel(line.scope)}`:"");
}
function revenueBoardOptions(lines){
  const labels=new Map();
  for(const line of lines){
    const label=revenueBoardLabel(line);
    labels.set(label,(labels.get(label)||0)+1);
  }
  return lines.map(line=>{
    const label=revenueBoardLabel(line);
    const identity=[line.scope,...line.axes.map(([axis,member])=>`${axis}=${member}`)].filter(Boolean).join(" / ");
    return {id:line.id,label:labels.get(label)>1?`${label} · ${identity}`:label};
  });
}
function mountRevenueBoardControls(){
  $("#revenue-board-y-scale").onchange=()=>renderRevenueBreakdownTrend();
  $("#revenue-board-share-toggle").onchange=()=>renderRevenueBreakdownTrend();
  $("#revenue-board-period").onchange=event=>updateRevenueBoardPeriod(Number(event.target.value));
  bindProfileBoardPeriod($("#profile-revenue-breakdowns"),updateRevenueBoardPeriod,()=>revenueBreakdowns.board?.active,{
    valid:()=>Boolean(revenueBreakdowns.board)&&!$("#profile-revenue-breakdowns").hidden,
    key:()=>revenueBreakdowns.board,
    count:()=>revenueBreakdowns.board?.periods.length||0,describe:revenueBoardContext,defaultMode:"amount",
    order:()=>revenueBreakdowns.board?.selection.order.join(","),items:()=>revenueBreakdowns.board?.selection.order||[],
  });
  observeProfileBoardWidth($(".revenue-board-panels"),renderRevenueBreakdownTrend,()=>Boolean(revenueBreakdowns.board)&&!$("#profile-revenue-breakdowns").hidden);
}
function configureRevenueBoard(view){
  const lines=revenueBoardLines(view);
  const key=`${view.frequency}:${view.kind}`;
  let model=revenueBreakdowns.boards.get(key);
  const periodSelect=$("#revenue-board-period");
  if(!model){
    const components=lines.filter(line=>!line.total);
    const defaults=[...components.filter(line=>line.slots.at(-1)),...components.filter(line=>!line.slots.at(-1)&&line.slots.some(Boolean))].slice(0,3);
    model={selection:createProfileBoard(defaults.map(line=>line.id)),active:Math.max(0,view.periods.length-1),share:false};
    revenueBreakdowns.boards.set(key,model);
  }
  model.view=view;model.lines=lines;
  model.periods=view.periods.map(period=>({
    label:revenuePeriodLabel(period,view.frequency),
    short:`${String(period.fiscal_year).slice(-2)}${view.frequency==="quarterly"?`Q${period.fiscal_quarter}`:""}`,
  }));
  model.options=revenueBoardOptions(lines);
  revenueBreakdowns.board=model;
  periodSelect.innerHTML=model.periods.map(({label},index)=>`<option value="${index}">${esc(label)}</option>`).join("");
  periodSelect.disabled=!model.periods.length;
  $("#revenue-board-share-toggle").checked=model.share;
  $("#revenue-board-y-scale").value=model.includeZero?"ZERO":"AUTO";
  renderProfileBoardSelection($(".revenue-breakdown-trend"),model.selection,model.options,renderRevenueBreakdownTrend);
}
function profileBoardLegend(lines){
  return lines.length?`<ul class="board-near-legend" aria-label="차트 항목">${lines.map(line=>`<li><button type="button" data-board-item="${esc(line.id)}" title="${esc(line.label)}" aria-label="${esc(line.label)}: 선택 기간 설명 고정">${profileBoardSwatch(line.color)}<span>${esc(line.label)}</span></button></li>`).join("")}</ul>`:"";
}
function revenueBoardContext(id,index,mode="amount"){
  const model=revenueBreakdowns.board;if(!model?.periods[index])return "";
  const lines=id?model.visible.filter(line=>line.id===id):model.visible;
  const definition=mode==="amount"?REVENUE_MONEY:REVENUE_PERCENT;
  return lines.map(line=>{
    const point=line.points[mode]?.[index];if(!point)return "";
    const rationale=mode==="share"?`비중 분모: ${point.basis} · 합계가 아닌 개별 비중`:
      mode==="yoy"?"같은 공시의 전년 비교값 · 추이의 전년 금액과 다를 수 있습니다.":"";
    const detail=[actualPeriod(model.view.periods[index]),rationale].filter(Boolean).join(" · ");
    return `<div>${profileBoardContextLine(line.label,model.periods[index].label,point.value,definition,point.reason,detail)}${revenueSourceLinks(point.sources||[],revenueBreakdowns.data?.cik)}</div>`;
  }).join("");
}
function renderRevenueBreakdownTrend(){
  const model=revenueBreakdowns.board;
  if(!model)return;
  const host=$("#profile-revenue-breakdowns"),restore=host.profileBoardInteraction?.beforeRender($(".revenue-board-panels"));
  const {selection,view,periods,lines,options,active}=model;
  const labels=new Map(options.map(item=>[item.id,item.label]));
  const visible=selection.order.map(id=>lines.find(line=>line.id===id)).filter(Boolean);
  model.share=$("#revenue-board-share-toggle").checked;
  model.includeZero=$("#revenue-board-y-scale").value==="ZERO";
  const definitions={amount:REVENUE_MONEY,yoy:REVENUE_PERCENT,share:REVENUE_PERCENT};
  const charts=[
    ["amount","#revenue-breakdown-chart","매출 금액"],
    ["yoy","#revenue-breakdown-growth","같은 공시 전년비"],
    ["share","#revenue-breakdown-share","항목별 비중"],
  ];
  model.visible=visible.map(line=>({
    id:line.id,label:labels.get(line.id),color:selection.colors.get(line.id),
    points:Object.fromEntries(charts.map(([mode])=>[mode,periods.map((_,index)=>revenueBoardPoint(line,index,mode))])),
  }));
  for(const [mode,selector,label] of charts){
    const series=model.visible.map(line=>({...line,points:line.points[mode]}));
    const target=$(selector);target.parentElement?.setAttribute("data-board-mode",mode);
    const hasValues=series.some(line=>line.points.some(point=>point.value!=null));
    target.innerHTML=profileBoardLegend(model.visible)+(mode==="share"&&!hasValues?
      '<div class="board-context" role="status" tabindex="0" hidden></div><p class="board-empty">선택 항목의 비중이 준비되지 않았습니다. 분모와 누락 사유는 아래 기간별 값에서 확인하세요.</p>':
      profileBoardPlot({periods,series,definition:definitions[mode],label,active,interactive:true,includeZero:model.includeZero,width:Math.max(360,Math.floor(target.clientWidth||570)),height:176}));
  }
  $("#revenue-share-panel").hidden=!model.share;
  const values=$("#revenue-board-values");
  values.innerHTML=visible.length?`<table class="series-table"><thead><tr><th scope="col">회계기간</th><th scope="col">항목</th><th scope="col">매출 · 백만 USD</th><th scope="col">전년비 (%)</th>${model.share?'<th scope="col">비중 (%) · 분모</th>':""}</tr></thead>
    ${view.periods.map((period,index)=>`<tbody>${model.visible.map((line,row)=>{
      const [amount,rate,share]=charts.map(([mode])=>line.points[mode][index]);
      return `<tr>${row===0?`<th scope="rowgroup" rowspan="${visible.length}">${esc(periods[index].label)}<small>${esc(actualPeriod(period))}</small></th>`:""}
        <th scope="row">${esc(line.label)}</th><td>${profileBoardValue(amount.value,REVENUE_MONEY,amount.reason,true)}</td><td>${profileBoardValue(rate.value,REVENUE_PERCENT,rate.reason,true)}</td>
        ${model.share?`<td>${profileBoardValue(share.value,REVENUE_PERCENT,share.reason,true)}${share.value!=null?`<small>${esc(share.basis)}</small>`:""}</td>`:""}</tr>`;
    }).join("")}</tbody>`).join("")}</table>`:"";
  $("#revenue-board-evidence").hidden=!visible.length;
  updateRevenueBoardPeriod(active,true);
  host.profileBoardInteraction?.afterRender(restore);
}
function updateRevenueBoardPeriod(index,force=false){
  const model=revenueBreakdowns.board;
  if(!model?.periods[index]||!force&&index===model.active)return;
  model.active=index;
  $("#revenue-board-period").value=String(index);
  markProfileBoardPeriod($("#profile-revenue-breakdowns"),index,model.periods.length);
  const period=model.view.periods[index];
  $("#revenue-board-readout").innerHTML=model.visible.length?`<p><strong>${esc(model.periods[index].label)}</strong> · ${financialPeriodDisplay(period)}</p>
    <ul>${model.visible.map(line=>{
      const {amount,yoy,share}=Object.fromEntries(Object.entries(line.points).map(([mode,points])=>[mode,points[index]]));
      return `<li>${profileBoardSwatch(line.color)}<strong>${esc(line.label)}</strong>
        <span>매출 ${profileBoardValue(amount.value,REVENUE_MONEY,amount.reason)} 백만 USD · 전년비 ${profileBoardValue(yoy.value,REVENUE_PERCENT,yoy.reason)} %
          ${model.share?` · 비중 ${profileBoardValue(share.value,REVENUE_PERCENT,share.reason)} %${share.value!=null?` (${esc(share.basis)})`:""}`:""}</span></li>`;
    }).join("")}</ul>`:"";
}

// Multi-metric comparison reuses published series and the prepared comparison adjunct.
const comparisonMulti={token:0,model:null,cache:new Map(),observer:null,frame:0};
function comparisonMultiOwns(model){return S.view==="explorer"&&model&&comparisonMulti.model===model&&model.token===comparisonMulti.token&&!$("#comparison-panel").hidden&&model.key===explorerContextKey()&&JSON.stringify(model.ciks)===JSON.stringify([...S.explorerSelected].sort())&&model.selection===JSON.stringify([...$("#comparison-metrics").selectedOptions].map(option=>option.value))}
function invalidateComparisonMulti(){comparisonMulti.token++;comparisonMulti.model=null;if($("#comparison-multi-board"))$("#comparison-multi-board").hidden=true}
async function readComparisonPreparedGrowth(context,cik){
  const dataset=explorerDataset(),scope={dataset_id:context.dataset,dataset_publication_id:context.publication,financial_as_of:context.financialAsOf,cik};
  if(!financialGrowthCapability)financialGrowthCapability=api("/api/financial-growth").catch(error=>{financialGrowthCapability=null;throw error});
  const capability=await financialGrowthCapability,{cik:ignored,...request}=scope;
  const owner=(capability.owner_contexts||[]).find(item=>Object.keys(request).every(key=>item.request_scope?.[key]===request[key])&&item.request_scope.dataset_manifest_sha256===dataset?.auxiliary_manifest_sha256&&item.available_ciks?.includes(cik));
  if(!capability.configured||!owner&&Object.keys(request).some(key=>capability[key]!==request[key]))throw new Error("이 기업 발행물의 상세 비교 자료가 준비되지 않았습니다.");
  const source=owner?.source_scope||capability,query=new URLSearchParams(scope).toString();let pending=financialGrowthCache.get(query);
  if(!pending){pending=api(`/api/financial-growth?${query}`).then(response=>{
    const data=auxiliaryOwnerPayload(response,scope,dataset,owner?.source_scope||null),expected=data.auxiliary_owner?{...data.auxiliary_owner.source_scope,cik}:scope;
    if(!((data.schema_version==="screening-financial-growth-v1"&&data.rule_version===FINANCIAL_GROWTH_RULE)||(data.schema_version==="screening-financial-growth-v2"&&data.rule_version==="catalog-prepared-financial-comparison-v2"))||data.period_end_convention!=="EXCLUSIVE"||Object.keys(scope).some(key=>data[key]!==expected[key])||data.dataset_manifest_sha256!==source.dataset_manifest_sha256||!data.definitions||!data.series)throw new Error("상세 비교 자료의 원본 발행물 범위가 다릅니다.");return data;
  });financialGrowthCache.set(query,pending);pending.catch(()=>{if(financialGrowthCache.get(query)===pending)financialGrowthCache.delete(query)})}
  return pending;
}
function comparisonMultiPoints(item,company){return company.points.map((point,index)=>({value:point.observation?.value??null,row:point.observation,connect:index>0&&item.aligned.slots[index-1].ordinal===point.slot.ordinal-1,reason:point.observation?.reason_labels?.[0]||"이 기간에 준비된 값이 없습니다."}))}
function comparisonMultiRates(model,item,company){
  const definitions=new Map(activeExplorerMetrics().map(definition=>[definition.metric_id,definition])),published=financialProfileGrowth(item.definition.metric_id,definitions);
  if(published){const record=item.published?.series.find(series=>series.company.cik===company.company.cik);return{definition:published,points:record?comparisonMultiPoints({...item,aligned:item.published},record):model.slots.map(()=>({value:null,reason:"공표된 전년비를 불러오지 못했습니다."})),published:true}}
  if(!financialComparisonEligible(item.definition))return{definition:null,points:null};
  const levels=comparisonMultiPoints(item,company),growth=model.growth.get(company.company.cik)||{loading:true};
  return{definition:financialComparisonMetric(item.definition),points:financialGrowthPoints({growth,context:item.context,slots:model.slots},item.definition,levels),published:false};
}
function comparisonMultiContext(id,index,mode){
  const model=comparisonMulti.model;if(!comparisonMultiOwns(model)||!id)return "";const [metricId,cik]=id.split("|"),item=model.items.find(entry=>entry.definition.metric_id===metricId),company=item?.aligned?.series.find(entry=>entry.company.cik===cik);if(!company||!model.slots[index])return "";
  const levels=comparisonMultiPoints(item,company),rate=comparisonMultiRates(model,item,company),point=mode==="growth"?rate.points?.[index]:levels[index],definition=mode==="growth"?rate.definition:item.definition;
  if(!point||!definition)return "";const row=point.row||point.evidence?.current||levels[index]?.row,policy=point.row?.continuity_evidence||point.row?.continuity_policy;
  const detail=[row?actualPeriod(row):"",mode==="growth"?preparedChangeCaption(item.definition):metricPresentationCaption(item.definition),mode==="growth"?(point.formula||definition.formula||""):"",policy?"동일 공시의 전년 비교 근거":"",...(row?.source_filings||[])].filter(Boolean).join(" · ");
  return profileBoardContextLine(`${company.company.ticker||cik} · ${item.definition.label}`,model.slots[index].label,point.value,definition,point.reason,detail)+(mode==="growth"?financialGrowthEvidence(point):"");
}
function mountComparisonMulti(){
  if($("#comparison-multi-board"))return;
  const section=document.createElement("section");section.id="comparison-multi-board";section.className="comparison-multi-board";
  section.innerHTML='<div class="comparison-multi-heading"><h3>선택 지표 · 기업별 수준과 준비된 변화</h3><label>보기<select id="comparison-board-view"><option value="BOTH">수준 + 준비된 변화</option><option value="LEVEL">수준</option></select></label><label>공통 기간<select id="comparison-board-period"></select></label></div><p id="comparison-board-status" role="status"></p><div class="comparison-multi-grid"></div>';
  $("#comparison-result").before(section);arrangeComparisonAnalysis();$("#comparison-board-period").onchange=event=>updateComparisonMultiPeriod(Number(event.target.value));$("#comparison-board-view").onchange=()=>{if(comparisonMultiOwns(comparisonMulti.model))renderComparisonMulti(comparisonMulti.model)};
  bindProfileBoardPeriod(section,(index)=>updateComparisonMultiPeriod(index),()=>comparisonMulti.model?.active,{
    valid:()=>comparisonMultiOwns(comparisonMulti.model),key:()=>comparisonMulti.model?`${comparisonMulti.model.identity}:${$("#comparison-board-view").value}`:null,count:()=>comparisonMulti.model?.slots.length||0,describe:comparisonMultiContext,defaultMode:"level",defaultItem:target=>{const id=target.closest?.("[data-comparison-board-metric]")?.dataset.comparisonBoardMetric;return id&&comparisonMulti.model?.ciks[0]?`${id}|${comparisonMulti.model.ciks[0]}`:null},items:()=>comparisonMulti.model?.items.flatMap(item=>comparisonMulti.model.ciks.map(cik=>`${item.definition.metric_id}|${cik}`))||[],
  });
  if(typeof ResizeObserver!=="undefined"){comparisonMulti.observer=new ResizeObserver(()=>{if(comparisonMulti.frame)return;comparisonMulti.frame=requestAnimationFrame(()=>{comparisonMulti.frame=0;if(comparisonMultiOwns(comparisonMulti.model))renderComparisonMulti(comparisonMulti.model)})});comparisonMulti.observer.observe(section.querySelector(".comparison-multi-grid"))}
}
function readComparisonMetric(context,definition,ciks){
  const key=JSON.stringify([context.key,context.publication,context.financialAsOf,definition.definition_version,context.annualYears]);if(comparisonMulti.cache.has(key))return comparisonMulti.cache.get(key);
  const pending=(async()=>{const records=await Promise.all(ciks.map(cik=>cachedCompanyTrendSeries(context,cik).catch(error=>({company:context.companies.find(company=>company.cik===cik),error:error.message,rows:[],preparedYears:[]}))));
    const aligned=alignCompanyTrend(context,records),publishedDefinition=financialProfileGrowth(definition.metric_id,new Map((context.catalogDefinitions||activeExplorerMetrics()).map(metric=>[metric.metric_id,metric])));let published=null;
    if(publishedDefinition){const publishedContext={...context,definition:publishedDefinition},rates=await Promise.all(ciks.map(cik=>cachedCompanyTrendSeries(publishedContext,cik).catch(error=>({company:context.companies.find(company=>company.cik===cik),error:error.message,rows:[],preparedYears:[]}))));published=alignCompanyTrend(publishedContext,rates)}
    return{definition,context,aligned,published};})();comparisonMulti.cache.set(key,pending);while(comparisonMulti.cache.size>32)comparisonMulti.cache.delete(comparisonMulti.cache.keys().next().value);pending.then(item=>{if((item.aligned.series.some(series=>series.error)||item.published?.series.some(series=>series.error))&&comparisonMulti.cache.get(key)===pending)comparisonMulti.cache.delete(key)},()=>{if(comparisonMulti.cache.get(key)===pending)comparisonMulti.cache.delete(key)});return pending;
}
async function loadComparisonMulti(){
  const ids=[...$("#comparison-metrics").selectedOptions].map(option=>option.value),ciks=[...S.explorerSelected].sort();if(ciks.length<2||ciks.length>4||!ids.length)return;
  mountComparisonMulti();const host=$("#comparison-multi-board"),token=++comparisonMulti.token;
  const model={token,key:explorerContextKey(),ciks,selection:JSON.stringify(ids),identity:JSON.stringify([explorerContextKey(),ciks,ids]),items:[],slots:[],growth:new Map(),active:0};comparisonMulti.model=model;host.hidden=false;$("#comparison-board-status").textContent="선택 지표의 공표 시계열을 불러옵니다…";
  try{
    const definitions=activeExplorerMetrics(),selected=ids.slice(0,PROFILE_BOARD_LIMIT);let next=0;const loaded=new Map();
    async function worker(){while(next<selected.length){const id=selected[next++],definition=definitions.find(item=>item.metric_id===id);if(!definition)throw new Error("선택한 지표의 카탈로그 정의가 없습니다.");const item=await readComparisonMetric(companyTrendContext(id,true),definition,ciks);if(!comparisonMultiOwns(model))return;loaded.set(id,item)}}
    await Promise.all(Array.from({length:Math.min(2,selected.length)},worker));if(!comparisonMultiOwns(model))return;
    model.items=selected.map(id=>loaded.get(id)).filter(Boolean);model.slots=model.items[0]?.aligned.slots||[];model.active=Math.max(0,model.slots.length-1);
    $("#comparison-board-period").innerHTML=model.slots.map((slot,index)=>`<option value="${index}">${esc(slot.label)}</option>`).join("");$("#comparison-board-period").value=String(model.active);
    $("#comparison-board-status").textContent=`선택 ${ids.length}개 · 차트 ${model.items.length}개${ids.length>PROFILE_BOARD_LIMIT?`(최대 ${PROFILE_BOARD_LIMIT}개, 나머지는 아래 비교표)` :""} · 지표별 독립 축 · 상세 비교는 조건 등록 여부와 다릅니다.`;
    renderComparisonMulti(model);
    if(model.items.some(item=>financialComparisonEligible(item.definition)&&!financialProfileGrowth(item.definition.metric_id,new Map(definitions.map(metric=>[metric.metric_id,metric]))))){
      await Promise.all(ciks.map(async cik=>{try{const data=await readComparisonPreparedGrowth(model.items[0].context,cik);if(comparisonMultiOwns(model))model.growth.set(cik,{data})}catch(error){if(comparisonMultiOwns(model))model.growth.set(cik,{error:error.message})}}));if(comparisonMultiOwns(model))renderComparisonMulti(model);
    }
  }catch(error){if(comparisonMultiOwns(model))$("#comparison-board-status").textContent=error.message}
}
function renderComparisonMulti(model){
  if(!comparisonMultiOwns(model))return;const host=$("#comparison-multi-board"),grid=host.querySelector(".comparison-multi-grid"),restore=host.profileBoardInteraction?.beforeRender(grid),expanded=new Set([...grid.querySelectorAll("details[open]")].map(node=>node.dataset.comparisonDetails));
  const width=Math.max(360,Math.floor((grid.clientWidth||1100)/(grid.clientWidth>=1450?4:grid.clientWidth>=1060?3:grid.clientWidth>=700?2:1)-16));
  grid.innerHTML=model.items.map(item=>{
    const definition=item.definition,id=definition.metric_id,companies=item.aligned.series,rateDefinition=comparisonMultiRates(model,item,companies[0]||{company:{cik:""},points:[]}).definition;
    const series=(mode)=>companies.map((company,index)=>({id:`${id}|${company.company.cik}`,label:company.company.ticker||company.company.name,color:index,points:mode==="level"?comparisonMultiPoints(item,company):comparisonMultiRates(model,item,company).points||[]}));
    const legend=mode=>`<div class="board-near-legend">${companies.map((company,index)=>`<button type="button" data-board-item="${esc(id+"|"+company.company.cik)}" title="${esc(company.company.name||company.company.ticker)}">${profileBoardSwatch(index)}${esc(company.company.ticker||company.company.name)}</button>`).join("")}</div>`;
    const plot=(mode,metric,title)=>`<div class="financial-board-plot" data-board-mode="${mode}"><h5>${esc((mode==="level"&&metric.unit_kind==="MONEY"?"금액":title).replace(/\s*\(%p?\)$/u,""))} · ${esc(metricPresentationUnit(metric))}</h5>${legend(mode)}${profileBoardPlot({periods:model.slots,series:series(mode),definition:metric,label:title,active:model.active,interactive:true,type:mode==="level"?"LINE":"LINE",width,height:mode==="level"?144:116,showPeriods:mode!=="level"||!rateDefinition||$("#comparison-board-view").value==="LEVEL"})}</div>`;
    return `<article class="financial-board-card" data-comparison-board-metric="${esc(id)}"><h4 title="${esc(metricPresentationCaption(definition))}">${esc(financialMetricCaption(definition))}</h4><small>${esc(metricPresentation(definition,{catalog:activeExplorerMetrics()}).period)} · ${esc(metricPresentation(definition,{catalog:activeExplorerMetrics()}).source)}</small>
      ${plot("level",definition,"수준")}${$("#comparison-board-view").value==="LEVEL"?"":rateDefinition?plot("growth",rateDefinition,preparedChangeCaption(definition)):'<p class="board-empty">이 단위의 준비된 비교 지표가 없습니다.</p>'}<div class="comparison-multi-readout" data-comparison-readout="${esc(id)}"></div>${companies.map(company=>{const rates=comparisonMultiRates(model,item,company);return rates.points?.some(point=>point.status)?`<div data-board-item="${esc(id+"|"+company.company.cik)}"><small>${esc(company.company.ticker||company.company.name)} 기간별 상태</small>${financialGrowthPeriodStatuses(rates.points,model.slots,model.active)}</div>`:""}).join("")}
      <details data-comparison-details="${esc(id)}" ${expanded.has(id)?"open":""}><summary>정확한 값·실제 기간·출처</summary><div class="table-wrap"><table class="series-table"><thead><tr><th>기간</th><th>기업</th><th>수준 · ${esc(unitLabel(definition))}</th><th>${esc(preparedChangeCaption(definition))}</th></tr></thead><tbody>${model.slots.map((slot,index)=>companies.map(company=>{const level=comparisonMultiPoints(item,company)[index],rates=comparisonMultiRates(model,item,company),rate=rates.points?.[index];return `<tr><th>${esc(slot.label)}</th><th>${esc(company.company.ticker||company.company.name)}</th><td>${profileBoardValue(level?.value,definition,level?.reason,true)}<small>${esc(actualPeriod(level?.row||{}))}</small><details><summary>공표 원문 근거</summary><pre>${esc(JSON.stringify(level?.row||{},null,2))}</pre></details></td><td>${rates.definition?profileBoardValue(rate?.value,rates.definition,rate?.reason,true):"—"}${rate?financialGrowthEvidence(rate,true):""}<small>${esc(actualPeriod(rate?.row||rate?.evidence?.current||{}))}</small>${rates.definition?`<details><summary>공표된 비교 정의·원문 근거</summary><p>${esc(rate?.formula||rates.definition.formula||"발행된 비교 정의")}</p><pre>${esc(JSON.stringify({definition:rates.definition,observation:rate?.row,comparison:rate?.evidence},null,2))}</pre></details>`:""}</td></tr>`}).join("")).join("")}</tbody></table></div></details></article>`;
  }).join("");
  updateComparisonMultiPeriod(model.active,true);host.profileBoardInteraction?.afterRender(restore);
}
function updateComparisonMultiPeriod(index,force=false){
  const model=comparisonMulti.model;if(!comparisonMultiOwns(model)||!model.slots[index]||!force&&model.active===index)return;model.active=index;$("#comparison-board-period").value=String(index);markProfileBoardPeriod($("#comparison-multi-board"),index,model.slots.length);
  for(const item of model.items){const node=[...$("#comparison-multi-board").querySelectorAll('[data-comparison-readout]')].find(element=>element.dataset.comparisonReadout===item.definition.metric_id);if(!node)continue;
    node.innerHTML=`<strong>${esc(model.slots[index].label)}</strong><ul>${item.aligned.series.map(company=>{const level=comparisonMultiPoints(item,company)[index],rates=comparisonMultiRates(model,item,company),rate=rates.points?.[index];return `<li>${esc(company.company.ticker||company.company.name)} · ${profileBoardValue(level?.value,item.definition,level?.reason)} ${esc(unitLabel(item.definition))}${level?.value==null?`<small>${esc(level?.reason||"수준 미준비")}</small>`:""}${rates.definition?`<small>${esc(preparedChangeCaption(item.definition))}: ${profileBoardValue(rate?.value,rates.definition,rate?.reason)}${rate?.value==null?` · ${esc(rate?.reason||"상세 비교 미준비")}`:""}${financialGrowthEvidence(rate||{})}</small>`:""}</li>`}).join("")}</ul>`;
  }
}

// Published same-metric company trends; no screening state or financial calculations.
const companyTrend={token:0,cache:new Map(),model:null,displayModel:null,scale:"AMOUNT",baseMetric:"revenue",frame:0,resizeObserver:null};
const COMPANY_TREND_METRICS={revenue:"매출",operating_income:"영업이익",net_income:"순이익",cfo:"영업활동 현금흐름",standardized_fcf:"표준화 FCF"};
const COMPANY_TREND_STYLES=[{color:"#225e80",dash:""},{color:"#32634f",dash:"7 4"},{color:"#8b5a12",dash:"2 3"},{color:"#795787",dash:"10 3 2 3"}];
function invalidateCompanyTrend(){
  companyTrend.token++;companyTrend.model=null;companyTrend.displayModel=null;
  const section=$("#comparison-trend");if(!section)return;
  section.setAttribute("aria-busy","false");$("#comparison-trend-chart").replaceChildren();$("#comparison-trend-values").replaceChildren();$("#comparison-trend-legend").replaceChildren();$("#comparison-trend-status").textContent="";$("#comparison-trend-base").textContent="";$("#comparison-trend-retry").hidden=true;
}
function companyTrendMetricOptions(){
  const prefix=explorerBasis.basis==="ANNUAL"?"":explorerBasis.basis==="TTM"?"ttm_":"quarter_";
  return Object.entries(COMPANY_TREND_METRICS).map(([base,label])=>({base,label,definition:activeExplorerMetrics().find(metric=>metric.metric_id===prefix+base)})).filter(item=>item.definition?.unit_kind==="MONEY"&&item.definition.unit==="USD");
}
function companyTrendSpine(latest){
  const inventory=explorerBasis.inventory||{},base=(inventory.spine||[]).map(row=>({...row})),published=inventory.latest_company_periods;
  if(!latest||!published)return base;
  const dataset=explorerDataset(),cutoff=dataset?.financial_as_of||explorerBasis.snapshot?.financial_as_of;
  if(published.schema_version!=="screening-latest-company-periods-v1"||published.dataset_id!==dataset?.dataset_id||
      published.dataset_publication_id!==(dataset?.publication_id||dataset?.dataset_publication_id)||published.financial_as_of!==cutoff||!Array.isArray(published.records))throw new Error("최신 분기 공표 범위가 선택한 자료와 다릅니다.");
  const byCoordinate=new Map(base.map(row=>[periodCoordinate(row),row])),seen=new Set();
  for(const row of published.records){
    const end=row.period_end;
    if(!/^\d{10}$/u.test(row.cik||"")||seen.has(row.cik)||row.bucket_status!=="PERIOD_AVAILABLE"||row.end_convention!=="EXCLUSIVE"||
        !/^\d{4}-\d{2}-\d{2}$/u.test(end||"")||!Number.isInteger(row.calendar_year)||![1,2,3,4].includes(row.calendar_quarter))throw new Error("최신 분기 공표 좌표를 확인할 수 없습니다.");
    const date=new Date(`${end}T00:00:00Z`);if(!Number.isFinite(date.getTime())||date.toISOString().slice(0,10)!==end)throw new Error("최신 분기 날짜가 올바르지 않습니다.");
    date.setUTCDate(date.getUTCDate()-1);
    if(date.toISOString().slice(0,10)>cutoff||date.getUTCFullYear()!==row.calendar_year||Math.floor(date.getUTCMonth()/3)+1!==row.calendar_quarter)throw new Error("최신 분기 날짜가 자료 기준 범위를 벗어납니다.");
    seen.add(row.cik);byCoordinate.set(periodCoordinate(row),{calendar_year:row.calendar_year,calendar_quarter:row.calendar_quarter});
  }
  return [...byCoordinate.values()].sort((a,b)=>a.calendar_year-b.calendar_year||a.calendar_quarter-b.calendar_quarter);
}
function companyTrendContext(metric,expanded=false){
  const basis=explorerBasis.basis,dataset=explorerDataset(),annual=basis==="ANNUAL",ciks=[...S.explorerSelected].sort();
  if(ciks.length<2||ciks.length>4)throw new Error("같은 지표를 비교할 기업을 2~4개 선택해 주세요.");
  if(explorerBasis.readyKey!==explorerContextKey())throw new Error("현재 탐색 자료를 먼저 불러와 주세요.");
  const definition=activeExplorerMetrics().find(item=>item.metric_id===metric);
  if(!definition||!expanded&&(definition.unit_kind!=="MONEY"||definition.unit!=="USD")||expanded&&!["MONEY","PERCENT","RATIO"].includes(definition.unit_kind))throw new Error("이 보기에서 준비된 동일 통화 금액 지표가 아닙니다.");
  const rows=annual?S.explorer.rows:explorerBasis.snapshot.rows;
  const ends=latestExplorerPeriod()?Object.fromEntries(ciks.map(cik=>{
    const period=annual?S.explorer.resolved_periods?.[cik]:rows.find(row=>row.company.cik===cik)?.period;
    return[cik,period?(annual?period.fiscal_year:periodCoordinate(period)):null];
  })):null;
  const availableEnds=ends?Object.values(ends).filter(value=>value!==null).sort():[];
  const end=availableEnds.at(-1)??(annual?S.explorerYear:explorerBasis.periods[basis]);
  if(ends&&!availableEnds.length)throw new Error("비교 기업에 준비된 기간이 없습니다.");
  return{catalogDefinitions:expanded?activeExplorerMetrics().slice():undefined,annualDefinitions:annual?(expanded?activeExplorerMetrics():companyTrendMetricOptions().map(item=>item.definition)):[],dataset:dataset.dataset_id,publication:S.explorer?.dataset_publication_id,financialAsOf:annual?S.explorer.financial_as_of:explorerBasis.snapshot.financial_as_of,basis,end,ends,ciks,definition,companies:rows.map(row=>row.company),annualYears:annual?S.explorer.fiscal_years.map(row=>row.fiscal_year):[],spine:annual?[]:companyTrendSpine(latestExplorerPeriod()),explorerKey:explorerContextKey(),key:JSON.stringify([dataset.dataset_id,basis,end,ends,ciks,metric])};
}
function companyTrendOwns(context,token){
  if(token!==companyTrend.token||$("#comparison-panel").hidden||context.explorerKey!==explorerContextKey())return false;
  return JSON.stringify([...S.explorerSelected].sort())===JSON.stringify(context.ciks)&&$("#comparison-trend-metric").value===context.definition.metric_id;
}
function projectTrendObservation(row){
  const keys=["observation_id","metric_observation_id","source_kind","source_filings","continuity_evidence","selection_as_of_date","metric_id","fiscal_year","fiscal_quarter","calendar_year","calendar_quarter","availability_status","value","period_start","period_end","end_convention","definition_version","unit","cik","quality_status","quality_blocking","reason","reason_labels"];
  const result=Object.fromEntries(keys.filter(key=>Object.hasOwn(row,key)).map(key=>[key,row[key]]));
  const guarded=preparedExplorerObservation(result);
  if(guarded.value===null&&result.reason_labels?.length)guarded.reason_labels=[...result.reason_labels];
  return guarded;
}
function validateCompanyTrendSeries(context,cik,payload){
  const annual=context.basis==="ANNUAL",expected=context.definition;
  let definition,rows,years=[],company=context.companies.find(item=>item.cik===cik)||{cik,ticker:cik,name:cik};
  if(annual){
    if(payload.dataset_id!==context.dataset||!context.publication||payload.dataset_publication_id!==context.publication||payload.financial_as_of!==context.financialAsOf||payload.selected_fiscal_year!==context.end||payload.company?.cik!==cik)throw new Error("연간 기업 자료의 선택 범위가 다릅니다.");
    const definitions=(payload.groups||[]).flatMap(group=>group.metrics||[]).map(item=>item.definition).filter(item=>item?.metric_id===expected.metric_id);
    if(definitions.length!==1)throw new Error("연간 지표 정의가 없거나 중복됩니다.");
    definition=definitions[0];rows=payload.series?.[expected.metric_id];years=payload.prepared_years;
    if(!Array.isArray(years)||new Set(years).size!==years.length||years.some(year=>!Number.isInteger(year)||!context.annualYears.includes(year)))throw new Error("연간 준비 기간의 범위가 다릅니다.");
    company={cik:payload.company.cik,ticker:payload.company.ticker,name:payload.company.name};
  }else{definition=payload.metric;rows=payload.observations}
  if(!definition||["metric_id","definition_version","unit_kind","unit"].some(field=>definition[field]!==expected[field])||(annual?definition.period_class!==expected.period_class:definition.observation_basis!==expected.observation_basis))throw new Error("기업별 지표 정의 또는 단위가 다릅니다.");
  if(!Array.isArray(rows))throw new Error("공표된 시계열이 없습니다.");
  const coordinates=new Set();
  for(const row of rows){
    if(row.metric_id!==expected.metric_id||row.definition_version!==expected.definition_version)throw new Error("시계열의 지표 정의가 다릅니다.");
    if(annual){if(!Number.isInteger(row.fiscal_year)||!years.includes(row.fiscal_year))throw new Error("시계열의 회계연도 범위가 다릅니다.")}
    else if(row.cik!==cik||row.unit!==expected.unit||row.selection_as_of_date!==context.financialAsOf||row.period_class!==expected.observation_basis||!Number.isInteger(row.calendar_year)||![1,2,3,4].includes(row.calendar_quarter)||(row.period_end&&row.end_convention!=="EXCLUSIVE"))throw new Error("분기 시계열의 기업·기간·단위 범위가 다릅니다.");
    const coordinate=annual?row.fiscal_year:periodCoordinate(row);if(!annual&&!context.spine.some(slot=>periodCoordinate(slot)===coordinate))throw new Error("시계열의 분기가 준비된 기간 범위를 벗어납니다.");if(coordinates.has(coordinate))throw new Error("시계열의 기간 좌표가 중복됩니다.");coordinates.add(coordinate);
    if(row.value!==null&&row.value!==undefined){if(typeof row.value!=="string")throw new Error("정확한 공표 숫자 문자열이 아닙니다.");shiftDecimal(row.value,0)}
  }
  return{company,preparedYears:years.slice(),rows:rows.map(projectTrendObservation)};
}
const annualProfilePayloadCache=new Map();
function readAnnualProfilePayload(context,cik,path){
  const key=JSON.stringify([context.dataset,context.publication,context.financialAsOf,cik,Boolean(context.ends),context.end]);
  if(annualProfilePayloadCache.has(key))return annualProfilePayloadCache.get(key);
  const pending=api(path).then(payload=>{if(payload.dataset_id!==context.dataset||payload.dataset_publication_id!==context.publication||payload.financial_as_of!==context.financialAsOf||payload.company?.cik!==cik||payload.selected_fiscal_year!==context.end)throw new Error("연간 기업 자료의 선택 범위가 다릅니다.");return payload});
  annualProfilePayloadCache.set(key,pending);while(annualProfilePayloadCache.size>32)annualProfilePayloadCache.delete(annualProfilePayloadCache.keys().next().value);pending.catch(()=>{if(annualProfilePayloadCache.get(key)===pending)annualProfilePayloadCache.delete(key)});return pending;
}
function cachedCompanyTrendSeries(context,cik){
  const annual=context.basis==="ANNUAL",definitions=context.annualDefinitions||[context.definition];
  if(annual&&context.ends)context={...context,end:context.ends[cik]??context.end};
  const cacheKey=JSON.stringify([context.dataset,context.publication,context.financialAsOf,cik,Boolean(context.ends),annual?"annual-profile":context.definition.metric_id,annual?definitions.map(item=>[item.metric_id,item.definition_version,item.unit]):context.definition.definition_version,annual?context.end:null]);
  const use=pending=>pending.then(entry=>{
    const selected=annual?entry[context.definition.metric_id]:entry;
    if(!selected||selected.error)throw new Error(selected?.error||"선택한 지표가 준비되지 않았습니다.");return selected;
  }).catch(error=>{if(companyTrend.cache.get(cacheKey)===pending)companyTrend.cache.delete(cacheKey);throw error});
  if(companyTrend.cache.has(cacheKey)){const pending=companyTrend.cache.get(cacheKey);companyTrend.cache.delete(cacheKey);companyTrend.cache.set(cacheKey,pending);return use(pending)}
  const path=annual?`/api/company-profile?${new URLSearchParams({dataset_id:context.dataset,dataset_publication_id:context.publication,cik,...(context.ends?{latest:"true"}:{fiscal_year:String(context.end)})})}`:`/api/quarter-series?${new URLSearchParams({dataset_id:context.dataset,dataset_publication_id:context.publication,cik,metric_id:context.definition.metric_id,limit:"8",...(context.ends?{latest:"true"}:{})})}`;
  const pending=(annual?readAnnualProfilePayload(context,cik,path):api(path)).then(payload=>{
    if(!annual)return validateCompanyTrendSeries(context,cik,payload);
    // One governed annual profile supplies the small five-metric display projection.
    return Object.fromEntries(definitions.map(definition=>{
      try{return[definition.metric_id,validateCompanyTrendSeries({...context,definition},cik,payload)]}
      catch(error){return[definition.metric_id,{error:error.message}]}
    }));
  });
  companyTrend.cache.set(cacheKey,pending);while(companyTrend.cache.size>16)companyTrend.cache.delete(companyTrend.cache.keys().next().value);return use(pending);
}
function companyTrendSlots(context,series){
  if(context.basis==="ANNUAL"){
    const years=series.flatMap(item=>item.preparedYears||[]).filter(year=>year<=context.end),fallback=context.annualYears.filter(year=>year<=context.end),earliest=Math.min(...(years.length?years:fallback));
    if(!Number.isFinite(earliest))return[];
    const start=Math.max(context.end-3,earliest);return Array.from({length:Math.max(0,context.end-start+1)},(_,index)=>({key:start+index,ordinal:start+index,label:`FY${start+index}`}));
  }
  const ending=context.end.match(/^(\d{4})Q([1-4])$/);if(!ending)throw new Error("종료 분기를 확인해 주세요.");
  const end=Number(ending[1])*4+Number(ending[2])-1,seen=new Set();
  return context.spine.map(row=>{
    if(!Number.isInteger(row.calendar_year)||![1,2,3,4].includes(row.calendar_quarter))throw new Error("준비된 분기 좌표가 올바르지 않습니다.");
    const key=periodCoordinate(row);if(seen.has(key))throw new Error("준비된 분기 좌표가 중복됩니다.");seen.add(key);return{key,ordinal:row.calendar_year*4+row.calendar_quarter-1,label:key,year:row.calendar_year,quarter:row.calendar_quarter};
  }).filter(row=>row.ordinal<=end).sort((a,b)=>a.ordinal-b.ordinal).slice(-8);
}
function alignCompanyTrend(context,results){
  const successful=results.filter(item=>!item.error),slots=companyTrendSlots(context,successful);
  return{context,slots,series:results.map((item,index)=>{
    const byCoordinate=new Map((item.rows||[]).map(row=>[context.basis==="ANNUAL"?row.fiscal_year:periodCoordinate(row),row]));
    return{...item,style:COMPANY_TREND_STYLES[index],points:slots.map(slot=>({slot,observation:(context.ends&&(context.ends[item.company.cik]===null||slot.key>context.ends[item.company.cik])?null:byCoordinate.get(slot.key))||{value:null,reason_labels:[item.error?"기업 자료를 불러오지 못했습니다.":"해당 기간에 준비된 자료가 없습니다."]}}))};
  })};
}
// User-approved ephemeral display normalization; cached monetary observations stay immutable.
function displayIndex100(value,base){
  const parts=input=>{const normalized=shiftDecimal(input,0),negative=normalized.startsWith("-"),[whole,fraction=""]=(negative?normalized.slice(1):normalized).split(".");return{negative,digits:BigInt(whole+fraction),scale:fraction.length}};
  const numerator=parts(value),denominator=parts(base);
  if(denominator.negative||denominator.digits===0n)throw new Error("기준값은 0보다 커야 합니다.");
  const dividend=numerator.digits*10n**BigInt(denominator.scale+4),divisor=denominator.digits*10n**BigInt(numerator.scale);
  let rounded=dividend/divisor;if((dividend%divisor)*2n>=divisor)rounded+=1n;
  const digits=rounded.toString().padStart(3,"0");return(numerator.negative&&rounded!==0n?"-":"")+digits.slice(0,-2)+"."+digits.slice(-2);
}
function buildCompanyTrendDisplay(model,requested="AMOUNT"){
  const eligible=observation=>observation?.availability_status==="AVAILABLE"&&!observation.quality_blocking&&observation.quality_status!=="BLOCK"&&observation.value!==null&&observation.value!==undefined;
  const baseIndex=requested==="INDEX100"?model.slots.findIndex((slot,index)=>model.series.length>=2&&model.series.every(series=>!series.error&&eligible(series.points[index].observation)&&compareExplorerDecimals(series.points[index].observation.value,"0")>0)):-1;
  const indexed=requested==="INDEX100"&&baseIndex>=0,reason=requested==="INDEX100"&&!indexed?"모든 선택 기업에 공표된 양수 기준값이 있는 공통 기간이 없어 실제 금액으로 표시합니다. 0·음수·미제공·조회 실패는 기준으로 쓰지 않습니다.":"";
  return{...model,effectiveScale:indexed?"INDEX100":"AMOUNT",baseSlot:indexed?model.slots[baseIndex]:null,reason,series:model.series.map(series=>({...series,points:series.points.map((point,index)=>({...point,beforeBase:indexed&&index<baseIndex,plotValue:indexed?(index<baseIndex||!eligible(point.observation)?null:displayIndex100(point.observation.value,series.points[baseIndex].observation.value)):eligible(point.observation)?point.observation.value:null}))}))};
}
function companyTrendPlotValue(point){return Object.hasOwn(point,"plotValue")?point.plotValue:point.observation.value}
function companyTrendPlotNumber(point,model){const value=companyTrendPlotValue(point);return Number(model.effectiveScale==="INDEX100"?value:shiftDecimal(value,-6))}
function companyTrendUnit(model){return model.effectiveScale==="INDEX100"?"지수 · 기준 100":"백만 USD"}
function companyTrendPointText(point,model){return model.effectiveScale==="INDEX100"?formatDecimal(companyTrendPlotValue(point),2)+" 지수 · 원금액 "+displayValue(point.observation.value,model.context.definition)+" 백만 USD":displayValue(point.observation.value,model.context.definition)+" 백만 USD"}
function companyTrendIndexCell(point,model){
  const value=companyTrendPlotValue(point),text=point.beforeBase?"기준 이전":value===null||value===undefined?"—":formatDecimal(value,2);
  return`<span class="display-number" title="${esc(text)} 지수 · 원값 ${esc(point.observation.value??"미제공")} USD" aria-label="${esc(text)} 지수"><span class="number-text">${esc(text)}</span><span class="number-clipped" aria-hidden="true">…</span></span><small>금액 ${explorerValue(point.observation,model.context.definition)} 백만 USD</small>`;
}
function applyCompanyTrendDisplay(){
  if(!companyTrend.model||$("#comparison-panel").hidden)return;
  const model=buildCompanyTrendDisplay(companyTrend.model,companyTrend.scale);companyTrend.displayModel=model;companyTrend.scale=model.effectiveScale;
  $("#comparison-trend-scale").value=model.effectiveScale;
  $("#comparison-trend-base").textContent=model.reason||(model.baseSlot?`공통 기준 ${model.baseSlot.label} = 100 · 각 기업의 해당 기간 양수 금액 대비`:"실제 금액 · 백만 USD");
  renderCompanyTrendValues(model);renderCompanyTrendPlot();
  $("#comparison-trend-retry").hidden=!companyTrend.model.series.some(series=>series.error);
}
function setCompanyTrendScale(scale){
  companyTrend.scale=scale==="INDEX100"?"INDEX100":"AMOUNT";
  if(companyTrend.model)applyCompanyTrendDisplay();
  else $("#comparison-trend-base").textContent=companyTrend.scale==="INDEX100"?"자료를 불러온 뒤 공통 양수 기준 기간을 확인합니다.":"실제 금액 · 백만 USD";
}
function resetCompanyTrendView(){
  companyTrend.baseMetric="revenue";companyTrend.scale="AMOUNT";$("#comparison-trend-scale").value="AMOUNT";
  const option=companyTrendMetricOptions().find(item=>item.base==="revenue");
  if(!option){$("#comparison-trend-base").textContent="현재 보기에 매출 지표가 없습니다.";return}
  const same=$("#comparison-trend-metric").value===option.definition.metric_id;$("#comparison-trend-metric").value=option.definition.metric_id;
  if($("#comparison-panel").hidden)return;
  if(same&&companyTrend.model)applyCompanyTrendDisplay();else loadCompanyTrend();
}

function companyTrendGeometry(model,width){
  const left=84,right=18,top=26,bottom=58,height=280,plotWidth=width-left-right,plotHeight=height-top-bottom;
  const values=model.series.flatMap(series=>series.points.filter(point=>companyTrendPlotValue(point)!==null&&companyTrendPlotValue(point)!==undefined).map(point=>companyTrendPlotNumber(point,model)));
  if(values.some(value=>!Number.isFinite(value)))throw new Error("그래프 범위를 표현할 수 없습니다. 정확한 값은 아래 표에서 확인해 주세요.");
  if(!values.length)return null;
  let min=Math.min(0,...values),max=Math.max(0,...values);if(min===max){min=-1;max=1}else{const pad=(max-min)*0.08;if(min<0)min-=pad;if(max>0)max+=pad}
  const first=model.slots[0].ordinal,last=model.slots.at(-1).ordinal,x=ordinal=>left+(ordinal-first)/Math.max(last-first,1)*plotWidth,y=value=>top+(max-value)/(max-min)*plotHeight;
  if(!Number.isFinite(max-min)||!Number.isFinite(max)||!Number.isFinite(min))throw new Error("그래프 범위를 표현할 수 없습니다. 정확한 값은 아래 표에서 확인해 주세요.");
  const references=model.effectiveScale==="INDEX100"?[0,100]:[0],ticks=[...new Set([min,(min+max)/2,max].filter(value=>references.includes(value)||references.every(reference=>Math.abs(y(value)-y(reference))>=18)).concat(references))].sort((a,b)=>a-b);
  const ordered=ticks.slice().sort((a,b)=>y(a)-y(b)),labelPositions=new Map();let previous=top-10;
  for(const tick of ordered){const position=Math.max(y(tick)+4,previous+14);labelPositions.set(tick,position);previous=position}
  const overflow=Math.max(0,previous-(height-bottom+4));for(const tick of ordered)labelPositions.set(tick,labelPositions.get(tick)-overflow);
  return{width,height,left,right,top,bottom,min,max,x,y,ticks,labelPositions,zero:y(0),reference:model.effectiveScale==="INDEX100"?y(100):null};
}
function renderCompanyTrendPlot(){
  const model=companyTrend.displayModel||companyTrend.model,chart=$("#comparison-trend-chart");if(!model||$("#comparison-panel").hidden)return;
  const width=Math.max(300,Math.floor(chart.getBoundingClientRect().width||600));
  try{
    const geometry=companyTrendGeometry(model,width);
    if(!geometry){chart.innerHTML='<p class="empty">선택한 기간에 표시할 수 있는 공표 값이 없습니다. 미제공은 0이 아닙니다.</p>';return}
    const {height,left,right,top,bottom,x,y}=geometry;
    const seenTicks=new Set();
    const grid=geometry.ticks.map(value=>{
      const label=model.effectiveScale==="INDEX100"?formatDecimal(String(value),2):displayValue(shiftDecimal(String(value),6),model.context.definition);
      const visible=!seenTicks.has(label);seenTicks.add(label);
      return `<g><line class="company-trend-grid" x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}"/>${visible?`<text class="company-trend-y" x="${left-8}" y="${geometry.labelPositions.get(value)}">${esc(label)}</text>`:""}</g>`;
    }).join("");
    const axis=model.slots.map(slot=>`<text class="company-trend-x" x="${x(slot.ordinal)}" y="${height-bottom+21}">${model.context.basis==="ANNUAL"?esc(slot.label):`<tspan x="${x(slot.ordinal)}">${slot.year}</tspan><tspan x="${x(slot.ordinal)}" dy="13">Q${slot.quarter}</tspan>`}</text>`).join("");
    const lines=model.series.map(series=>{
      const points=series.points.map(point=>companyTrendPlotValue(point)===null||companyTrendPlotValue(point)===undefined?null:{...point,x:x(point.slot.ordinal),y:y(companyTrendPlotNumber(point,model))});
      const segments=points.slice(1).map((point,index)=>point&&points[index]&&point.slot.ordinal===points[index].slot.ordinal+1?`<line x1="${points[index].x}" y1="${points[index].y}" x2="${point.x}" y2="${point.y}"/>`:"").join("");
      const circles=points.filter(Boolean).map(point=>`<circle cx="${point.x}" cy="${point.y}" r="3.5"><title>${esc(series.company.ticker||series.company.name)} · ${esc(point.slot.label)} · ${esc(companyTrendPointText(point,model))} · 원값 ${esc(point.observation.value)} USD · ${esc(actualPeriod(point.observation))}${model.context.basis!=="ANNUAL"?" · "+esc(fiscalLabel(point.observation)):""}</title></circle>`).join("");
      return`<g class="company-trend-series" data-cik="${esc(series.company.cik)}" stroke="${series.style.color}" stroke-dasharray="${series.style.dash}" fill="${series.style.color}">${segments}${circles}</g>`;
    }).join("");
    chart.innerHTML=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(explorerMetricCaption(model.context.definition))} · 선택 기업 ${model.series.length}개 · ${model.slots.length}개 기간 · 단위 ${esc(companyTrendUnit(model))}. 값과 실제 기간은 아래 표를 확인해 주세요."><text class="company-trend-unit" x="${left}" y="14">${esc(companyTrendUnit(model))}</text>${grid}<line class="company-trend-zero" x1="${left}" x2="${width-right}" y1="${geometry.zero}" y2="${geometry.zero}"/>${geometry.reference!==null?`<line class="company-trend-reference" x1="${left}" x2="${width-right}" y1="${geometry.reference}" y2="${geometry.reference}"/>`:""}${axis}${lines}</svg>`;
  }catch(error){chart.innerHTML=`<p class="message error">${esc(error.message)}</p>`}
}
function renderCompanyTrendValues(model){
  $("#comparison-trend-legend").innerHTML=model.series.map(series=>`<li><svg width="30" height="12" aria-hidden="true"><line x1="0" x2="30" y1="6" y2="6" stroke="${series.style.color}" stroke-width="2" stroke-dasharray="${series.style.dash}"/></svg><span><strong>${esc(series.company.ticker||series.company.cik)}</strong> ${esc(series.company.name||"")}${series.error?`<small class="company-trend-error">조회 실패: ${esc(series.error)}</small>`:""}</span></li>`).join("");
  $("#comparison-trend-values").innerHTML=`<details><summary>공표 값과 기업별 실제 기간 · ${model.slots.length}개 기간</summary><table><thead><tr><th>${model.context.basis==="ANNUAL"?"회계연도":"종료 분기"}</th>${model.series.map(series=>`<th>${esc(series.company.ticker||series.company.name)}<small>${esc(companyTrendUnit(model))}</small></th>`).join("")}</tr></thead><tbody>${model.slots.map((slot,index)=>`<tr><th>${esc(slot.label)}</th>${model.series.map(series=>{const point=series.points[index],observation=point.observation;return`<td>${model.effectiveScale==="INDEX100"?companyTrendIndexCell(point,model):explorerValue(observation,model.context.definition)}<small>${esc(actualPeriod(observation))}${model.context.basis!=="ANNUAL"?" · "+esc(fiscalLabel(observation)):""}</small></td>`}).join("")}</tr>`).join("")}</tbody></table></details>`;
}
async function loadCompanyTrend(){
  const token=++companyTrend.token;companyTrend.model=null;companyTrend.displayModel=null;$("#comparison-trend-retry").disabled=true;$("#comparison-trend-chart").replaceChildren();$("#comparison-trend-values").replaceChildren();$("#comparison-trend-legend").replaceChildren();
  const section=$("#comparison-trend");section.setAttribute("aria-busy","true");$("#comparison-trend-status").textContent="선택 기업의 같은 지표 흐름을 불러오는 중입니다…";
  let context;
  try{
    context=companyTrendContext($("#comparison-trend-metric").value);
    const results=await Promise.all(context.ciks.map(cik=>cachedCompanyTrendSeries(context,cik).catch(error=>({company:context.companies.find(item=>item.cik===cik)||{cik,ticker:cik},error:error.message}))));
    if(!companyTrendOwns(context,token))return;
    const model=alignCompanyTrend(context,results);companyTrend.model=model;applyCompanyTrendDisplay();
    const failed=results.filter(item=>item.error).length;
    $("#comparison-trend-status").textContent=`${explorerBasisLabel()} · 종료 ${context.basis==="ANNUAL"?"FY"+context.end:context.end} · 공표된 ${model.slots.length}개 기간${failed?` · ${failed}개 기업 조회 실패`:""}`;
  }catch(error){if(token===companyTrend.token&&!$("#comparison-panel").hidden&&(!context||context.explorerKey===explorerContextKey())){$("#comparison-trend-status").textContent=error.message;$("#comparison-trend-retry").hidden=false}}
  finally{if(token===companyTrend.token){section.setAttribute("aria-busy","false");$("#comparison-trend-retry").disabled=false}}
}
function mountCompanyTrend(userOpened=true){
  if(!$("#comparison-trend")){
    const section=document.createElement("section");section.id="comparison-trend";section.className="company-trend";
    section.innerHTML='<div class="company-trend-heading"><h3>선택 기업 추이 비교</h3><label>추이 지표<select id="comparison-trend-metric"></select></label><label>표시 방식<select id="comparison-trend-scale"><option value="AMOUNT">실제 금액</option><option value="INDEX100">공통 기준 100</option></select></label></div><p id="comparison-trend-base" class="muted" aria-live="polite"></p><div class="company-trend-actions"><button type="button" id="comparison-trend-reset" class="quiet">차트 보기 초기화</button><button type="button" id="comparison-trend-retry" class="quiet" hidden>실패한 자료 다시 읽기</button></div><p id="comparison-trend-status" role="status" aria-live="polite"></p><ul id="comparison-trend-legend" class="company-trend-legend"></ul><div id="comparison-trend-chart" class="company-trend-chart"></div><div id="comparison-trend-values"></div><p class="muted">기업마다 실제 재무기간이 다를 수 있습니다. 값이 없는 기간은 선을 연결하지 않습니다.</p>';
    $("#comparison-panel .section-head").after(section);
    section.addEventListener("toggle",()=>scheduleTablePresentation(section),true);
    $("#comparison-trend-metric").onchange=()=>{companyTrend.baseMetric=$("#comparison-trend-metric").value.replace(/^(quarter_|ttm_)/,"");loadCompanyTrend()};
    $("#comparison-trend-scale").onchange=()=>setCompanyTrendScale($("#comparison-trend-scale").value);
    $("#comparison-trend-reset").onclick=resetCompanyTrendView;$("#comparison-trend-retry").onclick=()=>loadCompanyTrend();
    if(typeof ResizeObserver!=="undefined"){
      companyTrend.resizeObserver=new ResizeObserver(()=>{if(!companyTrend.frame)companyTrend.frame=requestAnimationFrame(()=>{companyTrend.frame=0;renderCompanyTrendPlot()})});
      companyTrend.resizeObserver.observe($("#comparison-trend-chart"));
    }
  }
  const options=companyTrendMetricOptions();$("#comparison-trend-metric").innerHTML=options.map(item=>`<option value="${item.definition.metric_id}">${esc(item.label)}</option>`).join("");
  const selected=options.find(item=>item.base===companyTrend.baseMetric)||options.find(item=>item.base==="revenue")||options[0];
  $("#comparison-trend-scale").value=companyTrend.scale;$("#comparison-trend-metric").disabled=!selected;
  if(selected){$("#comparison-trend-metric").value=selected.definition.metric_id;loadCompanyTrend()}
  else{invalidateCompanyTrend();$("#comparison-trend-status").textContent="이 보기에는 공통 금액 흐름 지표가 준비되지 않았습니다."}
  arrangeComparisonAnalysis();
  if(userOpened){$("#comparison-trend").scrollIntoView({block:"start"});$("#comparison-trend-metric").focus({preventScroll:true})}
}

// One selection transition for checkboxes, filtered-independent chips, and both clear controls.
const explorerSelection={registry:new Map(),mounted:false,message:""};
function registerExplorerCompanies(companies){const dataset=explorerDataset()?.dataset_id;for(const company of companies)explorerSelection.registry.set(`${dataset}:${company.cik}`,{cik:company.cik,ticker:company.ticker,name:company.name})}
function explorerSelectedCompany(cik){return explorerSelection.registry.get(`${explorerDataset()?.dataset_id}:${cik}`)||{cik,ticker:cik,name:""}}
function comparisonFocusReturn(){const button=$("#compare-selected"),target=!button.disabled&&button.isConnected!==false?button:$("#explorer-query");target.focus({preventScroll:true})}
function closeExplorerComparison(returnFocus=true){
  invalidateComparisonMulti();
  invalidateCompanyTrend();explorerBasis.comparisonToken++;$("#comparison-panel").hidden=true;$("#comparison-result").replaceChildren();
  cancelComparisonRefresh();leaveExplorerAnalysis("COMPARE",returnFocus);
  if(returnFocus)comparisonFocusReturn();
}
function syncExplorerSelectionUI(){
  $$('[data-explorer-select]').forEach(input=>input.checked=S.explorerSelected.has(input.dataset.explorerCik));
  if(!explorerSelection.mounted)return;
  const count=S.explorerSelected.size;
  $("#explorer-selection-tray").hidden=count===0;
  $("#compare-selected").hidden=count<2;
  const hint=$(".compare-hint");if(hint)hint.hidden=count>0;
  $("#explorer-selection-count").textContent=`선택 기업 ${count}/4`;
  $("#explorer-selection-status").textContent=explorerSelection.message||(count<2?"기업을 2~4개 선택하면 비교할 수 있습니다.":"필터로 보이지 않는 선택 기업도 비교에 포함됩니다.");
  $("#explorer-selection-list").innerHTML=[...S.explorerSelected].map(cik=>{const company=explorerSelectedCompany(cik);return`<li><button type="button" class="quiet" data-remove-explorer-cik="${esc(cik)}" aria-label="${esc(company.ticker||company.name)} 선택 해제"><strong>${esc(company.ticker)}</strong> ${esc(company.name)} <span aria-hidden="true">×</span></button></li>`}).join("");
  $$('[data-remove-explorer-cik]').forEach(button=>button.onclick=()=>transitionExplorerSelection("remove",button.dataset.removeExplorerCik,false,null,button));
  $("#explorer-selection-clear").disabled=count===0;$("#comparison-selection-clear").disabled=count===0;
}
function transitionExplorerSelection(action,cik=null,checked=false,company=null,origin=null){
  const selected=S.explorerSelected,adding=action==="toggle"&&checked&&!selected.has(cik),before=[...selected].sort().join(","),wasOpen=!$("#comparison-panel").hidden;
  if(adding&&selected.size>=4){explorerSelection.message="최대 4개 기업까지 비교할 수 있습니다. 새 선택은 적용하지 않았습니다.";syncExplorerSelectionUI();return{accepted:false,changed:false}}
  if(action==="clear")selected.clear();else if(action==="remove"||!checked)selected.delete(cik);else if(action==="toggle"&&cik){selected.add(cik);if(company)registerExplorerCompanies([company])}
  explorerSelection.message="";const changed=before!==[...selected].sort().join(",");updateCompareButton();
  if(!changed)return{accepted:true,changed:false};
  explorerBasis.comparisonToken++;invalidateCompanyTrend();$("#comparison-result").textContent=selected.size>=2?(comparisonPicker.mounted?"기업 선택이 변경되어 비교를 갱신합니다…":"기업 선택이 변경되었습니다. 표를 보려면 ‘재무기간 비교’를 다시 눌러 주세요."):"";
  if(selected.size<2){closeExplorerComparison(false);if(wasOpen&&origin?.closest?.("#comparison-panel"))comparisonFocusReturn()}
  else if(wasOpen){mountCompanyTrend(false);renderComparisonMetricPicker();queueComparisonRefresh()}
  if(origin?.matches?.("[data-remove-explorer-cik]")){
    const next=$("#explorer-selection-list button")||$("#explorer-selection-clear");(selected.size?next:$("#explorer-query")).focus({preventScroll:true});
  }
  if(selected.size===0&&origin)$("#explorer-query").focus({preventScroll:true});
  return{accepted:true,changed:true};
}
function mountExplorerSelection(){
  const tray=document.createElement("section");tray.id="explorer-selection-tray";tray.className="explorer-selection-tray";tray.hidden=true;
  tray.innerHTML='<div class="selection-tray-heading"><strong id="explorer-selection-count"></strong><button id="explorer-selection-clear" type="button" class="quiet">선택 모두 해제</button></div><ul id="explorer-selection-list"></ul><p id="explorer-selection-status" role="status" aria-live="polite"></p>';
  $("#explorer-count").closest(".explorer-summary").after(tray);
  const clear=document.createElement("button");clear.id="comparison-selection-clear";clear.type="button";clear.className="quiet";clear.textContent="선택 모두 해제";$("#close-comparison").before(clear);
  $("#explorer-selection-clear").onclick=()=>transitionExplorerSelection("clear",null,false,null,$("#explorer-selection-clear"));
  clear.onclick=()=>transitionExplorerSelection("clear",null,false,null,clear);
  $("#close-comparison").textContent="비교 닫기";$("#close-comparison").onclick=()=>closeExplorerComparison();
  $("#comparison-panel").addEventListener("keydown",event=>{if(event.key==="Escape"){event.preventDefault();event.stopPropagation();closeExplorerComparison()}});
  explorerSelection.mounted=true;syncExplorerSelectionUI();
}

function resetExplorerBatch(snapshot){
  const dataset=snapshot?batchView.datasets.find(item=>item.dataset_id===snapshot.dataset_id):S.defaultDataset;
  if(!dataset||(snapshot&&dataset.publication_id!==snapshot.publication_id))throw new Error("등록된 배치와 자료 발행물이 다릅니다.");
  invalidateExplorerDetails();
  S.explorerSelected.clear();S.explorerDataset=dataset;S.explorerYear=null;S.explorer=null;S.explorerCatalog=null;
  explorerBasis.inventoryKey=null;explorerBasis.inventory=null;explorerBasis.snapshots.clear();
  explorerBasis.periods={QUARTERLY:null,TTM:null};explorerBasis.latestAnnual=Boolean(snapshot);
  explorerBasis.basis="ANNUAL";$("#explorer-basis").value="ANNUAL";
  $("#explorer-preset option[value='ALL']")?.remove();
  for(const option of $("#explorer-preset").options){
    option.textContent=explorerBasis.annualPresetLabels?.[option.value]||option.textContent;
  }
  $("#explorer-preset").value=explorerBasis.views.ANNUAL?.preset||"CORE";
  $("#explorer-year").closest("label").hidden=false;$("#explorer-quarter").closest("label").hidden=true;
  batchView.snapshot=snapshot;batchView.fixedOnly=!snapshot;
  $("#batch-use-screen").disabled=!snapshot;
}
function renderAppliedBatch(){
  const snapshot=batchView.snapshot;
  const actual=snapshot?.mode==="ACTUAL";
  const mode=actual?"확보 기록 기준":snapshot?"준비된 자료로 가정":batchView.fixedOnly?"제공 자료에서 기간 선택":"";
  $("#batch-applied-summary").textContent=mode?`적용 중 · ${mode}`:"적용된 자료 기준 없음";
  const cutoff=snapshot?.financial_as_of||(batchView.fixedOnly?S.defaultDataset.financial_as_of:null);
  const meta=actual?`판단일 ${snapshot.decision_date} · 사용지연 ${snapshot.lag}거래일 · 재무 기준일 ${cutoff}`
    :cutoff?`재무 기준일 ${cutoff}${snapshot?" · 실제 확보 이력 미반영":""}`:"";
  $("#batch-applied-meta").textContent=meta;
  const proof=$("#batch-ready-proof");
  proof.hidden=!actual;
  proof.textContent=actual?`뉴욕 ${new Date(snapshot.ready_at).toLocaleString("ko-KR",{timeZone:"America/New_York"})} 조회 가능 확인`:"";
  $("#batch-use-screen").hidden=!snapshot;
  $("#batch-cancel").hidden=!(snapshot||batchView.fixedOnly);
}
function closeBatchEditor(focus=false){
  $("#batch-editor").open=false;
  if(focus)$("#batch-editor-summary").focus({preventScroll:true});
}
async function applyBatchChoice({focus=false}={}){
  const token=++batchView.token,mode=$("#batch-mode").value;
  const params=new URLSearchParams({mode});
  if(mode==="PREPARED_SIMULATION")params.set("dataset_id",$("#batch-dataset").value);
  else if(mode==="ACTUAL"){
    if($("#batch-date").value)params.set("decision_date",$("#batch-date").value);
    params.set("lag",$("#batch-lag").value||"0");
  }
  const status=$("#batch-status"),editor=$("#batch-editor");
  status.textContent="자료 기준을 확인하는 중입니다…";
  $("#batch-apply").disabled=true;$("#batch-cancel").disabled=true;$("#batch-use-screen").disabled=true;
  status.classList.toggle("explorer-error",false);
  try{
    try{
      const snapshot=mode==="PROVIDED_FIXED"?null:await api(`/api/batch-availability?${params}`);
      if(token!==batchView.token)return;
      resetExplorerBatch(snapshot);
      renderAppliedBatch();
    }catch(error){
      if(token===batchView.token){
        const message=error.message.includes("no verified batch")?"선택한 날짜에 확인된 실제 배치가 없습니다. 다른 날짜나 자료 기준을 선택할 수 있습니다.":error.message;
        const retained=batchView.snapshot||batchView.fixedOnly;
        status.textContent=retained?`${message} · 적용 중인 자료 기준을 유지했습니다.`:message;
        status.classList.toggle("explorer-error",true);
        editor.open=true;
      }
      return;
    }

    status.textContent="선택한 자료의 기업표를 불러오는 중입니다…";
    await loadExplorer();
    if(token!==batchView.token)return;
    if(explorerBasis.readyKey===explorerContextKey()){
      status.textContent="";
      closeBatchEditor(focus);
    }else{
      status.textContent="자료 기준을 적용했습니다. 기업표를 불러오지 못했습니다.";
      status.classList.toggle("explorer-error",true);
      editor.open=true;
    }
    if(S.explorerYear)await loadLibrary().catch(error=>explorerNotice(error.message,true));
    ensureExplorerInventory();
  }finally{
    if(token===batchView.token){
      $("#batch-apply").disabled=false;$("#batch-cancel").disabled=false;
      $("#batch-use-screen").disabled=!batchView.snapshot;
    }
  }
}

function batchDatasetCaption(dataset){
  const count=dataset.company_count??dataset.counts?.companies;
  const scope=dataset.quarter_definition_count>0?"연간·분기·TTM":"연간";
  return [dataset.financial_as_of,Number.isInteger(count)?`${count}개 기업`:null,scope].filter(Boolean).join(" · ");
}
function mountBatchAvailability(status){
  if(!status.batch_availability)return;
  batchView.enabled=true;batchView.datasets=status.datasets.filter(item=>item.definition_count||item.quarter_definition_count);
  if(!batchView.datasets.length){batchView.enabled=false;return}
  const panel=document.createElement("div");
  panel.className="batch-source";
  panel.innerHTML=`<details id="batch-editor" class="workflow-disclosure" open>
    <summary id="batch-editor-summary"><strong id="batch-applied-summary">적용된 자료 기준 없음</strong><small id="batch-applied-meta"></small><span class="batch-change-label">자료 기준 변경</span></summary>
    <div class="batch-availability">
      <label>자료 기준<select id="batch-mode"><option value="ACTUAL">확보 기록 기준</option><option value="PREPARED_SIMULATION">준비된 자료로 가정</option><option value="PROVIDED_FIXED">제공 자료에서 기간 선택</option></select></label>
      <label>준비 자료<select id="batch-dataset">${batchView.datasets.map(item=>`<option value="${esc(item.dataset_id)}">${esc(batchDatasetCaption(item))}</option>`).join("")}</select></label>
      <label>판단일 (뉴욕, 비우면 오늘)<input id="batch-date" type="date"></label>
      <label>사용지연 (미국 거래일)<input id="batch-lag" type="number" min="0" step="1" value="0"></label>
      <p id="batch-ready-proof" hidden></p>
      <p id="batch-help"></p>
      <div class="batch-editor-actions"><button id="batch-apply" type="button">적용</button><button id="batch-cancel" type="button" class="quiet" hidden>취소</button></div>
      <p id="batch-status" role="status"></p>
    </div>
  </details>
  <button id="batch-use-screen" type="button" class="quiet" hidden>이 기준으로 스크리닝</button>`;
  $(".explorer-tools").before(panel);
  panel.addEventListener("toggle",fitDesktopExplorerList,true);
  $("#explorer-asof").closest(".year-context").hidden=true;
  const note=document.createElement("p");note.id="screen-batch-status";note.className="muted";note.hidden=true;
  $("#period-mode").closest("label").after(note);
  const toggle=()=>{
    const mode=$("#batch-mode").value,actual=mode==="ACTUAL";
    $("#batch-dataset").closest("label").hidden=mode!=="PREPARED_SIMULATION";
    for(const id of ["#batch-date","#batch-lag"])$(id).closest("label").hidden=!actual;
    $("#batch-help").textContent=actual?"판단일까지 확보가 확인된 자료를 사용합니다. 재무 기준일은 공시 자료의 범위입니다."
      :mode==="PREPARED_SIMULATION"?"선택한 발행물의 재무 기준일을 사용합니다. 과거 실제 확보 여부는 반영하지 않습니다."
      :"현재 제공되는 자료에서 회계연도 또는 종료 분기를 직접 고릅니다.";
  };
  $("#batch-mode").value="ACTUAL";
  $("#batch-dataset").value=batchView.datasets.at(-1).dataset_id;
  $("#batch-mode").onchange=toggle;
  $("#batch-apply").onclick=()=>applyBatchChoice({focus:true});
  $("#batch-cancel").onclick=()=>{
    const snapshot=batchView.snapshot;
    $("#batch-mode").value=snapshot?.mode||"PROVIDED_FIXED";
    if(snapshot)$("#batch-dataset").value=snapshot.dataset_id;
    $("#batch-date").value=snapshot?.decision_date||"";
    $("#batch-lag").value=String(snapshot?.lag??0);
    $("#batch-status").textContent="";toggle();closeBatchEditor(true);
  };
  toggle();
  $("#batch-use-screen").onclick=()=>{if(batchView.snapshot)withBusy(async()=>{await newScreen();showView("screening",true)}).catch(fail)};
}
async function boot(){mountScreeningPresentation();mountJournalHistory();const s=await api("/api/status"),d=s.datasets.at(-1),explorer=d;S.defaultDataset=d;S.explorerDataset=explorer;$("#dataset").innerHTML=s.datasets.map(x=>`<option value="${x.dataset_id}">${x.dataset_id}</option>`).join("");$("#dataset").value=d.dataset_id;$("#asof").textContent=d.financial_as_of;await loadInputContext(d.dataset_id);await refreshScreens();await refreshRuns();await refreshDecisions();$("#predicates").innerHTML="";predicateRow();renderTimeline();syncResultActions();mountAdmin();bindExplorer();mountBatchAvailability(s);if(batchView.enabled){await applyBatchChoice();if(batchView.snapshot){S.screenAvailability=batchView.snapshot;$("#dataset").value=batchView.snapshot.dataset_id;$("#asof").textContent=batchView.snapshot.financial_as_of;await loadInputContext(batchView.snapshot.dataset_id);$("#predicates").replaceChildren();predicateRow();syncScreenPeriodModes();$("#period-mode").value=LATEST_ANNUAL_POLICY;togglePeriod()}}else{await loadExplorer();await loadLibrary()}const initial=({"#library-title":"library","#criteria-title":"screening","#results-title":"screening","#history-title":"history"})[location.hash]||"explorer";showView(initial);$("#criteria-form").addEventListener("input",e=>{if(isRevisionEdit(e.target))markDirty()});$("#criteria-form").addEventListener("change",e=>{if(isRevisionEdit(e.target))markDirty()})}
$("#add-predicate").onclick=()=>{predicateRow();markDirty()};$("#metric-category").onchange=refreshMetricOptions;$("#metric-search").oninput=refreshMetricOptions;$("#company-query").oninput=renderCompanyOptions;$("#company-select").onchange=syncCompanySelection;$("#universe-mode").onchange=toggleUniverse;$("#period-mode").onchange=togglePeriod;$("#frequency").onfocus=()=>{S.frequencyDrafts[S.frequency]={content:revisionContent(),name:$("#screen-name").value,revision:S.revision,dirty:S.dirty,dataset:{dataset_id:$("#dataset").value,financial_as_of:$("#asof").textContent}}};$("#frequency").onchange=()=>withBusy(switchFrequency).catch(fail);
async function openSavedScreenRecord(record,datasetId=null){const epoch=journalHistory.epoch,dependency=Boolean(datasetId);if(!record)return;if(!dependency&&historyHidden("REVISION",record.revision_id))throw new Error("휴지통에서 조건을 복원한 뒤 다시 열어 주세요.");if(!datasetId){record=await api(`/api/saved-conditions/${record.revision_id}`);datasetId=record.open_dataset_id||$("#dataset").value||S.defaultDataset.dataset_id;}if(epoch!==journalHistory.epoch)return;clearResult();$("#dataset").value=datasetId;await loadInputContext(datasetId);if(epoch!==journalHistory.epoch)return;const quarterly=quarterlyScreenPolicy(record.content.period_policy);$("#frequency").value=quarterly?"QUARTERLY":"ANNUAL";if(quarterly){const [catalog,periods]=await Promise.all([api(`/api/quarter-metric-catalog?dataset_id=${encodeURIComponent(datasetId)}`),api(`/api/quarter-periods?dataset_id=${encodeURIComponent(datasetId)}`)]);S.catalog=catalog;S.quarterSpine=periods.spine;$("#calendar-quarter").innerHTML=periods.spine.map(x=>`<option value="${x.calendar_year}Q${x.calendar_quarter}">${quarterLabel(x)}</option>`).join("")}if(epoch!==journalHistory.epoch)return;loadScreenRecord(record);$("#saved-screen").value=record.revision_id;setCriteriaCompact(false);if(record.context_origin==="UNKNOWN")toast("과거 저장 자료를 확인할 수 없어 현재 선택 자료로 조건을 열었습니다.");else if(record.context_origin==="HISTORICAL_RUN")toast("이 조건의 과거 실행 자료로 열었습니다.");showView("screening",true)}
$("#open-screen").onclick=()=>withBusy(async()=>{const record=S.screens.find(x=>x.revision_id===$("#saved-screen").value);if(!record)throw new Error("저장 조건 버전을 선택해 주세요.");await openSavedScreenRecord(record)}).catch(fail);
$("#save-result").onclick=()=>withBusy(saveResult).catch(fail);
async function newScreen(){clearResult();S.frequencyDrafts={};const d=batchView.snapshot?S.explorerDataset:S.defaultDataset;S.screenAvailability=batchView.snapshot;$("#new-screen").disabled=true;try{$("#frequency").value="ANNUAL";S.frequency="ANNUAL";$("#dataset").value=d.dataset_id;$("#asof").textContent=d.financial_as_of;await loadInputContext(d.dataset_id);syncScreenPeriodModes();if(S.screenAvailability)$("#period-mode").value=LATEST_ANNUAL_POLICY;togglePeriod();S.revision=null;S.companySelection.clear();renderCompanyOptions();S.dirty=false;$("#saved-screen").value="";$("#screen-name").readOnly=false;$("#screen-name").value="";$("#screen-context").textContent="새 조건";$("#save-state").textContent="새 조건";$("#predicates").innerHTML="";predicateRow();setCriteriaCompact(false);$("#screen-name").focus()}finally{$("#new-screen").disabled=false}}$("#new-screen").onclick=()=>withBusy(()=>newScreen()).catch(fail);$("#save-screen").onclick=()=>withBusy(()=>saveScreen()).catch(fail);$("#execute").onclick=()=>withBusy(()=>execute()).catch(fail);$("#toggle-criteria").onclick=()=>setCriteriaCompact(!$(".criteria").classList.contains("compact"));$("#show-all").onchange=renderRows;$$('[data-filter]').forEach(x=>x.onclick=()=>{$$('[data-filter]').forEach(y=>y.classList.remove("active"));x.classList.add("active");S.activeFilter=x.dataset.filter;renderRows()});$("#toggle-history").onclick=()=>{const c=$("#history-content"),o=c.hidden;c.hidden=!o;$("#toggle-history").setAttribute("aria-expanded",String(o));$("#toggle-history").textContent=o?"이력 닫기":"이력 보기"};$("#open-run").onclick=()=>withBusy(()=>openRun($("#old-run").value)).catch(fail);$("#compare-runs").onclick=()=>compareRuns().catch(fail);$("#export-selected-csv").onclick=()=>withBusy(()=>exportRun("SELECTED","csv")).catch(fail);$("#export-full-xlsx").onclick=()=>withBusy(()=>exportRun("FULL","xlsx")).catch(fail);$("#export-full-csv").onclick=()=>withBusy(()=>exportRun("FULL","csv")).catch(fail);$("#export-selected-xlsx").onclick=()=>withBusy(()=>exportRun("SELECTED","xlsx")).catch(fail);$("#evidence-metric").onchange=()=>renderMetricEvidence().catch(fail);$("#compare-peer").onclick=()=>comparePeer().catch(fail);$("#save-decision").onclick=()=>withBusy(saveDecision).catch(fail);$("#close-evidence").onclick=()=>{const c=$("#evidence").dataset.cik;$("#evidence").hidden=true;($(`[data-open="${c}"]`)||S.lastFocus)?.focus()};$("#evidence").addEventListener("keydown",e=>{if(e.key==="Escape"){$("#close-evidence").click();return}if(e.key!=="Tab")return;const f=$$("#evidence button:not([disabled]),#evidence select:not([disabled]),#evidence textarea:not([disabled])"),a=f[0],b=f.at(-1);if(e.shiftKey&&document.activeElement===a){e.preventDefault();b.focus()}else if(!e.shiftKey&&document.activeElement===b){e.preventDefault();a.focus()}});boot().catch(fail);

// Presentation-only enhancement. No requests, selection changes, or saved-record writes.
function tablePresentationRole(table){
  if(table.closest(".explorer-matrix"))return"explorer";
  if(table.closest(".workspace"))return"results";
  if(table.closest("#comparison-result,#comparison-trend-values"))return"comparison";
  if(table.closest("#peer-comparison"))return"peer";
  if(table.closest("#series-content,#profile-series"))return"series";
  return null;
}
function prepareDisplayTable(table){
  const role=tablePresentationRole(table);if(!role)return;
  table.classList.add("display-table");
  if(!table.closest(".table-wrap,.display-table-scroll")){
    const wrap=document.createElement("div");wrap.className="display-table-scroll";
    table.before(wrap);wrap.append(table);
  }
  const headings=[...table.tHead?.rows[0]?.cells||[]],style=getComputedStyle(table),width=name=>parseFloat(style.getPropertyValue(name));
  const roles=displayTableColumnRoles(role,headings);
  const widths=roles.map(kind=>kind==="hidden"?0:kind==="status"?width("--status-column"):kind==="context"?(role==="series"?92:112):kind==="number"&&role==="comparison"?188:width({select:"--select-column",company:"--company-column",period:"--period-column",number:"--number-column",label:"--label-column"}[kind]));
  let group=table.querySelector(":scope > colgroup");
  if(!group){group=document.createElement("colgroup");table.prepend(group)}
  if(group.children.length!==widths.filter(Boolean).length){group.replaceChildren(...widths.filter(Boolean).map(()=>document.createElement("col")))}
  widths.filter(Boolean).forEach((value,index)=>group.children[index].style.width=value+"px");
  table.style.setProperty("--display-table-width",widths.reduce((a,b)=>a+b,0)+"px");
  for(const row of table.rows){
    if(row.cells.length!==headings.length||row.cells[0]?.colSpan>1)continue;
    [...row.cells].forEach((cell,index)=>{
      const kind=roles[index];cell.classList.toggle("numeric",kind==="number");
      cell.classList.toggle("frozen-select",kind==="select");cell.classList.toggle("frozen-company",kind==="company");
      cell.classList.toggle("frozen-label",kind==="label");cell.classList.toggle("period-cell",kind==="period");
      if(kind==="period"&&!cell.dataset.displayPeriod){if(!cell.querySelector("[data-financial-date]"))cell.textContent=cell.textContent.replace(" ~ ","\n~ ");cell.dataset.displayPeriod="true"}
      if(row.parentElement.tagName==="THEAD"&&role==="comparison"&&index>0&&!cell.querySelector(".company-caption")){
        const text=cell.firstChild;if(text?.nodeType===Node.TEXT_NODE){const label=document.createElement("span");label.className="company-caption";label.textContent=text.textContent;cell.replaceChild(label,text)}
        cell.querySelectorAll("small").forEach(x=>{x.classList.add("period-caption");const text=x.textContent.replace(" ~ ","\n~ ");if(!x.querySelector("[data-financial-date]")&&x.textContent!==text)x.textContent=text});
      }
    });
  }
  const check=table.querySelector("tbody .frozen-select,thead .frozen-select");
  table.style.setProperty("--actual-select-width",(check?.getBoundingClientRect().width||0)+"px");
}
function visibleNumberFragment(rect,left,right){
  const start=Math.max(rect.left,left),end=Math.min(rect.right,right);
  return{clipped:rect.left<left-0.5||rect.right>right+0.5,visible:end-start>=14,markLeft:Math.max(0,end-rect.left-14)};
}
function maskPartialNumbers(table){
  if(table.closest("[hidden]")||!table.getClientRects().length)return;
  const wrap=table.closest(".table-wrap,.display-table-scroll"),view=wrap.getBoundingClientRect(),drawer=table.closest("aside")?.getBoundingClientRect();
  let left=Math.max(view.left,drawer?.left||0,0),right=Math.min(view.right,drawer?.right||Infinity,document.documentElement.clientWidth);
  for(const cell of table.querySelectorAll("tbody .frozen-select,tbody .frozen-company,tbody .frozen-label")){
    left=Math.max(left,cell.getBoundingClientRect().right);if(cell.classList.contains("frozen-company")||cell.classList.contains("frozen-label"))break;
  }
  for(const number of table.querySelectorAll("td.numeric .display-number")){
    const rect=number.getBoundingClientRect(),cell=number.closest("td").getBoundingClientRect(),fragment=visibleNumberFragment(rect,Math.max(left,cell.left+4),Math.min(right,cell.right-4));
    number.classList.toggle("is-clipped",fragment.clipped);number.toggleAttribute("data-visible-fragment",fragment.visible);
    number.style.setProperty("--clip-mark-left",fragment.markLeft+"px");
  }
}
const presentationQueue=new Set();let presentationFrame=0;
function scheduleTablePresentation(root=document){
  if(root.matches?.("table"))presentationQueue.add(root);
  else root.querySelectorAll?.("table").forEach(table=>presentationQueue.add(table));
  if(!presentationFrame)presentationFrame=requestAnimationFrame(()=>{
    presentationFrame=0;const tables=[...presentationQueue];presentationQueue.clear();
    tables.filter(table=>table.isConnected&&!table.closest("[hidden]")).forEach(table=>{prepareDisplayTable(table);maskPartialNumbers(table)});
  });
}
new MutationObserver(records=>{
  for(const record of records){const table=record.target.closest?.("table");scheduleTablePresentation(table||document)}
}).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["hidden"]});
document.addEventListener("scroll",event=>{
  const root=event.target===document?document:event.target;
  if(root===document||root.matches?.(".table-wrap,.display-table-scroll,aside"))scheduleTablePresentation(root);
},true);
window.addEventListener("resize",()=>scheduleTablePresentation());
scheduleTablePresentation();
