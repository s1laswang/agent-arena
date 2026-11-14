import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseEpisodes } from "../src/parse";
import { provenance } from "../src/provenance";

const root = process.argv[2] ?? "../data/runs/committed/v1.3";
const label = process.argv[4] ?? root.replace(/^.*?(data\/runs\/)/, "$1");
const out = process.argv[3] ?? "public/gap.json";
const walk = (d: string): string[] =>
  readdirSync(d).flatMap((n) => {
    const p = join(d, n);
    return statSync(p).isDirectory() ? (n === "superseded" ? [] : walk(p)) : n === "episodes.jsonl" ? [p] : [];
  });

type Acc = { scores: number[]; correct: number; days: number[]; labels: Set<string>; invalid: number; sources: Set<string> };
const acc = new Map<string, Acc>();
for (const f of walk(root)) {
  for (const e of parseEpisodes(readFileSync(f, "utf8")).episodes) {
    const key = `${e.tier}\t${e.agent}`;
    const a = acc.get(key) ?? { scores: [], correct: 0, days: [], labels: new Set(), invalid: 0, sources: new Set() };
    acc.set(key, a);
    a.sources.add(f.slice(root.length + 1).replace(/\/episodes\.jsonl$/, ""));
    if (e.meta?.valid === false) {
      a.invalid++;
      continue;
    }
    a.scores.push(e.score);
    a.correct += e.correct ? 1 : 0;
    if (e.accused) a.days.push(e.final_day);
    a.labels.add(provenance(e).label);
  }
}
const mean = (x: number[]) => x.reduce((s, v) => s + v, 0) / x.length;
const rows = [...acc.entries()].map(([k, a]) => {
  const [tier, agent] = k.split("\t");
  const n = a.scores.length;
  const m = n ? mean(a.scores) : null;
  const sd = n > 1 ? Math.sqrt(a.scores.reduce((s, v) => s + (v - (m as number)) ** 2, 0) / (n - 1)) : 0;
  const label = a.labels.size === 1 ? [...a.labels][0] : "UNVERIFIED";
  return { tier, agent, n, invalid: a.invalid, score: m, ci: n > 1 ? 1.96 * sd / Math.sqrt(n) : null, accuracy: n ? a.correct / n : null, accuse_day: a.days.length ? mean(a.days) : null, label: n ? label : "UNVERIFIED", sources: [...a.sources].sort() };
});
for (const r of rows) {
  const solver = rows.find((x) => x.tier === r.tier && x.agent === "solver");
  (r as Record<string, unknown>).vs_solver = solver?.score && r.score !== null ? r.score / solver.score : null;
}
rows.sort((a, b) => a.tier.localeCompare(b.tier) || (b.score ?? -9) - (a.score ?? -9));
writeFileSync(out, JSON.stringify({ rows, source: label }, null, 1));
console.log(`${rows.length} rows -> ${out}`);
