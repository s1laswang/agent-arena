const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct=v=>v==null?"n/a":(v*100).toFixed(0)+"%";
const num=v=>v==null?"n/a":Number(v).toFixed(2);
async function get(u){const r=await fetch(u);if(!r.ok)throw new Error(u);return r.json()}
const NEED=[["Gemini 4 Carbon",/gemini 4 carbon/i],["Claude",/claude/i],["Codex",/codex/i]];
const canon=n=>({reference:"fair reference"}[n]||n).toLowerCase();
const FIXED=["fair reference","oracle","staff"];
const rank=r=>{const c=canon(r.row),i=FIXED.indexOf(c);if(i>=0)return 10+i;if(r.mode&&r.provenance==="real"&&r.agent!=="scripted")return 0;if(NEED.some(([n,re])=>re.test(r.row))||/gemini|claude|codex/i.test(r.row))return 5;return 20};
const KIND=m=>/scripted/.test(m||"")?"scripted":null;
function fromSummary(s){
  return Object.entries(s).filter(([k])=>!k.includes(":")).map(([k,v])=>({row:k,mode:"all-8",n_days:v.n_days,pass1:v["pass^1"],reward:v.reward_mean,sleeper_success:v.sleeper_success_rate,false_accusation:v.false_accusation_rate,model:v.model,kind:v.agent_kind,commit:v.run_id,provenance:v.agent_kind==="scripted"?"scripted":undefined}));
}
const head=d=>d.paired_diff!=null?`<b>${num(d.paired_diff)}</b>${d.paired_ci?` (${num(d.paired_ci[0])} to ${num(d.paired_ci[1])})`:""}${d.verdict?` ${esc(d.verdict)}`:""}`:num(d.gap_ref);
function row(d){
  if(d.status==="pending"||d.provenance==="placeholder"){const b=d.provenance==="placeholder"?badge(prov("scripted",d.model,{provenance:"placeholder"})):"";return `<tr><td>${esc(d.row)}</td><td>${b}</td><td colspan="10" class="nf">NOT FOUND</td></tr>`}
  if(false)return `<tr><td>${esc(d.row)}</td><td></td><td colspan="9" class="nf">NOT FOUND</td></tr>`;
  const kind=d.agent||d.kind||(d.provenance==="scripted"||d.model==="scripted"?"scripted":d.provenance==="placeholder"?"scripted":d.model?"model":null);
  const b=prov(kind,d.model,{provenance:d.provenance});
  const ci=d.pass3_ci?`${num(d.pass3)} (${num(d.pass3_ci[0])} to ${num(d.pass3_ci[1])})`:num(d.pass3);
  return `<tr><td>${esc(d.row)}</td><td>${badge(b)}${d.capped?' <span class="badge unver">CAPPED</span>':""}</td><td>${esc(d.mode||"")}</td><td class="num">${esc(d.n_days??d.n??"n/a")}</td><td class="num">${num(d.reward)}</td><td class="num">${num(d.pass1)}</td><td class="num">${ci}</td><td class="num">${pct(d.sleeper_success)}</td><td class="num">${pct(d.false_accusation)}</td><td class="num">${head(d)}</td><td class="num">${num(d.gap_oracle)}</td><td class="muted">${esc(d.model||"?")}, ${esc(d.commit||"no commit")}</td></tr>`;
}
async function init(){
  const q=new URLSearchParams(location.search);
  const flag=document.getElementById("flag");
  let rows,from;
  for(const u of [q.get("src"),"results/frontier/gaptable.json","results/eval/summary.json","fixtures/gaptable.json"].filter(Boolean)){
    try{const d=await get(u);rows=Array.isArray(d)?d:fromSummary(d);from=u;break}catch(e){}
  }
  if(!rows){rows=[];from="nothing"}
  if(Array.isArray(rows)&&rows.some(r=>r.mode)&&!from.includes("summary")){
    try{const have=new Set(rows.map(r=>canon(r.row)));
      fromSummary(await get("results/eval/summary.json")).forEach(r=>{if(!have.has(canon(r.row)))rows.push(r)});from+=" + results/eval/summary.json"}catch(e){}
  }
  if(from.startsWith("fixtures/"))flag.innerHTML='<b class="bad">FIXTURE, not real results</b>';
  document.getElementById("src").textContent=from;
  FIXED.forEach(n=>{if(!rows.some(r=>canon(r.row)===n))rows.push({row:n,status:"pending"})});
  rows.sort((a,b)=>rank(a)-rank(b));
  NEED.forEach(([n,re])=>{if(!rows.some(r=>re.test(r.row)))rows.push({row:n,status:"pending"})});
  document.querySelector("#gap thead").innerHTML="<tr><th>Agent</th><th>Label</th><th>Mode</th><th>n days</th><th>Mean reward</th><th>pass^1</th><th>pass^3 (95% CI)</th><th>Sleeper success</th><th>False accusation</th><th>Gap vs reference (paired when present)</th><th>Gap vs oracle</th><th>Source</th></tr>";
  const top=r=>r.headline===true||r.status==="pending"||!("headline" in r);
  const A=rows.filter(top),B=rows.filter(r=>!top(r));
  const ex=rows.filter(r=>r.excluded||r.invalid);
  const hd=t=>`<tr class="grp"><th colspan="12">${t}</th></tr>`;
  document.querySelector("#gap tbody").innerHTML=(B.length?hd("Headline"):"")+A.map(row).join("")+(B.length?hd("Ablation and other groups"):"")+B.map(row).join("")+(ex.length?`<tr><td colspan="12" class="muted">Excluded or invalid runs: ${ex.map(r=>esc(r.row)+" "+esc(r.excluded??r.invalid)).join(", ")}</td></tr>`:"");
  document.getElementById("seatwrap").hidden=true;
}
init();
