import { variantInk } from "../colors";
import type { EmployeeView, LeakView } from "../replay";

export function LeakFeed({
  leaks,
  hidden,
  feedChecked,
  day,
  pin,
  employees,
  onPin,
}: {
  leaks: LeakView[];
  hidden: number;
  feedChecked: boolean;
  day: number;
  pin: string | null;
  employees: EmployeeView[];
  onPin: (docId: string | null) => void;
}) {
  const nameOf = (id: string) => employees.find((e) => e.id === id)?.name;

  return (
    <section className="leaks" data-testid="leaks">
      <header className="leaks-h">
        <h2>Leak feed</h2>
        <span>day {day}</span>
      </header>
      {!feedChecked && <p className="note">check_leak_feed was never called.</p>}
      {feedChecked && leaks.length === 0 && <p className="note">Nothing has surfaced by day {day}.</p>}
      <ol>
        {leaks.map((leak) => {
          const pinned = pin === leak.docId;
          const ink = leak.variant ? variantInk(leak.variant) : null;
          const who = leak.implicated.slice(0, 4).map((id) => nameOf(id) ?? id);
          const more = leak.implicated.length - who.length;
          return (
            <li key={leak.docId}>
              <button
                type="button"
                className={pinned ? "leak on" : "leak"}
                data-testid={`leak-${leak.docId}`}
                style={ink ? { borderLeftColor: ink.bg } : undefined}
                onClick={() => onPin(pinned ? null : leak.docId)}
              >
                <span className="leak-top">
                  <span className="dayn">d{leak.surfacedDay}</span>
                  {leak.variant && ink && (
                    <span className="vtag" style={{ background: ink.bg, color: ink.fg }}>
                      {leak.variant}
                    </span>
                  )}
                  {!leak.variant && <span className="vtag plain">{leak.isCanary ? "canary" : "doc"}</span>}
                  <span className="docid">{leak.docId}</span>
                  {leak.unread && <span className="unread">unread</span>}
                </span>
                <span className="leak-title">{leak.title}</span>
                {who.length > 0 && (
                  <span className="who">
                    {leak.variant ? "variant group" : "recipients"}: {who.join(", ")}
                    {more > 0 ? ` +${more}` : ""}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
      {hidden > 0 && (
        <p className="note">
          {hidden} more in the log {hidden === 1 ? "has" : "have"} not surfaced yet.
        </p>
      )}
    </section>
  );
}
