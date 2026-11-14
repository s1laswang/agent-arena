import { pretty, shortTool, summarize } from "../format";
import { toolTone } from "../colors";
import type { Step } from "../types";

export function StepDetail({ step, side }: { step: Step | null; side?: string }) {
  if (!step) {
    return (
      <div className="detail empty" data-testid="step-detail">
        <p className="note">No step selected.</p>
      </div>
    );
  }
  const answer = step.tool === "interview" && step.result.ok ? step.result.data.answer : null;
  return (
    <div className="detail" data-testid={side === "B" ? "step-detail-b" : "step-detail"}>
      <header>
        <span className={`tool tone-${toolTone(step.tool)}`}>{shortTool(step.tool)}</span>
        <span className="mono">t{step.t}</span>
        <span className="mono">day {step.day}</span>
        <span className={step.result.ok ? "pill good" : "pill bad"}>{step.result.ok ? "ok" : "error"}</span>
        {!step.result.ok && step.result.error && <span className="err">{step.result.error}</span>}
      </header>
      {typeof answer === "string" ? <blockquote>{answer}</blockquote> : <p className="blurb">{blurb(step)}</p>}
      <div className="jsons">
        <section>
          <h3>Arguments</h3>
          <pre>{pretty(step.args)}</pre>
        </section>
        <section>
          <h3>Result</h3>
          <pre>{pretty(step.result)}</pre>
        </section>
      </div>
    </div>
  );
}

function blurb(step: Step): string {
  if (!step.result.ok) return step.result.error ?? "The tool call failed.";
  if (step.tool === "accuse") {
    const who = typeof step.args.employee === "string" ? step.args.employee : "someone";
    return `Accused ${who}. The tool result does not say whether that was the mole.`;
  }
  return summarize(step) || step.tool;
}
