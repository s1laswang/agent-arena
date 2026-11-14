function prov(kind,model,p){
  p=p||{};
  if(p.provenance==="placeholder")return{t:"SCRIPTED PLACEHOLDER",c:"scripted"};
  if(!kind||!model||kind==="scripted"||p.provenance==="scripted")return kind||p.provenance?{t:"SCRIPTED",c:"scripted"}:{t:"UNVERIFIED",c:"unver"};
  return p.provenance==="real"?{t:"REAL",c:"real"}:{t:"UNVERIFIED",c:"unver"};
}
const badge=b=>`<span class="badge ${b.c}">${b.t}</span>`;
