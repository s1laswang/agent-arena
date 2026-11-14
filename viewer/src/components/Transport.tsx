import { advanceClock, endClock, nudgeClock, startClock, type Clock, type SyncMode } from "../clock";
import type { Episode } from "../types";

export function Transport({
  clock,
  episodes,
  playing,
  speed,
  onPlay,
  onSpeed,
  onMode,
  onClock,
}: {
  clock: Clock;
  episodes: Episode[];
  playing: boolean;
  speed: number;
  onPlay: () => void;
  onSpeed: (ms: number) => void;
  onMode: (mode: SyncMode) => void;
  onClock: (clock: Clock) => void;
}) {
  const maxStep = Math.max(0, ...episodes.map((e) => e.steps.length - 1));
  const maxDay = Math.max(1, ...episodes.map((e) => Math.max(e.final_day, ...e.steps.map((s) => s.day))));
  const maxOffset = Math.max(
    0,
    ...episodes.map((e) => e.steps.filter((s) => s.day === clock.day).length - 1),
  );
  const atEnd = advanceClock(clock, episodes) === null;

  return (
    <div className="transport">
      <button type="button" className="icon" title="Start (Home)" onClick={() => onClock(startClock(clock.mode))}>
        <Ico d="M3 3h2v10H3zM13 3.2 6.7 8 13 12.8z" />
      </button>
      <button type="button" className="icon" title="Back" onClick={() => onClock(nudgeClock(clock, episodes, "step", -1))}>
        <Ico d="M11.5 3.2 5.2 8l6.3 4.8z" />
      </button>
      <button
        type="button"
        className="icon primary"
        data-testid="play"
        aria-pressed={playing}
        title={playing ? "Pause (space)" : atEnd ? "Replay from the start (space)" : "Play (space)"}
        onClick={onPlay}
      >
        {playing ? <Ico d="M3.5 2.8h3.2v10.4H3.5zM9.3 2.8h3.2v10.4H9.3z" /> : <Ico d="M4.5 2.8v10.4L13 8z" />}
      </button>
      <button type="button" className="icon" title="Forward" onClick={() => onClock(nudgeClock(clock, episodes, "step", 1))}>
        <Ico d="M4.5 3.2 10.8 8 4.5 12.8z" />
      </button>
      <button type="button" className="icon" title="End (End)" onClick={() => onClock(endClock(episodes, clock.mode))}>
        <Ico d="M11 3h2v10h-2zM3 3.2 9.3 8 3 12.8z" />
      </button>

      <div className="seg" role="group" aria-label="Sync" data-testid="sync-mode">
        <button type="button" aria-pressed={clock.mode === "step"} onClick={() => onMode("step")}>
          Step
        </button>
        <button type="button" aria-pressed={clock.mode === "day"} onClick={() => onMode("day")}>
          Day
        </button>
      </div>

      <label className="scrub">
        <span>{clock.mode === "step" ? `t ${Math.min(clock.step, maxStep)} / ${maxStep}` : `day ${clock.day} / ${maxDay}`}</span>
        <input
          data-testid="scrubber"
          type="range"
          min={clock.mode === "step" ? 0 : 1}
          max={clock.mode === "step" ? maxStep : maxDay}
          value={clock.mode === "step" ? Math.min(clock.step, maxStep) : clock.day}
          onChange={(e) => {
            const n = Number(e.target.value);
            onClock(clock.mode === "step" ? { ...clock, step: n } : { ...clock, day: n, offset: 0 });
          }}
        />
      </label>
      {clock.mode === "day" && (
        <label className="scrub offset">
          <span>action {Math.min(clock.offset, maxOffset) + 1}</span>
          <input
            data-testid="offset-scrubber"
            type="range"
            min={0}
            max={maxOffset}
            value={Math.min(clock.offset, maxOffset)}
            onChange={(e) => onClock({ ...clock, offset: Number(e.target.value) })}
          />
        </label>
      )}

      <select aria-label="Playback speed" value={speed} onChange={(e) => onSpeed(Number(e.target.value))}>
        <option value={700}>Slow</option>
        <option value={380}>Normal</option>
        <option value={140}>Fast</option>
      </select>
      <span className="keys">← → step · ↑ ↓ day · space play</span>
    </div>
  );
}

function Ico({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d={d} fill="currentColor" />
    </svg>
  );
}
