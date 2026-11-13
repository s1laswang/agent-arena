const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct=v=>v==null?"n/a":(v*100).toFixed(0)+"%";
const num=v=>v==null?"n/a":v.toFixed(2);
async function get(u){const r=await fetch(u);if(!r.ok)throw new Error(u);return r.json()}
async function init(){
  const q=new URLSearchParams(location.search);
  const want=q.get("src")||"results/eval/summary.json";
  let data,fixture=false;
  try{data=await get(want);document.getElementById("src").textContent=want}
  catch(e){data=await get("fixtures/eval-summary.json");fixture=true;document.getElementById("src").textContent="fixtures/eval-summary.json"}
  if(fixture)document.getElementById("flag").innerHTML='<b class="bad">FIXTURE, not real results</b>';
  if(data.team)data={[data.team]:data};
  const teams=Object.keys(data);
  const ks=[...new Set(teams.flatMap(t=>Object.keys(data[t]).filter(k=>k.startsWith("pass^"))))].sort();
  document.querySelector("#gap thead").innerHTML=`<tr><th>Team</th><th>Kind</th><th>Reward</th>${ks.map(k=>`<th>${esc(k)}</th>`).join("")}<th>Sleeper success</th><th>False accusations</th><th>Ticket completion</th><th>Days</th></tr>`;
  document.querySelector("#gap tbody").innerHTML=teams.map(t=>{const d=data[t];return `<tr><td>${esc(t)}</td><td>${esc(d.agent_kind||"")}${d.deterministic?", deterministic":""}</td><td class="num">${num(d.reward_mean)}</td>${ks.map(k=>`<td class="num">${num(d[k])}</td>`).join("")}<td class="num">${pct(d.sleeper_success_rate)}</td><td class="num">${pct(d.false_accusation_rate)}</td><td class="num">${pct(d.ticket_completion)}</td><td class="num">${esc(d.n_days??"")}</td></tr>`}).join("");
  const det=teams.some(t=>data[t].deterministic&&data[t].agent_kind==="scripted");
  document.getElementById("note").textContent=det?"Scripted teams are deterministic, so pass^k for them is not earned by repeated sampling.":"";
}
init();
