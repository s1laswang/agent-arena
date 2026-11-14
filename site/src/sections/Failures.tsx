const CARDS = [
  {
    n: '01',
    tag: 'Uninformative canary',
    title: 'One variant teaches nothing',
    body: 'On medium seed 5, day 1, gpt-5.5 sent a canary to three people under a single label. A single label splits nobody, so the belief stayed at 0.05. The same silence happens when almost everyone receives the copy: a careful mole tends to skip a widely shared canary.',
    cost: '0 information',
    foot: 'Draft gap report · day 1 of the annotated run',
  },
  {
    n: '02',
    tag: 'premature_accusation',
    title: 'A coin flip is worth less than nothing',
    body: 'By day 14 the field was e02 against e14, each at probability 0.50, after a long run of interviews that barely moved the belief. gpt-5.5 accused e02. Wrong. Score −1. Doing nothing would have scored 0. The expected value of a 50/50 accusation is 0.5·V − 0.5, which is below zero.',
    cost: '−1',
    foot: 'Tag on the final step · regret 0.18 V',
  },
  {
    n: '03',
    tag: 'ignored_delay',
    title: 'The leak cannot arrive in time',
    body: 'On days 12 and 13 the agent planted more canaries on that same pair. Medium leaks surface one to three days late, and the horizon is day 14. A canary planted that late is unlikely to show up before the episode ends. The split that would have resolved the pair belonged on days 9–10.',
    cost: 'Too late',
    foot: 'Tag on the final step · delay 1–3 days',
  },
]

export function Failures() {
  return (
    <div className="fails">
      <p className="lede slim">
        Annotated case from the draft gap report. Medium seed 5, gpt-5.5, score −1.0. Directional, not the official run.
      </p>
      <div className="fail-grid">
        {CARDS.map((card) => (
          <article key={card.n} className="file">
            <header>
              <span>{card.n}</span>
              <span className="tag">{card.tag}</span>
            </header>
            <h3>{card.title}</h3>
            <p>{card.body}</p>
            <p className="cost">{card.cost}</p>
            <footer>{card.foot}</footer>
          </article>
        ))}
      </div>
    </div>
  )
}
