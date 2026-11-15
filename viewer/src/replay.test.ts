import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { advanceClock, endClock, resolveCursor, startClock } from "./clock";
import { parseEpisodes } from "./parse";
import { modelEpisode, project, type Frame } from "./replay";
import type { Episode, Step } from "./types";

const samples = resolve(dirname(fileURLToPath(import.meta.url)), "..", "public", "samples");
const solverText = readFileSync(resolve(samples, "solver-medium.jsonl"), "utf8");
const heuristicText = readFileSync(resolve(samples, "heuristic-medium.jsonl"), "utf8");
const restrictText = readFileSync(resolve(samples, "restrict-all-medium.jsonl"), "utf8");

function step(
  t: number,
  day: number,
  tool: string,
  args: Record<string, unknown>,
  data: Record<string, unknown>,
  ok = true,
): Step {
  return { t, day, tool, args, result: { ok, data, error: ok ? null : "invalid arguments" } };
}

function episode(partial: Partial<Episode> & Pick<Episode, "steps">): Episode {
  return {
    tier: "medium",
    seed: 0,
    agent: "test",
    score: 0,
    accused: null,
    correct: false,
    final_day: partial.steps.at(-1)?.day ?? 1,
    end_reason: "horizon",
    meta: {},
    ...partial,
  };
}

function at(ep: Episode, cursor: number): Frame {
  return project(modelEpisode(ep), cursor);
}

describe("parseEpisodes", () => {
  it("reads the generated solver, heuristic, and restrict-all logs", () => {
    const solver = parseEpisodes(solverText);
    const heuristic = parseEpisodes(heuristicText);
    const restrict = parseEpisodes(restrictText);
    expect(solver.warnings).toEqual([]);
    expect(solver.episodes.map((ep) => ep.seed)).toEqual([0, 1, 2]);
    expect(solver.episodes.every((ep) => ep.agent === "solver" && ep.tier === "medium")).toBe(true);
    expect(heuristic.episodes.map((ep) => [ep.seed, ep.correct])).toEqual([
      [0, false],
      [1, true],
      [2, false],
    ]);
    expect(restrict.episodes).toHaveLength(1);
    expect(restrict.episodes[0].agent).toBe("restrict_all");
  });

  it("accepts a JSON array, an episodes wrapper, and skips a bad JSONL line", () => {
    const one = parseEpisodes(solverText).episodes[0];
    expect(parseEpisodes(JSON.stringify([one])).episodes).toHaveLength(1);
    expect(parseEpisodes(JSON.stringify({ episodes: [one, one] })).episodes).toHaveLength(2);
    const mixed = parseEpisodes(`not json\n${JSON.stringify(one)}\n`);
    expect(mixed.episodes).toHaveLength(1);
    expect(mixed.warnings.some((w) => w.includes("Line 1"))).toBe(true);
  });
});

describe("replay of solver seed 0", () => {
  const ep = parseEpisodes(solverText).episodes[0];
  const last = ep.steps.length - 1;

  it("names the roster and marks the correct accusation as the mole", () => {
    const frame = at(ep, last);
    const mole = frame.employees.find((e) => e.id === "e05");
    expect(frame.rosterKnown).toBe(true);
    expect(frame.employees).toHaveLength(20);
    expect(mole).toMatchObject({ name: "Eero Salo", mole: true, accused: true, exonerated: false });
    expect(frame.employees.filter((e) => e.mole)).toHaveLength(1);
    expect(ep.score).toBeCloseTo(0.85);
    expect(frame.vAtCursor).toBeCloseTo(0.85);
  });

  it("shows canary recipients and holds V until the next status", () => {
    const plant = ep.steps.findIndex((s) => s.tool === "plant_canary");
    const frame = at(ep, plant);
    expect(frame.canaries.map((c) => c.id)).toEqual(["c1"]);
    expect(frame.vAtCursor).toBeCloseTo(1);
    const status = ep.steps.findIndex((s, i) => i > plant && s.tool === "status");
    expect(at(ep, status).vAtCursor).toBeCloseTo(0.99);
    const end = at(ep, last);
    expect(end.canaries.map((c) => c.id)).toEqual(["c1", "c2", "c3"]);
    expect(end.employees.find((e) => e.id === "e05")?.tags).toEqual(
      expect.arrayContaining([{ canaryId: "c2", variant: "B" }]),
    );
  });

  it("reveals a canary leak on the day it surfaces and colours the variant group", () => {
    const day3 = ep.steps.reduce((acc, s, i) => (s.day <= 3 ? i : acc), 0);
    const day4 = ep.steps.findIndex((s) => s.day === 4);
    expect(at(ep, day3).leaks.map((l) => l.docId)).toEqual(["d1-1"]);
    expect(at(ep, day3).leaks[0].implicated.length).toBeGreaterThan(0);
    const leaks = at(ep, day4).leaks;
    const canary = leaks.find((l) => l.docId === "c2");
    expect(canary).toMatchObject({ variant: "B", isCanary: true, surfacedDay: 4 });
    expect(canary?.implicated).toEqual(expect.arrayContaining(["e05", "e10"]));
    expect(at(ep, last).hiddenLeaks).toBe(0);
  });
});

