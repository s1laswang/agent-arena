import type { Episode, Step } from "./types";
import { isRecord, num, str } from "./util";

/**
 * Viewer state is rebuilt from the step log. The episode header supplies the
 * score and whether the accusation was correct. Everything else — roster,
 * canary assignments, restrictions, the leak feed, and V — is parsed back out
 * of tool arguments and results, because the env does not keep a side file.
 *
 * Company value is only reported by `status` and `advance_day`. `plant_canary`
 * spends value immediately but the result is just `{canary_id}`, so the drop
 * shows up on the next status. V starts at 1.0 by the rules; that point is
 * marked source "initial".
 *
 * The mole's id is not in any tool result. It is known only when `correct` is
 * true, in which case it is `accused`. A wrong accusation does not name the mole.
 * The decoy is never exposed.
 */

export type VSource = "initial" | "status" | "advance_day" | "meta";

export type VSample = {
  t: number;
  day: number;
  v: number;
  source: VSource;
};

export type CanaryPlant = {
  id: string;
  title: string;
  day: number;
  revealStep: number;
  /** Variant label → employee ids. */
  variants: Record<string, string[]>;
};

export type EmployeeView = {
  id: string;
  name: string | null;
  dept: string | null;
  role: string | null;
  clearance: number | null;
  restricted: boolean;
  tags: { canaryId: string; variant: string }[];
  accused: boolean;
  mole: boolean;
  exonerated: boolean;
};

export type LeakView = {
  docId: string;
  title: string;
  surfacedDay: number;
  variant?: string;
  observedAt: number;
  isCanary: boolean;
  implicated: string[];
  unread: boolean;
};

export type Frame = {
  cursor: number;
  step: Step | null;
  day: number;
  employees: EmployeeView[];
  rosterKnown: boolean;
  canaries: CanaryPlant[];
  leaks: LeakView[];
  hiddenLeaks: number;
  feedChecked: boolean;
  samples: VSample[];
  vAtCursor: number | null;
  accusedStep: number | null;
  accusationLive: boolean;
};

type Emp = {
  id: string;
  name: string | null;
  dept: string | null;
  role: string | null;
  clearance: number | null;
};

type Leak = {
  docId: string;
  title: string;
  surfacedDay: number;
  variant?: string;
  observedAt: number;
};

type DocInfo = {
  id: string;
  title: string;
  day: number;
  recipients: string[];
  isCanary: boolean;
  variants: Record<string, string[]> | null;
};

export type EpisodeModel = {
  episode: Episode;
  employees: Map<string, Emp>;
  rosterKnown: boolean;
  canaries: CanaryPlant[];
  leaks: Map<string, Leak>;
  docs: Map<string, DocInfo>;
  samples: VSample[];
  accusedStep: number | null;
  feedChecked: boolean;
  restrictedAfter: string[][];
};

