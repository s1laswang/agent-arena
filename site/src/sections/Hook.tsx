import { Mark } from '../components/Mark'

export function Hook() {
  return (
    <div className="hook">
      <header className="toprule">
        <Mark size={26} />
        <span className="word">Canary</span>
        <span className="spacer" />
        <span>Junction 2026</span>
        <span className="dot" aria-hidden="true" />
        <span>Break the Agent</span>
      </header>
      <div className="hook-grid">
        <div className="hook-copy">
          <p className="kicker">Dossier 01 · Catch the mole</p>
          <h1>
            Your next coworker is an AI agent.
            <em>So is your next insider threat.</em>
          </h1>
        </div>
        <aside className="stakes">
          <p className="stakes-lead">One mole. One accusation.</p>
          <ul>
            <li>
              <b>Correct</b>
              <span>Score the company value that is left.</span>
            </li>
            <li>
              <b>Wrong</b>
              <span>Score −1. A guess is worse than waiting.</span>
            </li>
            <li>
              <b>Silence</b>
              <span>Score 0. Doing nothing is exact.</span>
            </li>
          </ul>
          <p className="hint">Arrow keys move through the nine sections.</p>
        </aside>
      </div>
    </div>
  )
}
