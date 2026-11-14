import type { Episode, Step } from "./types";
import { isRecord } from "./util";

export function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

export function episodeLabel(ep: Episode): string {
  const seed = ep.seed === null ? "—" : String(ep.seed);
  const verdict = ep.correct ? "correct" : "wrong";
  return `seed ${seed} · ${ep.tier} · ${fmtNum(ep.score)} · ${verdict} · day ${ep.final_day}`;
}

const SHORT: Record<string, string> = {
  status: "status",
  list_employees: "roster",
  list_documents: "docs",
  read_access_logs: "logs",
  search_messages: "search",
  read_message: "message",
  interview: "interview",
  plant_canary: "plant",
  check_leak_feed: "leaks",
  restrict_access: "restrict",
  unrestrict_access: "unrestrict",
  advance_day: "advance",
  accuse: "accuse",
};

export function shortTool(tool: string): string {
  return SHORT[tool] ?? tool;
}

export function summarize(step: Step): string {
  const a = step.args;
  const data = step.result.data;
  switch (step.tool) {
    case "plant_canary": {
      const asg = isRecord(a.assignment) ? a.assignment : null;
      const n = asg ? Object.keys(asg).length : 0;
      const labels = asg
        ? [...new Set(Object.values(asg).filter((v): v is string => typeof v === "string"))].sort().join("")
        : "";
      const title = typeof a.doc_title === "string" ? a.doc_title : "canary";
      return `${title} · ${n} ${labels}`.trim();
    }
    case "restrict_access":
    case "unrestrict_access":
    case "accuse":
      return typeof a.employee === "string" ? a.employee : "";
    case "interview":
      return [a.employee, a.topic].filter((v): v is string => typeof v === "string").join(" · ");
    case "advance_day":
      return typeof data.day === "number" ? `→ day ${data.day}` : "close day";
    case "status":
      return typeof data.V === "number" ? `V ${data.V.toFixed(3)}` : "";
    case "check_leak_feed":
      return Array.isArray(data.items) ? `${data.items.length} surfaced` : "";
    case "list_documents":
      return a.day_from != null ? `days ${String(a.day_from)}–${String(a.day_to ?? "")}` : "";
    case "read_access_logs": {
      const n = Array.isArray(data.logs) ? `${data.logs.length} · ` : "";
      return `${n}days ${String(a.day_from ?? "")}–${String(a.day_to ?? "")}`;
    }
    case "search_messages":
      return typeof a.query === "string" ? a.query : "";
    case "read_message":
      return typeof a.id === "string" ? a.id : "";
    case "list_employees":
      return Array.isArray(data.employees) ? `${data.employees.length} people` : "";
    default:
      return "";
  }
}

export function pretty(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2) ?? "null";
  } catch {
    return String(v);
  }
}
