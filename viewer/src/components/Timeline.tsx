import { useEffect, useRef } from "react";
import { toolTone } from "../colors";
import { shortTool, summarize } from "../format";
import type { Step } from "../types";

export function Timeline({
  steps,
  cursor,
  onSeek,
}: {
  steps: Step[];
  cursor: number;
  onSeek: (index: number) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const el = root.querySelector<HTMLElement>("[data-current='true']");
    if (!el) return;
    const er = el.getBoundingClientRect();
    const rr = root.getBoundingClientRect();
    if (er.top < rr.top) root.scrollTop -= rr.top - er.top + 8;
    else if (er.bottom > rr.bottom) root.scrollTop += er.bottom - rr.bottom + 8;
  }, [cursor, steps]);

  const groups: { day: number; items: { step: Step; index: number }[] }[] = [];
  steps.forEach((step, index) => {
    const last = groups[groups.length - 1];
    if (!last || last.day !== step.day) groups.push({ day: step.day, items: [{ step, index }] });
    else last.items.push({ step, index });
  });

  return (
    <div className="timeline" ref={ref} data-testid="timeline">
      {groups.map((group) => (
        <section key={group.day}>
          <h3 className="day-h">Day {group.day}</h3>
          {group.items.map(({ step, index }) => {
            const on = index === cursor;
            return (
              <button
                key={index}
                type="button"
                className={on ? "step on" : "step"}
                data-current={on ? "true" : undefined}
                onClick={() => onSeek(index)}
              >
                <span className="t">{step.t}</span>
                <span className={`tool tone-${toolTone(step.tool)}`}>{shortTool(step.tool)}</span>
                <span className="sum">{summarize(step)}</span>
                {!step.result.ok && <span className="bang">!</span>}
              </button>
            );
          })}
        </section>
      ))}
      {steps.length === 0 && <p className="note">No tool calls.</p>}
    </div>
  );
}
