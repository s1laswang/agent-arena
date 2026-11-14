import type { Episode } from "./types";

export type SyncMode = "step" | "day";

export type Clock = {
  mode: SyncMode;
  /** Shared step index in step mode. */
  step: number;
  /** 1-based day in day mode. */
  day: number;
  /** Index within the day, shared by both episodes. */
  offset: number;
};

export function stepsOnDay(ep: Episode, day: number): number[] {
  const out: number[] = [];
  ep.steps.forEach((s, i) => {
    if (s.day === day) out.push(i);
  });
  return out;
}

export function maxDayOf(ep: Episode): number {
  let m = 0;
  for (const s of ep.steps) if (s.day > m) m = s.day;
  if (ep.final_day > m) m = ep.final_day;
  return Math.max(1, m);
}

export function resolveCursor(ep: Episode, clock: Clock): number {
  const n = ep.steps.length;
  if (n === 0) return -1;
  if (clock.mode === "step") return Math.max(0, Math.min(clock.step, n - 1));
  const idxs = stepsOnDay(ep, clock.day);
  if (idxs.length === 0) {
    let best = -1;
    for (let i = 0; i < n; i++) if (ep.steps[i].day <= clock.day) best = i;
    return best >= 0 ? best : 0;
  }
  return idxs[Math.max(0, Math.min(clock.offset, idxs.length - 1))];
}

export function clockAt(ep: Episode, cursor: number, mode: SyncMode): Clock {
  const n = ep.steps.length;
  if (n === 0) return { mode, step: 0, day: 1, offset: 0 };
  const c = Math.max(0, Math.min(cursor, n - 1));
  const day = ep.steps[c].day;
  const idxs = stepsOnDay(ep, day);
  const offset = Math.max(0, idxs.indexOf(c));
  return { mode, step: c, day, offset };
}

export function startClock(mode: SyncMode): Clock {
  return { mode, step: 0, day: 1, offset: 0 };
}

export function endClock(episodes: Episode[], mode: SyncMode): Clock {
  if (!episodes.length || episodes.every((e) => e.steps.length === 0)) return { mode, step: 0, day: 1, offset: 0 };
  if (mode === "step") {
    const step = Math.max(...episodes.map((e) => e.steps.length - 1));
    const cursor = Math.min(step, Math.max(0, episodes[0].steps.length - 1));
    return { ...clockAt(episodes[0], cursor, mode), step };
  }
  const day = Math.max(...episodes.map(maxDayOf));
  const offset = Math.max(0, ...episodes.map((e) => stepsOnDay(e, day).length - 1));
  return { mode, step: 0, day, offset };
}

export function advanceClock(clock: Clock, episodes: Episode[]): Clock | null {
  if (!episodes.length) return null;
  if (clock.mode === "step") {
    const max = Math.max(...episodes.map((e) => e.steps.length - 1));
    if (clock.step >= max) return null;
    return { ...clock, step: clock.step + 1 };
  }
  const maxDay = Math.max(1, ...episodes.map(maxDayOf));
  const maxOff = Math.max(-1, ...episodes.map((e) => stepsOnDay(e, clock.day).length - 1));
  if (maxOff >= 0 && clock.offset < maxOff) return { ...clock, offset: clock.offset + 1 };
  if (clock.day >= maxDay) return null;
  return { ...clock, day: clock.day + 1, offset: 0 };
}

export function nudgeClock(clock: Clock, episodes: Episode[], kind: "step" | "day", dir: -1 | 1): Clock {
  const primary = episodes[0];
  if (!primary) return clock;
  if (clock.mode === "step" && kind === "step") {
    const max = Math.max(0, ...episodes.map((e) => Math.max(0, e.steps.length - 1)));
    return { ...clock, step: Math.max(0, Math.min(max, clock.step + dir)) };
  }
  if (clock.mode === "step" && kind === "day") {
    const cursor = resolveCursor(primary, clock);
    return clockAt(primary, adjacentDay(primary, cursor, dir), "step");
  }
  const maxDay = Math.max(1, ...episodes.map(maxDayOf));
  if (kind === "day") {
    return { ...clock, day: Math.max(1, Math.min(maxDay, clock.day + dir)), offset: 0 };
  }
  let { day, offset } = clock;
  if (dir > 0) {
    const maxOff = Math.max(0, ...episodes.map((e) => stepsOnDay(e, day).length - 1));
    if (offset < maxOff) offset += 1;
    else if (day < maxDay) {
      day += 1;
      offset = 0;
    }
  } else if (offset > 0) offset -= 1;
  else if (day > 1) {
    day -= 1;
    offset = Math.max(0, ...episodes.map((e) => stepsOnDay(e, day).length - 1));
  }
  return { ...clock, day, offset };
}

function adjacentDay(ep: Episode, cursor: number, dir: -1 | 1): number {
  if (!ep.steps.length) return 0;
  const day = ep.steps[Math.max(0, cursor)].day;
  const limit = maxDayOf(ep);
  for (let d = day + dir; dir > 0 ? d <= limit : d >= 1; d += dir) {
    const idxs = stepsOnDay(ep, d);
    if (idxs.length) return dir > 0 ? idxs[0] : idxs[idxs.length - 1];
  }
  return cursor;
}

/** The shared clock is past the last action of this episode. */
export function episodeClamped(ep: Episode, clock: Clock): boolean {
  if (ep.steps.length === 0) return true;
  if (clock.mode === "step") return clock.step > ep.steps.length - 1;
  return stepsOnDay(ep, clock.day).length === 0 && clock.day > ep.steps[ep.steps.length - 1].day;
}
