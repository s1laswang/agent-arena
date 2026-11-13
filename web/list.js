const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
fetch("days/index.json").then(r=>r.json()).then(rows=>{
  const tb=document.querySelector("tbody");
  tb.innerHTML=rows.map(r=>`<tr><td><input type="checkbox" value="${esc(r.id)}" data-seed="${esc(r.seed)}" aria-label="Select ${esc(r.id)}"></td><td><a href="replay.html?day=${encodeURIComponent(r.id)}">${esc(r.id)}</a></td><td class="num">${esc(r.seed)}</td><td>${esc(r.team)}</td><td>${esc(r.goal||"none")}</td><td>${esc(r.seat_under_test)}</td><td class="num ${r.reward?"ok":"bad"}">${r.reward}</td></tr>`).join("");
  const b=document.getElementById("cmp");
  const sel=()=>[...tb.querySelectorAll("input:checked")];
  tb.onchange=()=>{const s=sel();b.disabled=!(s.length===2&&s[0].dataset.seed===s[1].dataset.seed)};
  b.onclick=()=>{const s=sel();location.href=`replay.html?day=${s[0].value}&vs=${s[1].value}`};
});
