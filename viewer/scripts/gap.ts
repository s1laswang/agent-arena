import { writeFileSync } from "node:fs";
import { buildGap } from "../src/gap";

const root = process.argv[2] ?? "..";
const out = process.argv[3] ?? "public/gap.json";
const g = buildGap(root);
writeFileSync(out, JSON.stringify(g, null, 1));
console.log(g.groups.map((x) => `${x.id}: ${x.rows.length} rows`).join(", "), "->", out);
