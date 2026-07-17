import { useLayoutEffect, useRef, useState } from 'react'
import { getComparables } from '../api.js'
import { US_STATES } from '../states.js'
import { useInView } from '../hooks/useInView.js'
import JerseyBadge from './JerseyBadge.jsx'

const POSITIONS = ['GK', 'D', 'M', 'F']
const GENDERS = [
  { value: 'M', label: "Men's" },
  { value: 'W', label: "Women's" },
]
const CLASS_YEARS = ['Fr', 'So', 'Jr', 'Sr']

// onResults lifts a successful search up to App so the Outreach Assistant section
// (rendered separately, below Moment-Finder) can draft for one of these programs.
export default function Comparator({ onResults = () => {} }) {
  const [position, setPosition] = useState(null)
  const [gender, setGender] = useState(null)
  const [state, setState] = useState('')
  const [classYear, setClassYear] = useState(null)

  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [data, setData] = useState(null)
  // The queried position, captured at submit — result rows don't echo it back,
  // and every result shares the position that was filtered on.
  const [queryPosition, setQueryPosition] = useState(null)
  // Snapshot of the athlete facts that produced these results, captured at submit
  // so the Outreach draft uses what was searched even if the form is edited after.
  const [queryMeta, setQueryMeta] = useState(null)
  const [error, setError] = useState(null)

  const canSubmit = position && gender && state

  const [introRef, introInView] = useInView()

  // Slide a thin indicator to the selected position badge. Measures the actual
  // button geometry so it stays correct when the row wraps or the page resizes.
  const btnRefs = useRef({})
  const connectorRef = useRef(null)
  useLayoutEffect(() => {
    function place() {
      const line = connectorRef.current
      if (!line) return
      const btn = position ? btnRefs.current[position] : null
      if (!btn) {
        line.style.opacity = '0'
        return
      }
      line.style.width = `${btn.offsetWidth}px`
      line.style.transform = `translateX(${btn.offsetLeft}px)`
      line.style.top = `${btn.offsetTop + btn.offsetHeight + 6}px`
      line.style.opacity = '1'
    }
    place()
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [position])

  async function onSubmit(e) {
    e.preventDefault()
    if (!canSubmit) return
    setStatus('loading')
    setError(null)
    try {
      const res = await getComparables({
        position,
        gender,
        hometown_state: state,
        class_year: classYear || undefined,
      })
      const meta = {
        position,
        gender,
        hometown_state: state,
        class_year: classYear || null,
      }
      setQueryPosition(position)
      setQueryMeta(meta)
      setData(res)
      setStatus('done')
      // Hand the results to App so the Outreach Assistant section can use them.
      onResults({ results: res.results, athlete: meta })
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <section className="feature" id="comparator" aria-labelledby="comparator-heading">
      <div ref={introRef} className={`feature__intro ${introInView ? 'is-revealed' : ''}`}>
        <p className="eyebrow">Feature 01 — Comparator</p>
        <h2 id="comparator-heading" className="feature__title">
          Real players like you
        </h2>
        <p className="feature__lede">
          Pick a position, a home state, and a squad. See real college players who
          share that profile and the programs they actually play for. No score, no
          prediction — just the roster reality.
        </p>
      </div>

      <form className="comparator-form" onSubmit={onSubmit}>
        <fieldset className="field">
          <legend className="field__label">Position</legend>
          <div className="badge-row" role="group" aria-label="Select a position">
            {POSITIONS.map((p) => (
              <button
                type="button"
                key={p}
                ref={(el) => (btnRefs.current[p] = el)}
                className={`badge-button ${position === p ? 'is-selected' : ''}`}
                aria-pressed={position === p}
                onClick={() => setPosition(p)}
              >
                <JerseyBadge position={p} size="lg" active={position === p} />
              </button>
            ))}
            <span className="badge-connector" ref={connectorRef} aria-hidden="true" />
          </div>
        </fieldset>

        <fieldset className="field">
          <legend className="field__label">Squad</legend>
          <div className="segmented" role="group" aria-label="Select a squad">
            {GENDERS.map((g) => (
              <button
                type="button"
                key={g.value}
                className={`segmented__option ${gender === g.value ? 'is-selected' : ''}`}
                aria-pressed={gender === g.value}
                onClick={() => setGender(g.value)}
              >
                {g.label}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <label className="field__label" htmlFor="state-select">
            Home state
          </label>
          <select
            id="state-select"
            className="select"
            value={state}
            onChange={(e) => setState(e.target.value)}
          >
            <option value="">Choose a state…</option>
            {US_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <fieldset className="field">
          <legend className="field__label">
            Class year <span className="field__optional">(optional)</span>
          </legend>
          <div className="pill-row" role="group" aria-label="Select a class year">
            <button
              type="button"
              className={`pill ${!classYear ? 'is-selected' : ''}`}
              aria-pressed={!classYear}
              onClick={() => setClassYear(null)}
            >
              Any
            </button>
            {CLASS_YEARS.map((c) => (
              <button
                type="button"
                key={c}
                className={`pill ${classYear === c ? 'is-selected' : ''}`}
                aria-pressed={classYear === c}
                onClick={() => setClassYear(c)}
              >
                {c}
              </button>
            ))}
          </div>
        </fieldset>

        <button type="submit" className="cta" disabled={!canSubmit || status === 'loading'}>
          {status === 'loading' ? 'Finding players…' : 'Find comparable players'}
        </button>
      </form>

      <div className="comparator-results" aria-live="polite">
        {status === 'idle' && (
          <div className="placeholder">
            <p className="placeholder__title">Enter your position and hometown</p>
            <p className="placeholder__sub">
              to see real players like you and where they play.
            </p>
          </div>
        )}

        {status === 'loading' && (
          <div className="placeholder">
            <p className="placeholder__title">Searching the rosters…</p>
          </div>
        )}

        {status === 'error' && (
          <div className="notice notice--error">
            <p>{error || 'Something went wrong. Try again.'}</p>
          </div>
        )}

        {status === 'done' && data && (
          <Results data={data} position={queryPosition} />
        )}
      </div>
    </section>
  )
}

function Results({ data, position }) {
  if (!data.count) {
    return (
      <div className="placeholder">
        <p className="placeholder__title">No players found for that combination.</p>
        <p className="placeholder__sub">
          Try a different state or squad — the dataset covers 43 programs, so some
          exact combinations come up empty.
        </p>
      </div>
    )
  }

  const isRegional = data.match_type === 'region'

  return (
    <div>
      {isRegional && (
        <div className="notice notice--regional" role="status">
          <span className="notice__tag">Regional matches</span>
          <p>
            Not enough players from that exact state, so these are from the
            surrounding region — <strong>not</strong> your home state. Treat them
            as nearby comparisons, not exact ones.
          </p>
        </div>
      )}

      <p className="results-count">
        <span className="mono">{data.count}</span>{' '}
        {isRegional ? 'regional' : 'in-state'} {data.count === 1 ? 'player' : 'players'}
      </p>

      <ul className="player-list">
        {data.results.map((p, i) => (
          <li
            className="player-card"
            key={`${p.school}-${p.hometown}-${i}`}
            // Stagger only the first ~10 rows; the rest share one delay and reveal
            // together, so long lists don't cascade for seconds.
            style={{ animationDelay: `${Math.min(i, 9) * 0.06}s` }}
          >
            <JerseyBadge position={position} size="md" />
            <div className="player-card__body">
              <p className="player-card__school">{p.school}</p>
              <p className="player-card__hometown mono">{p.hometown}</p>
            </div>
            <div className="player-card__meta">
              <span className="tag tag--division mono">{p.division}</span>
              {p.class_year && <span className="tag mono">{p.class_year}</span>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