describe("degraded and partial logs", () => {
  it("does not invent a mole after a wrong accusation", () => {
    const ep = parseEpisodes(heuristicText).episodes[0];
    const frame = at(ep, ep.steps.length - 1);
    expect(ep.accused).toBe("e06");
    expect(frame.employees.some((e) => e.mole)).toBe(false);
    expect(frame.employees.find((e) => e.id === "e06")).toMatchObject({ accused: true, exonerated: true });
    expect(frame.leaks.some((l) => l.variant)).toBe(true);
  });

  it("builds cards from a canary assignment when the roster was never listed", () => {
    const ep = episode({
      steps: [
        step(0, 1, "plant_canary", { doc_title: "Memo", assignment: { e03: "A", e04: "B" } }, { canary_id: "c1" }),
      ],
    });
    const frame = at(ep, 0);
    expect(frame.rosterKnown).toBe(false);
    expect(frame.employees.map((e) => e.id)).toEqual(["e03", "e04"]);
    expect(frame.employees.every((e) => e.name === null)).toBe(true);
    expect(frame.employees.find((e) => e.id === "e03")?.tags).toEqual([{ canaryId: "c1", variant: "A" }]);
  });

  it("tracks restrictions from the tools and from a later status snapshot", () => {
    const ep = episode({
      steps: [
        step(0, 1, "restrict_access", { employee: "e01" }, { restricted: "e01" }),
        step(1, 1, "restrict_access", { employee: "e01" }, {}, false),
        step(2, 1, "restrict_access", { employee: "e02" }, { restricted: "e02" }),
        step(3, 1, "status", {}, { day: 1, V: 0.98, restricted: ["e01", "e02"] }),
        step(4, 1, "unrestrict_access", { employee: "e01" }, { unrestricted: "e01" }),
      ],
    });
    expect(at(ep, 0).employees.filter((e) => e.restricted).map((e) => e.id)).toEqual(["e01"]);
    expect(at(ep, 1).employees.filter((e) => e.restricted).map((e) => e.id)).toEqual(["e01"]);
    expect(at(ep, 3).employees.filter((e) => e.restricted).map((e) => e.id)).toEqual(["e01", "e02"]);
    expect(at(ep, 4).employees.filter((e) => e.restricted).map((e) => e.id)).toEqual(["e02"]);
    expect(at(ep, 4).vAtCursor).toBeCloseTo(0.98);
  });

  it("keeps an empty leak feed when the agent never checked", () => {
    const ep = episode({ steps: [step(0, 1, "status", {}, { day: 1, V: 1, restricted: [] })] });
    const frame = at(ep, 0);
    expect(frame.feedChecked).toBe(false);
    expect(frame.leaks).toEqual([]);
  });

  it("shows every restricted employee in the restrict-all sample", () => {
    const ep = parseEpisodes(restrictText).episodes[0];
    const frame = at(ep, ep.steps.length - 1);
    expect(frame.employees.filter((e) => e.restricted)).toHaveLength(20);
    expect(frame.employees.some((e) => e.mole)).toBe(false);
    expect(frame.vAtCursor).toBeLessThan(1);
    expect(frame.samples.some((s) => s.source === "advance_day")).toBe(true);
  });
});

describe("synced clock", () => {
  const solver = parseEpisodes(solverText).episodes[0];
  const heuristic = parseEpisodes(heuristicText).episodes[0];

  it("aligns both episodes on the same day and clamps a short episode in step mode", () => {
    const day = { ...startClock("day"), day: 2, offset: 0 };
    expect(solver.steps[resolveCursor(solver, day)].day).toBe(2);
    expect(heuristic.steps[resolveCursor(heuristic, day)].day).toBe(2);
    const stepped = advanceClock(day, [solver, heuristic]);
    expect(stepped).toMatchObject({ day: 2, offset: 1 });

    const end = endClock([solver, heuristic], "step");
    expect(end.step).toBe(Math.max(solver.steps.length, heuristic.steps.length) - 1);
    expect(resolveCursor(solver, end)).toBe(solver.steps.length - 1);
    expect(resolveCursor(heuristic, end)).toBe(heuristic.steps.length - 1);
  });
});