export function modelEpisode(episode: Episode): EpisodeModel {
  const employees = new Map<string, Emp>();
  const canaries: CanaryPlant[] = [];
  const leaks = new Map<string, Leak>();
  const docs = new Map<string, DocInfo>();
  const samples: VSample[] = [{ t: -1, day: episode.steps[0]?.day ?? 1, v: 1, source: "initial" }];
  const restrictedAfter: string[][] = [];
  let restricted = new Set<string>();
  let rosterKnown = false;
  let feedChecked = false;
  let accusedStep: number | null = null;

  const touch = (id: string): Emp => {
    let emp = employees.get(id);
    if (!emp) {
      emp = { id, name: null, dept: null, role: null, clearance: null };
      employees.set(id, emp);
    }
    return emp;
  };

  const absorbCanary = (
    id: string,
    title: string,
    day: number,
    step: number,
    variants: Record<string, string[]> | null,
  ) => {
    const existing = canaries.find((c) => c.id === id);
    if (!existing) {
      canaries.push({ id, title, day, revealStep: step, variants: variants ?? {} });
      return;
    }
    if ((existing.title === existing.id || !existing.title) && title && title !== id) existing.title = title;
    if (variants && Object.keys(variants).length > 0 && Object.keys(existing.variants).length === 0) {
      existing.variants = variants;
    }
    if (step < existing.revealStep) existing.revealStep = step;
  };

  episode.steps.forEach((step, i) => {
    const data = step.result.data;

    if (step.tool === "list_employees" && step.result.ok) {
      for (const raw of listOf(data, "employees")) {
        if (!isRecord(raw)) {
          const id = str(raw);
          if (id) touch(id);
          continue;
        }
        const id = str(raw.id);
        if (!id) continue;
        const emp = touch(id);
        const name = str(raw.name);
        const dept = str(raw.dept);
        const role = str(raw.role);
        const clearance = num(raw.clearance);
        if (name) emp.name = name;
        if (dept) emp.dept = dept;
        if (role) emp.role = role;
        if (clearance !== null) emp.clearance = clearance;
        rosterKnown = true;
      }
    }

    if (step.tool === "list_documents" && step.result.ok) {
      for (const raw of listOf(data, "documents", "docs")) {
        if (!isRecord(raw)) continue;
        const id = str(raw.doc_id) ?? str(raw.id);
        if (!id) continue;
        const variants = parseVariants(raw.variants);
        const recipients = Array.isArray(raw.recipients)
          ? raw.recipients.filter((x): x is string => typeof x === "string")
          : variants
            ? Object.values(variants).flat()
            : [];
        recipients.forEach(touch);
        const title = str(raw.title) ?? id;
        const day = num(raw.day) ?? step.day;
        const isCanary = raw.is_canary === true || variants !== null || /^c\d+$/.test(id);
        docs.set(id, { id, title, day, recipients, isCanary, variants });
        if (isCanary) absorbCanary(id, title, day, i, variants);
      }
    }

    if (step.tool === "plant_canary" && step.result.ok) {
      const variants = variantsFromAssignment(step.args.assignment);
      const id = str(data.canary_id) ?? str(data.doc_id) ?? `c${step.day}`;
      const title = str(step.args.doc_title) ?? id;
      Object.values(variants).flat().forEach(touch);
      absorbCanary(id, title, step.day, i, variants);
      docs.set(id, {
        id,
        title,
        day: step.day,
        recipients: Object.values(variants).flat(),
        isCanary: true,
        variants,
      });
    }

    if (step.tool === "status" && step.result.ok && Array.isArray(data.restricted)) {
      restricted = new Set(data.restricted.filter((x): x is string => typeof x === "string"));
    }
    if (step.tool === "restrict_access" && step.result.ok) {
      const id = str(step.args.employee) ?? str(data.restricted);
      if (id) restricted.add(id);
    }
    if (step.tool === "unrestrict_access" && step.result.ok) {
      const id = str(step.args.employee) ?? str(data.unrestricted);
      if (id) restricted.delete(id);
    }
    restricted.forEach(touch);
    restrictedAfter.push([...restricted].sort());

    if (step.tool === "status" && step.result.ok) {
      const v = num(data.V) ?? num(data.value);
      if (v !== null) samples.push({ t: i, day: step.day, v, source: "status" });
    }
    if (step.tool === "advance_day" && step.result.ok) {
      const v = num(data.V) ?? num(data.value);
      if (v !== null) samples.push({ t: i, day: step.day, v, source: "advance_day" });
    }

    if (step.tool === "check_leak_feed" && step.result.ok) {
      feedChecked = true;
      for (const raw of listOf(data, "items", "feed", "leaks")) {
        if (!isRecord(raw)) continue;
        const docId = str(raw.doc_id) ?? str(raw.docId) ?? str(raw.id);
        if (!docId) continue;
        const variant = str(raw.variant) ?? undefined;
        const title = str(raw.title) ?? docs.get(docId)?.title ?? docId;
        const surfaced = num(raw.surfaced_day) ?? num(raw.surfacedDay) ?? num(raw.day) ?? step.day;
        const prev = leaks.get(docId);
        if (!prev) leaks.set(docId, { docId, title, surfacedDay: surfaced, variant, observedAt: i });
        else if (!prev.variant && variant) prev.variant = variant;
      }
    }

    if (step.result.ok) {
      const id = str(step.args.employee);
      if (id) touch(id);
      if (step.tool === "read_access_logs") {
        for (const raw of listOf(data, "logs", "entries", "accesses")) {
          if (isRecord(raw)) {
            const who = str(raw.employee);
            if (who) touch(who);
          }
        }
      }
    }

    if (step.tool === "accuse" && step.result.ok) {
      accusedStep = i;
      const id = str(step.args.employee) ?? str(data.accused);
      if (id) touch(id);
    }
  });

  if (episode.accused) touch(episode.accused);

  const metaV = num(episode.meta.V) ?? num(episode.meta.value);
  if (metaV !== null && episode.steps.length) {
    const last = samples[samples.length - 1];
    if (Math.abs(last.v - metaV) > 1e-6) {
      const tail = episode.steps.length - 1;
      samples.push({ t: tail, day: episode.steps[tail].day, v: metaV, source: "meta" });
    }
  }

  return {
    episode,
    employees,
    rosterKnown,
    canaries,
    leaks,
    docs,
    samples,
    accusedStep,
    feedChecked,
    restrictedAfter,
  };
}

