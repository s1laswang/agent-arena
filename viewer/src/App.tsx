import { useEffect, useMemo, useRef, useState } from "react";
import {
  advanceClock,
  clockAt,
  endClock,
  episodeClamped,
  nudgeClock,
  resolveCursor,
  startClock,
  type Clock,
  type SyncMode,
} from "./clock";
import { EpisodePane } from "./components/EpisodePane";
import { StepDetail } from "./components/StepDetail";
import { Transport } from "./components/Transport";
import { parseEpisodes } from "./parse";
import { modelEpisode, project } from "./replay";
import { fetchSample, SAMPLES, type SampleId } from "./samples";
import type { Episode, LoadedFile } from "./types";

export function App() {
  const [a, setA] = useState<LoadedFile | null>(null);
  const [b, setB] = useState<LoadedFile | null>(null);
  const [clock, setClock] = useState<Clock>(startClock("step"));
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(380);
  const [error, setError] = useState<string | null>(null);
  const [pinA, setPinA] = useState<string | null>(null);
  const [pinB, setPinB] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const fileTarget = useRef<"A" | "B" | "auto">("A");
  const onFilesRef = useRef<(target: "A" | "B" | "auto", files: File[]) => void>(() => {});
  const onPlayRef = useRef<() => void>(() => {});

  const epA = a?.episodes[a.index] ?? null;
  const epB = b?.episodes[b.index] ?? null;
  const episodes = useMemo(() => [epA, epB].filter((ep): ep is Episode => ep !== null), [epA, epB]);

  const modelA = useMemo(() => (epA ? modelEpisode(epA) : null), [epA]);
  const modelB = useMemo(() => (epB ? modelEpisode(epB) : null), [epB]);
  const cursorA = epA ? resolveCursor(epA, clock) : -1;
  const cursorB = epB ? resolveCursor(epB, clock) : -1;
  const frameA = useMemo(() => (modelA ? project(modelA, cursorA) : null), [modelA, cursorA]);
  const frameB = useMemo(() => (modelB ? project(modelB, cursorB) : null), [modelB, cursorB]);
  const hotA = useMemo(() => new Set(frameA?.leaks.find((leak) => leak.docId === pinA)?.implicated ?? []), [frameA, pinA]);
  const hotB = useMemo(() => new Set(frameB?.leaks.find((leak) => leak.docId === pinB)?.implicated ?? []), [frameB, pinB]);

  useEffect(() => {
    if (!playing || episodes.length === 0) return;
    const next = advanceClock(clock, episodes);
    if (!next) {
      setPlaying(false);
      return;
    }
    const id = window.setTimeout(() => setClock(next), speed);
    return () => window.clearTimeout(id);
  }, [playing, clock, speed, episodes]);

  useEffect(() => {
    let depth = 0;
    const hasFiles = (event: DragEvent) => {
      const types = event.dataTransfer?.types;
      return Boolean(types && [...types].includes("Files"));
    };
    const over = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
    };
    const enter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setDrag(true);
    };
    const leave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth -= 1;
      if (depth <= 0) {
        depth = 0;
        setDrag(false);
      }
    };
    const drop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDrag(false);
      const files = [...(event.dataTransfer?.files ?? [])];
      const el = document.elementFromPoint(event.clientX, event.clientY);
      const pane = el?.closest("[data-pane]")?.getAttribute("data-pane");
      const target = pane === "A" || pane === "B" ? pane : "auto";
      onFilesRef.current(target, files);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if ((tag === "BUTTON" || tag === "SUMMARY" || tag === "A") && (event.key === " " || event.key === "Enter")) return;
      if (!episodes.length) return;
      if (event.key === " ") {
        event.preventDefault();
        onPlayRef.current();
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        setPlaying(false);
        setClock((c) => nudgeClock(c, episodes, "step", 1));
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        setPlaying(false);
        setClock((c) => nudgeClock(c, episodes, "step", -1));
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setPlaying(false);
        setClock((c) => nudgeClock(c, episodes, "day", 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setPlaying(false);
        setClock((c) => nudgeClock(c, episodes, "day", -1));
      } else if (event.key === "Home") {
        event.preventDefault();
        setPlaying(false);
        setClock((c) => startClock(c.mode));
      } else if (event.key === "End") {
        event.preventDefault();
        setPlaying(false);
        setClock((c) => endClock(episodes, c.mode));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [episodes]);

  function ingest(label: string, text: string): LoadedFile | null {
    const parsed = parseEpisodes(text);
    if (!parsed.episodes.length) {
      setError(parsed.warnings.join(" ") || `${label} has no episodes.`);
      return null;
    }
    setError(null);
    return { label, episodes: parsed.episodes, index: 0, warnings: parsed.warnings };
  }

  function alignTo(file: LoadedFile, other: LoadedFile | null): LoadedFile {
    if (!other) return file;
    const cur = other.episodes[other.index];
    const hit = indexForSeed(file.episodes, cur.seed, cur.tier);
    return hit === null ? file : { ...file, index: hit };
  }

  async function onFiles(target: "A" | "B" | "auto", files: File[]) {
    if (!files.length) return;
    setPlaying(false);
    const loaded: LoadedFile[] = [];
    for (const file of files.slice(0, 2)) {
      const got = ingest(file.name, await file.text());
      if (got) loaded.push(got);
    }
    if (!loaded.length) return;
    if (target === "B") {
      const aligned = alignTo(loaded[0], a);
      setB(aligned);
      setPinB(null);
      const left = a ? a.episodes[a.index] : null;
      const eps = [left, aligned.episodes[aligned.index]].filter((ep): ep is Episode => ep !== null);
      setClock((c) => endClock(eps, c.mode));
      return;
    }
    const fileA = loaded[0];
    setA(fileA);
    setPinA(null);
    let nextB = b;
    if (loaded[1]) {
      nextB = alignTo(loaded[1], fileA);
      setB(nextB);
      setPinB(null);
    }
    const eps = [fileA.episodes[fileA.index]];
    if (nextB) eps.push(nextB.episodes[nextB.index]);
    setClock((c) => endClock(eps, c.mode));
  }
  onFilesRef.current = (target, files) => void onFiles(target, files);

  function pick(target: "A" | "B" | "auto") {
    fileTarget.current = target;
    fileRef.current?.click();
  }

  async function loadSample(id: SampleId) {
    setPlaying(false);
    try {
      const got = await fetchSample(id);
      const file = ingest(got.label, got.text);
      if (!file) return;
      setA(file);
      setB(null);
      setPinA(null);
      setPinB(null);
      setClock(endClock([file.episodes[file.index]], "step"));
      closeMenus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the sample.");
    }
  }

  async function loadCompare() {
    setPlaying(false);
    try {
      const [left, right] = await Promise.all([fetchSample("solver"), fetchSample("heuristic")]);
      const fileA = ingest(left.label, left.text);
      const fileB = ingest(right.label, right.text);
      if (!fileA || !fileB) return;
      const aIndex = indexForSeed(fileA.episodes, 0, "medium") ?? 0;
      const seeded = { ...fileA, index: aIndex };
      const aligned = alignTo(fileB, seeded);
      setA(seeded);
      setB(aligned);
      setPinA(null);
      setPinB(null);
      setClock(endClock([seeded.episodes[seeded.index], aligned.episodes[aligned.index]], "step"));
      closeMenus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the samples.");
    }
  }

  function onPlay() {
    if (!episodes.length) return;
    if (playing) {
      setPlaying(false);
      return;
    }
    if (advanceClock(clock, episodes) === null) setClock((c) => startClock(c.mode));
    setPlaying(true);
  }
  onPlayRef.current = onPlay;

  function onMode(mode: SyncMode) {
    setPlaying(false);
    const ep = epA;
    if (!ep) {
      setClock((c) => ({ ...c, mode }));
      return;
    }
    setClock((c) => clockAt(ep, Math.max(0, resolveCursor(ep, c)), mode));
  }

  function seek(ep: Episode, cursor: number) {
    setPlaying(false);
    setClock((c) => clockAt(ep, cursor, c.mode));
  }

  function setEpisode(which: "A" | "B", index: number) {
    setPlaying(false);
    const nextA = which === "A" ? (a?.episodes[index] ?? null) : epA;
    const nextB = which === "B" ? (b?.episodes[index] ?? null) : epB;
    if (which === "A") {
      setA((file) => (file ? { ...file, index } : file));
      setPinA(null);
    } else {
      setB((file) => (file ? { ...file, index } : file));
      setPinB(null);
    }
    setClock((c) => {
      if (c.mode !== "step") return c;
      const eps = [nextA, nextB].filter((ep): ep is Episode => ep !== null);
      const max = Math.max(0, ...eps.map((ep) => Math.max(0, ep.steps.length - 1)));
      return { ...c, step: Math.min(c.step, max) };
    });
  }

  function matchSeeds() {
    if (!a || !b) return;
    const cur = a.episodes[a.index];
    const hit = indexForSeed(b.episodes, cur.seed, cur.tier);
    if (hit === null) return;
    setPlaying(false);
    setB({ ...b, index: hit });
    setPinB(null);
  }

  const sameSeed = Boolean(epA && epB && epA.seed !== null && epA.seed === epB.seed && epA.tier === epB.tier);
  const canMatch = Boolean(a && b && epA && indexForSeed(b.episodes, epA.seed, epA.tier) !== null && !sameSeed);

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            ◆
          </span>
          <div className="word">
            <strong>Canary</strong>
            <small>episode replay</small>
          </div>
        </div>
        <div className="actions">
          <button type="button" onClick={() => pick(a ? "A" : "auto")}>
            Open
          </button>
          <details className="menu" data-testid="samples-menu">
            <summary>Samples</summary>
            <div className="menu-pop">
              {SAMPLES.map((sample) => (
                <button key={sample.id} type="button" onClick={() => void loadSample(sample.id)}>
                  <b>{sample.label}</b>
                  <small>{sample.hint}</small>
                </button>
              ))}
              <button type="button" data-testid="menu-compare" onClick={() => void loadCompare()}>
                <b>Side by side</b>
                <small>solver vs heuristic</small>
              </button>
            </div>
          </details>
          {a && !b && (
            <button type="button" onClick={() => pick("B")}>
              Compare with file
            </button>
          )}
          {b && (
            <button
              type="button"
              onClick={() => {
                setPlaying(false);
                setB(null);
                setPinB(null);
              }}
            >
              Close compare
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="banner" role="alert">
          {error}
        </div>
      )}

      {b && epA && epB && (
        <div className="seedbar">
          {sameSeed ? (
            <span>Same seed {epA.seed} · {epA.tier}</span>
          ) : (
            <span>
              Seeds differ ({epA.agent} seed {epA.seed ?? "—"} vs {epB.agent} seed {epB.seed ?? "—"})
            </span>
          )}
          {canMatch && (
            <button type="button" onClick={matchSeeds}>
              Use seed {epA.seed} on both
            </button>
          )}
        </div>
      )}

      {!a || !frameA || !epA ? (
        <Empty onOpen={() => pick("auto")} onSample={(id) => void loadSample(id)} onCompare={() => void loadCompare()} />
      ) : (
        <div className={b ? "workspace compare" : "workspace"}>
          <EpisodePane
            paneId="A"
            file={a}
            episode={epA}
            frame={frameA}
            ended={episodeClamped(epA, clock)}
            pin={pinA}
            hot={hotA}
            onPin={setPinA}
            onSeek={(cursor) => seek(epA, cursor)}
            onEpisode={(index) => setEpisode("A", index)}
          />
          {b && epB && frameB && (
            <EpisodePane
              paneId="B"
              file={b}
              episode={epB}
              frame={frameB}
              ended={episodeClamped(epB, clock)}
              pin={pinB}
              hot={hotB}
              onPin={setPinB}
              onSeek={(cursor) => seek(epB, cursor)}
              onEpisode={(index) => setEpisode("B", index)}
            />
          )}
        </div>
      )}

      {epA && frameA && (
        <footer className="dock">
          <Transport
            clock={clock}
            episodes={episodes}
            playing={playing}
            speed={speed}
            onPlay={onPlay}
            onSpeed={setSpeed}
            onMode={onMode}
            onClock={(next) => {
              setPlaying(false);
              setClock(next);
            }}
          />
          <div className={b ? "details compare" : "details"}>
            <StepDetail step={frameA.step} side="A" />
            {b && <StepDetail step={frameB?.step ?? null} side="B" />}
          </div>
        </footer>
      )}

      {drag && (
        <div className="overlay" aria-hidden="true">
          <strong>Drop episodes.jsonl</strong>
          <span>One file loads on the left. Two files open side by side.</span>
        </div>
      )}

      <input
        ref={fileRef}
        data-testid="file-input"
        type="file"
        accept=".jsonl,.json,application/json,application/x-ndjson,text/plain"
        multiple
        hidden
        onChange={(e) => {
          const files = [...(e.target.files ?? [])];
          e.target.value = "";
          void onFiles(fileTarget.current, files);
        }}
      />
    </div>
  );
}

