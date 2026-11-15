import type { Episode, Step, ToolResult } from "./types";
import { flag, isRecord, num, str } from "./util";

export type ParseResult = {
  episodes: Episode[];
  warnings: string[];
};

/** Accept JSONL (one EpisodeResult per line), a JSON array, or one episode object. */
export function parseEpisodes(text: string): ParseResult {
  const trimmed = text.replace(/^\uFEFF/, "").trim();
  if (!trimmed) return { episodes: [], warnings: ["File is empty."] };

  if (trimmed.startsWith("[") || (trimmed.startsWith("{") && trimmed.endsWith("}"))) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      const list = Array.isArray(parsed)
        ? parsed
        : isRecord(parsed) && Array.isArray(parsed.episodes)
          ? parsed.episodes
          : [parsed];
      return coerceList(list, "item");
    } catch {
      /* fall through: a JSONL file also starts with { and ends with } */
    }
  }

  const episodes: Episode[] = [];
  const warnings: string[] = [];
  const lines = trimmed.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    let raw: unknown;
    try {
      raw = JSON.parse(line);
    } catch {
      warnings.push(`Line ${i + 1} is not valid JSON.`);
      continue;
    }
    const got = coerceEpisode(raw, `Line ${i + 1}`);
    if (got.episode) episodes.push(got.episode);
    if (got.warning) warnings.push(got.warning);
  }
  if (!episodes.length && !warnings.length) warnings.push("No episodes found.");
  return { episodes, warnings };
}

function coerceList(list: unknown[], label: string): ParseResult {
  const episodes: Episode[] = [];
  const warnings: string[] = [];
  list.forEach((raw, i) => {
    const got = coerceEpisode(raw, `${label} ${i + 1}`);
    if (got.episode) episodes.push(got.episode);
    if (got.warning) warnings.push(got.warning);
  });
  if (!episodes.length && !warnings.length) warnings.push("No episodes found.");
  return { episodes, warnings };
}

function coerceEpisode(raw: unknown, where: string): { episode: Episode | null; warning?: string } {
  if (!isRecord(raw)) return { episode: null, warning: `${where}: expected an object.` };
  const stepsRaw = Array.isArray(raw.steps) ? raw.steps : Array.isArray(raw.history) ? raw.history : null;
  if (!stepsRaw) return { episode: null, warning: `${where}: missing steps.` };

  const warnings: string[] = [];
  const steps: Step[] = [];
  stepsRaw.forEach((item, i) => {
    const step = coerceStep(item, i);
    if (step) steps.push(step);
    else warnings.push(`${where}: dropped step ${i}.`);
  });

  const lastDay = steps.length ? steps[steps.length - 1].day : 1;
  const episode: Episode = {
    tier: str(raw.tier) ?? "unknown",
    seed: num(raw.seed),
    agent: str(raw.agent) ?? "unknown",
    steps,
    score: num(raw.score) ?? 0,
    accused: str(raw.accused),
    correct: flag(raw.correct),
    final_day: num(raw.final_day) ?? lastDay,
    end_reason: str(raw.end_reason) ?? "unknown",
    meta: isRecord(raw.meta) ? raw.meta : {},
  };
  return { episode, warning: warnings.length ? warnings.join(" ") : undefined };
}

function coerceStep(raw: unknown, index: number): Step | null {
  if (!isRecord(raw)) return null;
  return {
    t: num(raw.t) ?? index,
    day: num(raw.day) ?? 1,
    tool: str(raw.tool) ?? "unknown",
    args: isRecord(raw.args) ? raw.args : {},
    result: normalizeResult(raw.result),
  };
}

function normalizeResult(raw: unknown): ToolResult {
  if (!isRecord(raw)) return { ok: false, data: {}, error: "missing result" };
  if ("ok" in raw || "data" in raw || "error" in raw) {
    const error = str(raw.error);
    return {
      ok: "ok" in raw ? flag(raw.ok) : !error,
      data: isRecord(raw.data) ? raw.data : {},
      error,
    };
  }
  return { ok: true, data: raw, error: null };
}
