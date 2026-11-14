import { execSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { parseEpisodes } from "./parse";
import { provenance } from "./provenance";
import type { Episode } from "./types";

export type Row = {
  tier: string; agent: string; n: number; invalid: number; score: number | null; ci: number | null;
  accuracy: number | null; accuse_day: number | null; vs_solver: number | null; label: string; sources: string[];
};
export type Group = { id: string; title: string; version: string; commit: string; rows: Row[] };

const walk = (d: string, name: (n: string) => boolean): string[] =>
  readdirSync(d).flatMap((n) => {
    const p = join(d, n);
    return statSync(p).isDirectory() ? (n === "superseded" ? [] : walk(p, name)) : name(n) ? [p] : [];
  });
const mean = (x: number[]) => x.reduce((s, v) => s + v, 0) / x.length;

function commitOf(dir: string, fallback: string | null): string {
  if (fallback) return fallback.slice(0, 8);
  try {
    return execSync(`git log -1 --format=%h -- "${dir}"`, { cwd: dir, stdio: ["ignore", "pipe", "ignore"] }).toString().trim() || "unknown";
  } catch {
    return "unknown";
  }
}

type Item = { tier: string; agent: string; ep: Episode; source: string };

function rowsOf(items: Item[], noAccuse = false): Row[] {
  const by = new Map<string, Item[]>();
  for (const it of items) by.set(`${it.tier}\t${it.agent}`, [...(by.get(`${it.tier}\t${it.agent}`) ?? []), it]);
  const rows: Row[] = [...by.entries()].map(([k, list]) => {
    const [tier, agent] = k.split("\t");
    const ok = list.filter((i) => i.ep.meta?.valid !== false);
    const n = ok.length;
    const scores = ok.map((i) => i.ep.score);
    const m = n ? mean(scores) : null;
    const sd = n > 1 ? Math.sqrt(scores.reduce((s, v) => s + (v - (m as number)) ** 2, 0) / (n - 1)) : 0;
    const days = ok.filter((i) => i.ep.accused).map((i) => i.ep.final_day);
    const labels = new Set(ok.map((i) => provenance(i.ep).label));
    return {
      tier, agent, n, invalid: list.length - n, score: m, ci: n > 1 ? (1.96 * sd) / Math.sqrt(n) : null,
      accuracy: n && !noAccuse ? ok.filter((i) => i.ep.correct).length / n : null, accuse_day: days.length && !noAccuse ? mean(days) : null,
      vs_solver: null, label: n && labels.size === 1 ? [...labels][0] : "UNVERIFIED", sources: [...new Set(list.map((i) => i.source))].sort(),
    };
  });
  const seedScores = (tier: string, agent: string) => {
    const m = new Map<number, number>();
    for (const i of by.get(`${tier}\t${agent}`) ?? []) if (i.ep.meta?.valid !== false && i.ep.seed !== null) m.set(i.ep.seed, i.ep.score);
    return m;
  };
  for (const r of rows) {
    const refAgent = ["solver", "oracle"].find((a) => rows.some((x) => x.tier === r.tier && x.agent === a));
    const ref = rows.find((x) => x.tier === r.tier && x.agent === refAgent);
    const mine = seedScores(r.tier, r.agent);
    const theirs = refAgent ? seedScores(r.tier, refAgent) : new Map<number, number>();
    const common = [...mine.keys()].filter((k) => theirs.has(k));
    if (common.length) {
      const den = mean(common.map((k) => theirs.get(k) as number));
      r.vs_solver = den ? mean(common.map((k) => mine.get(k) as number)) / den : null;
    } else r.vs_solver = ref?.score && r.score !== null ? r.score / ref.score : null;
  }
  return rows.sort((a, b) => a.tier.localeCompare(b.tier) || (b.score ?? -9) - (a.score ?? -9));
}

function episodeGroup(root: string, rel: string, version: string, title: string): Group | null {
  const dir = join(root, rel);
  if (!existsSync(dir)) return null;
  const items: Item[] = [];
  let sha: string | null = null;
  for (const f of walk(dir, (n) => n === "episodes.jsonl")) {
    const meta = join(f, "..", "meta.json");
    if (!sha && existsSync(meta)) {
      const m = /"git_sha":\s*"([0-9a-f]+)"/.exec(readFileSync(meta, "utf8"));
      sha = m ? m[1] : null;
    }
    for (const ep of parseEpisodes(readFileSync(f, "utf8")).episodes) items.push({ tier: ep.tier, agent: ep.agent, ep, source: f.slice(dir.length + 1).replace(/\/episodes\.jsonl$/, "") });
  }
  return { id: version, title, version, commit: commitOf(dir, sha), rows: rowsOf(items) };
}

const HARBOR_NAME: Record<string, string> = { "g-oracle": "oracle", cheat: "cheat", do_nothing: "do_nothing", stop_early: "stop_early", oracle: "oracle" };

function harborGroup(root: string): Group | null {
  const dir = join(root, "results/harbor");
  if (!existsSync(dir)) return null;
  const items: Item[] = [];
  for (const f of walk(dir, (n) => n === "result.json")) {
    const rel = f.slice(dir.length + 1).split("/");
    if (rel.length !== 3) continue;
    const d = JSON.parse(readFileSync(f, "utf8"));
    const reward = d.verifier_result?.rewards?.reward;
    if (typeof reward !== "number") continue;
    const cfg = d.config?.agent ?? {};
    const model: string | undefined = cfg.model_name;
    const agent = model ? `${cfg.name}:${model}` : HARBOR_NAME[rel[0]] ?? String(cfg.name);
    if (rel[0] === "oracle") continue;
    const ar = d.agent_result ?? {};
    const ep = {
      tier: "", agent, seed: null, steps: [], score: reward, accused: reward !== 0 ? "x" : null, correct: reward > 0, final_day: 0, end_reason: "",
      meta: { usage: model ? { in: ar.n_input_tokens ?? 0, out: ar.n_output_tokens ?? 0 } : undefined, valid: d.verifier_result ? true : false },
    } as unknown as Episode;
    items.push({ tier: rel[0].startsWith("g-") ? "6 tasks (3 medium + 3 hard)" : "2 tasks (seed 900000, medium + hard)", agent, ep, source: rel[0] });
  }
  const keep = items.filter((i) => /^(g-|cheat|do_nothing|stop_early)/.test(i.source));
  return { id: "harbor-v1.4", title: "Harbor + OpenCode over MCP (one run per task)", version: "v1.4 tasks", commit: commitOf(dir, null), rows: rowsOf(keep, true) };
}

export function buildGap(root: string): { groups: Group[]; source: string } {
  const groups = [
    episodeGroup(root, "data/runs/committed/v1.3", "v1.3", "Reference and frontier runs, rules v1.3"),
    episodeGroup(root, "data/runs/committed/v1.4", "v1.4", "Scripted reference runs, rules v1.4"),
    harborGroup(root),
  ].filter((g): g is Group => g !== null);
  return { groups, source: "data/runs/committed and results/harbor" };
}
