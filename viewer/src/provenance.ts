import type { Episode } from "./types";

export type Provenance = { label: "REAL" | "SCRIPTED" | "SMOKE" | "UNVERIFIED"; tone: string; why: string };

export function provenance(ep: Episode): Provenance {
  const m = ep.meta ?? {};
  const named = ep.agent.includes(":");
  const logged = typeof m.usage === "object" && m.usage !== null && typeof m.steps_source === "string";
  if (m.smoke === true) return { label: "SMOKE", tone: "warn", why: "smoke test run, not a measurement" };
  if (named && logged) return { label: "REAL", tone: "good", why: `model ${ep.agent}, steps from ${String(m.steps_source)}, usage logged` };
  if (!named && !m.usage) return { label: "SCRIPTED", tone: "", why: "deterministic program, no model call" };
  return { label: "UNVERIFIED", tone: "warn", why: "model name or run record missing" };
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
