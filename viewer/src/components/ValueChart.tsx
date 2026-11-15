import { useEffect, useId, useRef, useState } from "react";
import { fmtNum } from "../format";
import type { VSample } from "../replay";
import type { Step } from "../types";

export function ValueChart({
  samples,
  cursor,
  steps,
  onSeek,
}: {
  samples: VSample[];
  cursor: number;
  steps: Step[];
  onSeek: (index: number) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(280);
  const gradId = useId().replace(/:/g, "");

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => {
      const w = Math.floor(el.clientWidth);
      setWidth((prev) => (prev === w || w < 40 ? prev : w));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const height = 156;
  const padL = 34;
  const padR = 10;
  const padT = 8;
  const padB = 16;
  const maxT = steps.length - 1;
  const observed = samples.some((s) => s.source === "status" || s.source === "advance_day");
  const usedMeta = samples.some((s) => s.source === "meta");
  const cursorV = holdAt(samples, cursor);

  if (maxT < 0) {
    return (
      <section className="chart" data-testid="chart">
        <header className="chart-h">
          <h2>Company value</h2>
          <strong>{fmtNum(cursorV)}</strong>
        </header>
        <p className="note">No steps to plot.</p>
      </section>
    );
  }

  const plotW = Math.max(1, width - padL - padR);
  const plotH = Math.max(1, height - padT - padB);
  let yLo = 0;
  let yHi = 1;
  for (const sample of samples) {
    if (sample.v < yLo) yLo = sample.v;
    if (sample.v > yHi) yHi = sample.v;
  }
  const yPad = (yHi - yLo) * 0.08 || 0.05;
  yLo -= yPad;
  yHi += yPad;
  const xOf = (t: number) => padL + ((t + 1) / (maxT + 1)) * plotW;
  const yOf = (v: number) => padT + (1 - (v - yLo) / (yHi - yLo)) * plotH;

  const at = new Map<number, number>();
  for (const sample of samples) at.set(sample.t, sample.v);
  let hold = at.has(-1) ? at.get(-1)! : 1;
  const pts: { t: number; x: number; y: number }[] = [];
  for (let t = -1; t <= maxT; t++) {
    if (at.has(t)) hold = at.get(t)!;
    pts.push({ t, x: xOf(t), y: yOf(hold) });
  }
  const cursorPt = pts.find((p) => p.t === cursor) ?? pts[pts.length - 1];
  const past = pts.filter((p) => p.t <= cursor);
  const future = pts.filter((p) => p.t >= cursor);
  const pastPath = line(past);
  const futurePath = line(future);
  const baseY = height - padB;
  const area =
    past.length > 0 ? `${pastPath} L ${past[past.length - 1].x.toFixed(1)} ${baseY} L ${past[0].x.toFixed(1)} ${baseY} Z` : "";

  const ticks = [0, 0.5, 1].filter((t) => t >= yLo && t <= yHi);
  const dayLabels: { day: number; x: number }[] = [];
  let prevDay = -1;
  steps.forEach((step, i) => {
    if (step.day === prevDay) return;
    prevDay = step.day;
    const x = xOf(i);
    if (!dayLabels.length || x - dayLabels[dayLabels.length - 1].x > 26) dayLabels.push({ day: step.day, x });
  });
  const dots = samples.filter((s) => s.t >= 0 && s.source !== "initial");

  const seek = (event: { currentTarget: SVGSVGElement; clientX: number }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const t = Math.round(-1 + ((px - padL) / plotW) * (maxT + 1));
    onSeek(Math.max(0, Math.min(maxT, t)));
  };

  return (
    <section className="chart" data-testid="chart">
      <header className="chart-h">
        <h2>Company value</h2>
        <strong>{fmtNum(cursorV)}</strong>
      </header>
      <div className="chart-body" ref={wrap}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Company value ${fmtNum(cursorV)} at step ${Math.max(0, cursor)}`}
          onClick={seek}
        >
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#e2b657" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#e2b657" stopOpacity="0" />
            </linearGradient>
          </defs>
          {ticks.map((tick) => (
            <g key={tick}>
              <line x1={padL} x2={width - padR} y1={yOf(tick)} y2={yOf(tick)} stroke="#313a34" />
              <text x={2} y={yOf(tick) + 3}>
                {Number.isInteger(tick) ? String(tick) : tick.toFixed(1)}
              </text>
            </g>
          ))}
          {area && <path d={area} fill={`url(#${gradId})`} />}
          <path d={pastPath} fill="none" stroke="#e2b657" strokeWidth="1.7" />
          {future.length > 1 && (
            <path d={futurePath} fill="none" stroke="#e2b657" strokeWidth="1.4" strokeDasharray="3 3" opacity="0.45" />
          )}
          {dots.map((sample) => (
            <circle key={`${sample.source}-${sample.t}`} cx={xOf(sample.t)} cy={yOf(sample.v)} r={2.4} fill="#f0d48a" />
          ))}
          <line
            x1={cursorPt.x}
            x2={cursorPt.x}
            y1={padT}
            y2={baseY}
            stroke="#e2b657"
            strokeDasharray="2 3"
            opacity="0.85"
          />
          <circle cx={cursorPt.x} cy={cursorPt.y} r={4} fill="#e2b657" stroke="#1a1408" strokeWidth={2} />
          {dayLabels.map((d) => (
            <text key={d.day} x={d.x} y={height - 3} textAnchor="middle">
              {d.day}
            </text>
          ))}
        </svg>
      </div>
      <p className="chart-note">
        {observed
          ? "Read from status and the close of each day. A canary’s cost shows up on the next status."
          : "No status or advance_day value in this log. The line holds the starting value of 1."}
        {usedMeta ? " The last point is the episode’s final V." : ""}
      </p>
    </section>
  );
}

function holdAt(samples: VSample[], cursor: number): number | null {
  let v: number | null = null;
  for (const sample of samples) if (sample.t <= cursor) v = sample.v;
  return v;
}

function line(points: { x: number; y: number }[]): string {
  return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
}
