import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { buildGap } from "./gap";

const root = process.env.GAP_ROOT ?? resolve(__dirname, "..", "..");
const md = resolve(root, "data/runs/committed/v1.3/gap_table.md");

describe.skipIf(!existsSync(md))("gap table matches gap_table.md", () => {
  const rows = readFileSync(md, "utf8")
    .split("\n")
    .filter((l) => /^\| (hard|medium|easy) \|/.test(l))
    .map((l) => l.split("|").slice(1, -1).map((c) => c.trim()));
  const g = buildGap(root).groups.find((x) => x.id === "v1.3");
  it("covers every v1.3 row", () => {
    expect(rows.length).toBeGreaterThan(0);
    expect(g).toBeTruthy();
    for (const [tier, agent, n, scoreCi, acc, day] of rows) {
      const r = g!.rows.find((x) => x.tier === tier && x.agent === agent);
      expect(r, `${tier} ${agent}`).toBeTruthy();
      const [score, ci] = scoreCi.split("±").map((s) => Number(s.trim()));
      expect(r!.n).toBe(Number(n));
      expect(Math.abs(r!.score! - score)).toBeLessThanOrEqual(0.00051);
      expect(Math.abs(r!.ci! - ci)).toBeLessThanOrEqual(0.00051);
      expect(Math.abs(r!.accuracy! - Number(acc))).toBeLessThanOrEqual(0.00501);
      if (day !== "–") expect(Math.abs(r!.accuse_day! - Number(day))).toBeLessThanOrEqual(0.0501);
    }
  });
  it("never mixes generations", () => {
    expect(g!.rows.find((x) => x.tier === "hard" && x.agent === "solver")!.n).toBe(20);
  });
});