export function project(model: EpisodeModel, cursor: number): Frame {
  const steps = model.episode.steps;
  const safe = steps.length === 0 ? -1 : Math.max(-1, Math.min(cursor, steps.length - 1));
  const day = safe < 0 ? (steps[0]?.day ?? 1) : steps[safe].day;
  const canaries = model.canaries.filter((c) => c.revealStep <= safe);
  const tags = new Map<string, { canaryId: string; variant: string }[]>();
  for (const canary of canaries) {
    for (const [variant, ids] of Object.entries(canary.variants)) {
      for (const id of ids) {
        const list = tags.get(id) ?? [];
        list.push({ canaryId: canary.id, variant });
        tags.set(id, list);
      }
    }
  }
  const restricted = new Set(safe < 0 ? [] : (model.restrictedAfter[safe] ?? []));
  const accused = model.episode.accused;
  const correct = model.episode.correct;
  const employees: EmployeeView[] = [...model.employees.values()]
    .map((emp) => ({
      ...emp,
      restricted: restricted.has(emp.id),
      tags: tags.get(emp.id) ?? [],
      accused: accused !== null && emp.id === accused,
      mole: correct && accused !== null && emp.id === accused,
      exonerated: !correct && accused !== null && emp.id === accused,
    }))
    .sort((a, b) => a.id.localeCompare(b.id));

  const allLeaks: LeakView[] = [...model.leaks.values()]
    .map((leak) => ({
      ...leak,
      isCanary:
        Boolean(leak.variant) || model.canaries.some((c) => c.id === leak.docId) || /^c\d+$/.test(leak.docId),
      implicated: implicated(leak, model),
      unread: leak.observedAt > safe,
    }))
    .sort((a, b) => a.surfacedDay - b.surfacedDay || a.docId.localeCompare(b.docId));
  const visible = allLeaks.filter((leak) => leak.surfacedDay <= day);

  let vAtCursor: number | null = null;
  for (const sample of model.samples) if (sample.t <= safe) vAtCursor = sample.v;

  return {
    cursor: safe,
    step: safe < 0 ? null : steps[safe],
    day,
    employees,
    rosterKnown: model.rosterKnown,
    canaries,
    leaks: visible,
    hiddenLeaks: allLeaks.length - visible.length,
    feedChecked: model.feedChecked,
    samples: model.samples,
    vAtCursor,
    accusedStep: model.accusedStep,
    accusationLive: model.accusedStep !== null && safe >= model.accusedStep,
  };
}

function implicated(leak: Leak, model: EpisodeModel): string[] {
  if (leak.variant) {
    const fromCanary = model.canaries.find((c) => c.id === leak.docId)?.variants[leak.variant];
    const fromDoc = model.docs.get(leak.docId)?.variants?.[leak.variant];
    return [...(fromCanary ?? fromDoc ?? [])].sort();
  }
  return [...(model.docs.get(leak.docId)?.recipients ?? [])].sort();
}

function listOf(data: Record<string, unknown>, ...keys: string[]): unknown[] {
  for (const key of keys) {
    const value = data[key];
    if (Array.isArray(value)) return value;
  }
  return [];
}

function variantsFromAssignment(raw: unknown): Record<string, string[]> {
  if (!isRecord(raw)) return {};
  const out: Record<string, string[]> = {};
  for (const [emp, label] of Object.entries(raw)) {
    const lab = str(label);
    if (!lab) continue;
    (out[lab] ??= []).push(emp);
  }
  for (const key of Object.keys(out)) out[key].sort();
  return out;
}

/** `{label: [employee, ...]}` from list_documents, or the inverse `{employee: label}`. */
function parseVariants(raw: unknown): Record<string, string[]> | null {
  if (!isRecord(raw)) return null;
  const entries = Object.entries(raw);
  if (!entries.length) return null;
  if (entries.every(([, value]) => Array.isArray(value))) {
    const out: Record<string, string[]> = {};
    for (const [label, ids] of entries) {
      out[label] = (ids as unknown[]).filter((x): x is string => typeof x === "string").sort();
    }
    return out;
  }
  if (entries.every(([, value]) => typeof value === "string")) {
    const out: Record<string, string[]> = {};
    for (const [emp, label] of entries) {
      if (typeof label !== "string") continue;
      (out[label] ??= []).push(emp);
    }
    for (const key of Object.keys(out)) out[key].sort();
    return out;
  }
  return null;
}
