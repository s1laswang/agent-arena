import { sortLabels, variantInk } from "../colors";
import type { EmployeeView, Frame } from "../replay";

const DEPT_ORDER = ["Engineering", "Finance", "Sales", "Legal", "Research"];

function deptRank(dept: string): number {
  if (dept === "Unknown") return 1000;
  const i = DEPT_ORDER.indexOf(dept);
  return i === -1 ? 500 : i;
}

export function Company({
  frame,
  hot,
}: {
  frame: Frame;
  hot: ReadonlySet<string>;
}) {
  const labels = new Set<string>();
  for (const canary of frame.canaries) for (const label of Object.keys(canary.variants)) labels.add(label);
  for (const leak of frame.leaks) if (leak.variant) labels.add(leak.variant);
  const ordered = sortLabels(labels);
  const restrictedCount = frame.employees.filter((e) => e.restricted).length;

  const groups = new Map<string, EmployeeView[]>();
  for (const emp of frame.employees) {
    const key = emp.dept ?? "Unknown";
    const list = groups.get(key) ?? [];
    list.push(emp);
    groups.set(key, list);
  }
  const depts = [...groups.keys()].sort((a, b) => deptRank(a) - deptRank(b) || a.localeCompare(b));

  return (
    <section className="company" data-testid="company">
      <header className="company-head">
        <div className="company-title">
          <h2>Company</h2>
          <span>
            {frame.employees.length} people
            {frame.canaries.length > 0 && ` · ${frame.canaries.length} canar${frame.canaries.length === 1 ? "y" : "ies"}`}
            {restrictedCount > 0 && ` · ${restrictedCount} restricted`}
          </span>
        </div>
        <ul className="legend">
          {ordered.map((label) => {
            const ink = variantInk(label);
            return (
              <li key={label}>
                <i style={{ background: ink.bg }} />
                {label}
              </li>
            );
          })}
          <li>
            <i className="swatch restricted" />
            restricted
          </li>
          <li>
            <i className="swatch mole" />
            mole
          </li>
          <li>
            <i className="swatch wrong" />
            wrong accuse
          </li>
        </ul>
        {!frame.rosterKnown && (
          <p className="note">No list_employees result. Cards are ids seen in other calls, without names.</p>
        )}
        {frame.employees.some((e) => e.mole) && (
          <p className="note">The accusation was correct, so the accused employee is the mole.</p>
        )}
        {frame.employees.some((e) => e.exonerated) && (
          <p className="note">Wrong accusation. This log does not name the mole.</p>
        )}
      </header>
      {frame.employees.length === 0 && <p className="note">No employees in this log yet.</p>}
      {depts.map((dept) => (
        <section key={dept} className="dept">
          <h3>{dept}</h3>
          <div className="dept-grid">
            {groups.get(dept)!.map((emp) => (
              <Card key={emp.id} emp={emp} hot={hot.has(emp.id)} live={frame.accusationLive} />
            ))}
          </div>
        </section>
      ))}
    </section>
  );
}

function Card({ emp, hot, live }: { emp: EmployeeView; hot: boolean; live: boolean }) {
  const latest = emp.tags[emp.tags.length - 1];
  const shown = emp.tags.slice(-5);
  const extra = emp.tags.length - shown.length;
  const cls = [
    "card",
    emp.mole ? "mole" : "",
    emp.exonerated ? "wrong" : "",
    emp.accused ? "outcome" : "",
    emp.accused && live ? "live" : "",
    emp.restricted ? "restricted" : "",
    hot ? "hot" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <article
      className={cls}
      data-testid={`emp-${emp.id}`}
      data-mole={emp.mole ? "true" : undefined}
      data-accused={emp.accused ? "true" : undefined}
      data-restricted={emp.restricted ? "true" : undefined}
      style={latest ? { borderLeftColor: variantInk(latest.variant).bg } : undefined}
      title={emp.tags.map((t) => `${t.canaryId} ${t.variant}`).join(" · ")}
    >
      <header>
        <span className="eid">{emp.id}</span>
        {emp.clearance !== null && <span className="clear">L{emp.clearance}</span>}
        {emp.restricted && <span className="pill warn">restricted</span>}
        {emp.mole && <span className="pill good">mole</span>}
        {emp.exonerated && <span className="pill bad">not mole</span>}
        {emp.accused && !emp.mole && !emp.exonerated && <span className="pill">accused</span>}
      </header>
      <strong>{emp.name ?? "Name not in log"}</strong>
      <em>{emp.role ?? (emp.dept ? "\u00a0" : "No roster record")}</em>
      {shown.length > 0 && (
        <div className="tags">
          {extra > 0 && <span className="tag more">+{extra}</span>}
          {shown.map((tag) => {
            const ink = variantInk(tag.variant);
            return (
              <span key={`${tag.canaryId}-${tag.variant}`} className="tag" style={{ background: ink.bg, color: ink.fg }}>
                {tag.canaryId} {tag.variant}
              </span>
            );
          })}
        </div>
      )}
    </article>
  );
}
