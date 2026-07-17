import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { getComparables, draftOutreach } from '../api.js'
import { US_STATES } from '../states.js'
import { useInView } from '../hooks/useInView.js'
import JerseyBadge from './JerseyBadge.jsx'

const POSITIONS = ['GK', 'D', 'M', 'F']
const GENDERS = [
  { value: 'M', label: "Men's" },
  { value: 'W', label: "Women's" },
]
const CLASS_YEARS = ['Fr', 'So', 'Jr', 'Sr']

export default function Comparator() {
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
      setQueryPosition(position)
      setQueryMeta({
        position,
        gender,
        hometown_state: state,
        class_year: classYear || null,
      })
      setData(res)
      setStatus('done')
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
          <Results data={data} position={queryPosition} athlete={queryMeta} />
        )}
      </div>
    </section>
  )
}

function Results({ data, position, athlete }) {
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

      {athlete && <OutreachPanel results={data.results} athlete={athlete} />}
    </div>
  )
}

// Maps an ApiError to a message in the interface's honest voice.
function outreachMessage(err) {
  switch (err?.kind) {
    case 'auth':
      return (
        err.message ||
        'The API key is missing or invalid. Check VITE_API_KEY in frontend/.env.local.'
      )
    case 'unconfigured':
      return 'Email drafting is unavailable right now — the server isn’t configured for it yet.'
    case 'network':
      return 'Could not reach the drafting service. Check your connection and try again.'
    default:
      return err?.message || 'Could not generate a draft right now. Try again.'
  }
}

// A shared panel below the results: the athlete picks one of THEIR real result
// programs, adds optional context, and gets an editable first-contact email
// draft. It never fabricates a coach name/email/date -- gaps come back as
// bracketed placeholders (enforced server-side), and the draft is always shown
// as editable text with a static verify-it-yourself disclaimer.
function OutreachPanel({ results, athlete }) {
  // De-duplicate programs: the same school can appear across several result rows.
  const programs = useMemo(() => {
    const seen = new Map()
    for (const r of results) {
      const key = `${r.school}|${r.division}`
      if (!seen.has(key)) seen.set(key, { school: r.school, division: r.division })
    }
    return [...seen.values()]
  }, [results])

  const [programKey, setProgramKey] = useState(
    `${programs[0].school}|${programs[0].division}`
  )
  const [gpa, setGpa] = useState('')
  const [why, setWhy] = useState('')
  const [clipUrl, setClipUrl] = useState('')

  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [draft, setDraft] = useState('')
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)

  const program =
    programs.find((p) => `${p.school}|${p.division}` === programKey) || programs[0]

  async function onDraft(e) {
    e.preventDefault()
    setStatus('loading')
    setError(null)
    setCopied(false)
    try {
      const res = await draftOutreach({
        position: athlete.position,
        hometown_state: athlete.hometown_state,
        gender: athlete.gender,
        class_year: athlete.class_year || undefined,
        school: program.school,
        division: program.division,
        gpa: gpa.trim() || undefined,
        why_interested: why.trim() || undefined,
        clip_url: clipUrl.trim() || undefined,
      })
      setDraft(res.draft)
      setStatus('done')
    } catch (err) {
      setError(outreachMessage(err))
      setStatus('error')
    }
  }

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(draft)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API blocked (e.g. non-secure context) — the user can still
      // select the text manually; just leave the button state unchanged.
    }
  }

  return (
    <section className="outreach" aria-labelledby="outreach-heading">
      <div className="outreach__intro">
        <p className="eyebrow">Optional — Outreach Assistant</p>
        <h3 id="outreach-heading" className="outreach__title">
          Draft a coach outreach email
        </h3>
        <p className="outreach__lede">
          Pick one of the real programs above and get a first-contact email draft
          you can edit. It writes from what you enter — it never looks up or
          invents a coach’s name, email, or dates.
        </p>
      </div>

      <form className="outreach-form" onSubmit={onDraft}>
        <div className="field">
          <label className="field__label" htmlFor="outreach-program">
            Program (from your results)
          </label>
          <select
            id="outreach-program"
            className="select"
            value={programKey}
            onChange={(e) => setProgramKey(e.target.value)}
          >
            {programs.map((p) => (
              <option key={`${p.school}|${p.division}`} value={`${p.school}|${p.division}`}>
                {p.school} ({p.division})
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="outreach-gpa">
            GPA <span className="field__optional">(optional)</span>
          </label>
          <input
            id="outreach-gpa"
            className="text-input"
            type="text"
            inputMode="decimal"
            placeholder="e.g. 3.8"
            value={gpa}
            onChange={(e) => setGpa(e.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="outreach-why">
            Why this program? <span className="field__optional">(optional, your own words)</span>
          </label>
          <textarea
            id="outreach-why"
            className="textarea"
            rows={3}
            placeholder="What draws you to this school and program — leave blank and the draft will mark a spot for you to fill in."
            value={why}
            onChange={(e) => setWhy(e.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="outreach-clip">
            Highlight clip link{' '}
            <span className="field__optional">(optional — paste a Moment-Finder clip URL)</span>
          </label>
          <input
            id="outreach-clip"
            className="text-input"
            type="url"
            placeholder="https://…"
            value={clipUrl}
            onChange={(e) => setClipUrl(e.target.value)}
          />
        </div>

        <button type="submit" className="cta" disabled={status === 'loading'}>
          {status === 'loading' ? 'Drafting…' : 'Draft outreach email'}
        </button>
      </form>

      {status === 'error' && (
        <div className="notice notice--error" role="alert">
          <span className="notice__tag">Couldn’t draft that</span>
          <p>{error}</p>
        </div>
      )}

      {status === 'done' && (
        <div className="outreach-result">
          <div className="outreach-note" role="note">
            <span className="notice__tag">Draft — verify before sending</span>
            <p>
              This is a draft to edit, not verified contact information. Confirm
              the coach’s name and email yourself (most athletics staff
              directories list them), and check your sport’s current NCAA
              contact-period rules — a non-response is often about timing, not
              interest.
            </p>
          </div>

          <label className="field__label" htmlFor="outreach-draft">
            Your editable draft
          </label>
          <textarea
            id="outreach-draft"
            className="outreach-draft"
            rows={16}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck
          />

          <div className="outreach__actions">
            <button type="button" className="btn-secondary" onClick={onCopy}>
              {copied ? 'Copied ✓' : 'Copy to clipboard'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
