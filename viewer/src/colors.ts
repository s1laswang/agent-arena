/** Stable colours for canary variant labels. A–H are fixed so a leak tag matches the people who received it. */

export type Ink = { bg: string; fg: string };

const NAMED: Record<string, Ink> = {
  A: { bg: "#2bb5a0", fg: "#04221e" },
  B: { bg: "#e2b657", fg: "#2a1d05" },
  C: { bg: "#e07a9a", fg: "#2a0c16" },
  D: { bg: "#7ea8c4", fg: "#07141c" },
  E: { bg: "#b7a3e0", fg: "#1a1028" },
  F: { bg: "#d4784a", fg: "#2a1006" },
  G: { bg: "#9cba7a", fg: "#141c0c" },
  H: { bg: "#d4d0c8", fg: "#1c1a16" },
};

const EXTRA: Ink[] = Object.values(NAMED);

export function variantInk(label: string): Ink {
  if (NAMED[label]) return NAMED[label];
  let h = 0;
  for (let i = 0; i < label.length; i++) h = (h * 33 + label.charCodeAt(i)) >>> 0;
  return EXTRA[h % EXTRA.length];
}

export function sortLabels(labels: Iterable<string>): string[] {
  const rank = (label: string) => {
    const i = Object.keys(NAMED).indexOf(label);
    return i === -1 ? 100 : i;
  };
  return [...labels].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export function toolTone(tool: string): string {
  switch (tool) {
    case "plant_canary":
      return "gold";
    case "check_leak_feed":
      return "leak";
    case "accuse":
      return "accuse";
    case "restrict_access":
    case "unrestrict_access":
      return "restrict";
    case "advance_day":
      return "advance";
    case "interview":
      return "talk";
    case "read_access_logs":
      return "logs";
    default:
      return "muted";
  }
}
