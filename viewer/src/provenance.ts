import type { Episode } from "./types";

export type Provenance = { label: "REAL" | "SCRIPTED" | "SMOKE" | "UNVERIFIED"; tone: string; why: string };

export const SCRIPTED_AGENTS = new Set([
  "solver", "heuristic", "grok_tactics", "do_nothing", "stop_early", "random", "restrict_all", "probe_all",
  "accuse_decoy", "accuse_most_logs", "obvious_heuristic", "logs_minus_decoy", "logs_only", "oracle", "cheat",
]);

export function provenance(ep: Episode): Provenance {
  const m = ep.meta ?? {};
  const u = (typeof m.usage === "object" && m.usage !== null ? m.usage : {}) as Record<string, unknown>;
  const tokens = (Number(u.in) || 0) + (Number(u.out) || 0);
  const named = /^[^:\s]+:[^:\s]+/.test(ep.agent);
  if (m.smoke === true) return { label: "SMOKE", tone: "warn", why: "flagged smoke test, not a measurement" };
  if (named && tokens > 0) {
    const cost = typeof u.cost_usd_est === "number" ? `, cost ESTIMATE $${u.cost_usd_est.toFixed(2)}` : "";
    return { label: "REAL", tone: "good", why: `usage: ${tokens} tokens, provider ${ep.agent.split(":")[0]}${cost}` };
  }
  if (SCRIPTED_AGENTS.has(ep.agent)) return { label: "SCRIPTED", tone: "", why: `${ep.agent} is a built-in scripted agent, no model call` };
  if (m.valid === false) return { label: "UNVERIFIED", tone: "warn", why: `run marked invalid${typeof m.error === "string" ? `: ${m.error}` : ""}` };
  return { label: "UNVERIFIED", tone: "warn", why: named ? "model name but no token usage in the run record" : "agent is not a known scripted agent and has no model name" };
}

export const LEGEND: [string, string][] = [
  ["Score", "Final company value V, minus penalties. Higher is better; a wrong accusation costs value."],
  ["V", "Company value. Each leak lowers it, so a late catch scores less than an early one."],
  ["Canary", "A marked copy of a document planted for a set of employees. Whoever leaks it is identified by the variant that surfaces."],
  ["Accuse", "The agent names one employee. Correct means the leaker, wrong means an innocent person."],
  ["REAL", "A model played and its run record (usage, transcript source) is present."],
  ["SCRIPTED", "A fixed program played. It is a reference, not a model."],
  ["SMOKE", "A quick plumbing check, not a result."],
  ["UNVERIFIED", "The run record is missing something, so do not trust the label."],
];
