import { useEffect } from "react";
import { episodeLabel, fmtNum } from "../format";
import type { Frame } from "../replay";
import type { Episode, LoadedFile } from "../types";
import { Company } from "./Company";
import { LeakFeed } from "./LeakFeed";
import { Timeline } from "./Timeline";
import { ValueChart } from "./ValueChart";

export function EpisodePane({
  paneId,
  file,
  episode,
  frame,
  ended,
  pin,
  hot,
  onPin,
  onSeek,
  onEpisode,
}: {
  paneId: "A" | "B";
  file: LoadedFile;
  episode: Episode;
  frame: Frame;
  ended: boolean;
  pin: string | null;
  hot: ReadonlySet<string>;
  onPin: (docId: string | null) => void;
  onSeek: (cursor: number) => void;
  onEpisode: (index: number) => void;
}) {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>(`[data-pane="${paneId}"] .company`);
    const el = root?.querySelector<HTMLElement>("[data-accused='true']");
    if (!root || !el) return;
    const er = el.getBoundingClientRect();
    const rr = root.getBoundingClientRect();
    if (er.top < rr.top || er.bottom > rr.bottom) root.scrollTop += er.top - rr.top - 56;
  }, [paneId, episode.agent, episode.seed, episode.tier]);

  return (
    <section className="pane" data-pane={paneId}>
      <header className="summary" data-testid={paneId === "A" ? "summary" : "summary-b"} data-agent={episode.agent}>
        <div className="sum-top">
          <span className="file">{file.label}</span>
          {file.episodes.length > 1 && (
            <label>
              Episode
              <select
                data-testid={paneId === "A" ? "episode-select" : "episode-select-b"}
                value={file.index}
                onChange={(e) => onEpisode(Number(e.target.value))}
              >
                {file.episodes.map((ep, i) => (
                  <option key={`${ep.agent}-${ep.tier}-${ep.seed}-${i}`} value={i}>
                    {episodeLabel(ep)}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <dl className="stats">
          <Stat k="Agent" v={episode.agent} />
          <Stat k="Tier" v={episode.tier} />
          <Stat k="Seed" v={episode.seed === null ? "—" : String(episode.seed)} />
          <Stat k="Score" v={fmtNum(episode.score)} tone={episode.score > 0 ? "good" : episode.score < 0 ? "bad" : ""} />
          <Stat k="Accused" v={episode.accused ?? "—"} />
          <Stat k="Correct" v={episode.correct ? "yes" : "no"} tone={episode.correct ? "good" : "bad"} />
          <Stat k="Final day" v={String(episode.final_day)} />
          <Stat k="End" v={episode.end_reason} />
        </dl>
        {file.warnings.length > 0 && <p className="warnline">{file.warnings.join(" · ")}</p>}
        {ended && <p className="ended">This episode is already over at the synced clock.</p>}
      </header>
      <Timeline steps={episode.steps} cursor={frame.cursor} onSeek={onSeek} />
      <Company frame={frame} hot={hot} />
      <div className="side">
        <LeakFeed
          leaks={frame.leaks}
          hidden={frame.hiddenLeaks}
          feedChecked={frame.feedChecked}
          day={frame.day}
          pin={pin}
          employees={frame.employees}
          onPin={onPin}
        />
        <ValueChart samples={frame.samples} cursor={frame.cursor} steps={episode.steps} onSeek={onSeek} />
      </div>
    </section>
  );
}

function Stat({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <div>
      <dt>{k}</dt>
      <dd className={tone || undefined}>{v}</dd>
    </div>
  );
}