function Empty({
  onOpen,
  onSample,
  onCompare,
}: {
  onOpen: () => void;
  onSample: (id: SampleId) => void;
  onCompare: () => void;
}) {
  return (
    <div className="hero">
      <span className="mark big">◆</span>
      <h1>Replay an investigation</h1>
      <p>
        Drop an <span className="mono">episodes.jsonl</span> file — one episode per line — or open a sample recorded from
        the Canary environment. The viewer rebuilds the company, the canaries, the leak feed, and company value from the
        tool log.
      </p>
      <div className="hero-actions">
        <button type="button" className="primary" onClick={onOpen}>
          Open file
        </button>
        <button type="button" data-testid="load-solver" onClick={() => onSample("solver")}>
          Solver sample
        </button>
        <button type="button" data-testid="load-compare" onClick={onCompare}>
          Solver vs heuristic
        </button>
        <button type="button" data-testid="load-restrict" onClick={() => onSample("restrict")}>
          Restrict-all sample
        </button>
      </div>
    </div>
  );
}

function indexForSeed(episodes: Episode[], seed: number | null, tier: string | null): number | null {
  if (seed === null) return null;
  const tierHit = episodes.findIndex((ep) => ep.seed === seed && ep.tier === tier);
  if (tierHit >= 0) return tierHit;
  const hit = episodes.findIndex((ep) => ep.seed === seed);
  return hit >= 0 ? hit : null;
}

function closeMenus() {
  document.querySelectorAll("details.menu").forEach((el) => el.removeAttribute("open"));
}
