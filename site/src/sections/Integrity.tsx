const HOLDS = [
  { t: 'Fuzz', d: 'Malformed args, homoglyph ids, a parallel accuse race, calls after the end. 0 violations. Best non-solver score 0.' },
  { t: 'No seed in the output', d: 'Tool results, the instruction, and the tool spec never print the seed.' },
  { t: 'No side channel', d: 'Mole and innocent return the same errors, shapes, and lengths. Accuse does not say whether it was right.' },
  { t: 'Value only falls', d: 'A rejected call changes nothing but the tool count. Unrestrict never raises V.' },
  { t: 'Ledger is locked', d: 'The grader endpoint requires a token. A wrong or missing token is refused.' },
  { t: 'Text stays quiet', d: 'A text-only probe of messages and interviews did not beat a fair-chance bar.' },
  { t: 'Logs are not enough', d: 'A log-only attacker was a real finding, then fixed in tiers v1: easy 28%, medium 1%, hard 3%.' },
  { t: 'Dev seeds stay in the lab', d: 'The server refuses them unless CANARY_ALLOW_DEV=1. They are public by design.' },
]

export function Integrity() {
  return (
    <div className="integrity">
      <p className="lede slim">
        Thirty-three attacks on our own reward, each logged in the exploit file, each with a regression test. Two were
        real and are closed. One is still open.
      </p>
      <div className="case-row">
        <article className="case is-closed">
          <p className="status">Closed · #1</p>
          <h3>Stop-early lottery</h3>
          <p>
            Accuse a random employee on day 1. Under the old 0/1 score this was a free ticket: about +0.10 on medium.
            A wrong accusation now scores −1, and the same policy lands around −0.96 on medium (−0.80 easy, −0.96 hard,
            50 seeds).
          </p>
        </article>
        <article className="case is-closed">
          <p className="status">Closed · #24 · #28</p>
          <h3>Judge worlds failed open</h3>
          <p>
            With no secret, public code rebuilt the world and named the mole. Score 1.0, including 90 of 90 judge seeds
            when the finding was re-run. Judge worlds now fail closed: no secret means a fresh secret for that server
            start, and no world file containing the mole is committed.
          </p>
        </article>
        <article className="case is-open">
          <p className="status">Open · #27</p>
          <h3>Same-user environment</h3>
          <p>
            Found by an external judge run. A process under the same user could read the server’s environment and
            recover the secret. Still open on the harness. Secrets are moving to mode-0600 files, and the Harbor sidecar
            keeps the server out of the agent’s process namespace.
          </p>
        </article>
      </div>
      <div className="holds">
        <p className="kicker">Probes that held</p>
        <ul>
          {HOLDS.map((item) => (
            <li key={item.t}>
              <b>{item.t}</b>
              <span>{item.d}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
