import { useEffect, useMemo, useState } from 'react'
import { draftOutreach, getPrograms } from '../api.js'
import { US_STATES } from '../states.js'
import { useInView } from '../hooks/useInView.js'

const POSITIONS = [
  { value: 'GK', label: 'Goalkeeper' },
  { value: 'D', label: 'Defender' },
  { value: 'M', label: 'Midfielder' },
  { value: 'F', label: 'Forward' },
]
const GENDERS = [
  { value: 'M', label: "Men's" },
  { value: 'W', label: "Women's" },
]
const CLASS_YEARS = ['Fr', 'So', 'Jr', 'Sr']

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

// Feature 03. Always rendered, no gate. It's the connective feature: draft a
// first-contact email for ANY real NCAA/NAIA program (browse-all, standalone) or
// one of the athlete's Comparator results. The drafting call, fabrication
// safeguards, and honesty disclaimer are unchanged -- this component owns only
// layout, which session state it reads, and the browse/results split.
export default function OutreachAssistant({ comparables, clips = [] }) {
  const [introRef, introInView] = useInView()
  return (
    <section className="feature" id="outreach" aria-labelledby="outreach-heading">
      <div ref={introRef} className={`feature__intro ${introInView ? 'is-revealed' : ''}`}>
        <p className="eyebrow">Feature 03 — Outreach Assistant</p>
        <h2 id="outreach-heading" className="feature__title">
          Draft the first email
        </h2>
        <p className="feature__lede">
          <strong>Optional</strong>, and it’s the piece that connects the other two:
          pick any program — browse every real <strong>NCAA &amp; NAIA soccer program</strong>{' '}
          in the country, or one of your Comparator results — tell us a bit about
          yourself, optionally attach a Moment-Finder clip, and get a first-contact
          email draft you can edit. It writes from what you enter; it never looks up
          or invents a coach’s name, email, or dates.
        </p>
      </div>

      <div className="outreach">
        <OutreachForm comparables={comparables} clips={clips} />
      </div>
    </section>
  )
}

function OutreachForm({ comparables, clips }) {
  const results = comparables?.results || []
  const athlete = comparables?.athlete || null

  // De-duplicated programs from the Comparator results (may be empty).
  const programs = useMemo(() => {
    const seen = new Map()
    for (const r of results) {
      const key = `${r.school}|${r.division}`
      if (!seen.has(key)) seen.set(key, { school: r.school, division: r.division })
    }
    return [...seen.values()]
  }, [results])

  const [source, setSource] = useState('browse') // 'browse' | 'results'
  const [programKey, setProgramKey] = useState(
    programs[0] ? `${programs[0].school}|${programs[0].division}` : ''
  )

  // Manual athlete fields, used by browse-all. Results mode uses comparables.athlete.
  // Pre-filled from Comparator data when it exists, but always editable.
  const [bPosition, setBPosition] = useState('')
  const [bGender, setBGender] = useState('')
  const [bState, setBState] = useState('')
  const [bClass, setBClass] = useState('')

  const [gpa, setGpa] = useState('')
  const [why, setWhy] = useState('')
  const [clipUrl, setClipUrl] = useState('')

  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [draft, setDraft] = useState('')
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)

  const [allPrograms, setAllPrograms] = useState(null)
  const [browseStatus, setBrowseStatus] = useState('idle') // idle|loading|ready|error
  const [browseError, setBrowseError] = useState(null)
  const [browseState, setBrowseState] = useState('')
  const [browseKey, setBrowseKey] = useState('')

  // Pre-fill the manual fields from Comparator data when present; only fill blanks
  // so a user's own edits are never clobbered.
  useEffect(() => {
    if (!athlete) return
    setBPosition((v) => v || athlete.position || '')
    setBGender((v) => v || athlete.gender || '')
    setBState((v) => v || athlete.hometown_state || '')
    setBClass((v) => v || athlete.class_year || '')
  }, [athlete])

  // Keep the results-mode selection valid when a new search changes the set.
  useEffect(() => {
    if (!programs.length) return
    const keys = programs.map((p) => `${p.school}|${p.division}`)
    setProgramKey((k) => (keys.includes(k) ? k : keys[0]))
  }, [programs])

  // Lazy-load the national directory the first time browse is active. Browse is
  // the default tab, so this runs on mount.
  useEffect(() => {
    if (source !== 'browse' || allPrograms || browseStatus === 'loading') return
    setBrowseStatus('loading')
    setBrowseError(null)
    getPrograms()
      .then((res) => {
        setAllPrograms(res.programs)
        setBrowseStatus('ready')
      })
      .catch((err) => {
        setBrowseError(outreachMessage(err))
        setBrowseStatus('error')
      })
  }, [source, allPrograms, browseStatus])

  // Browse cascade: filter to the chosen squad, then state -> school.
  const genderPrograms = useMemo(
    () => (allPrograms || []).filter((p) => p.gender === bGender),
    [allPrograms, bGender]
  )
  const browseStates = useMemo(
    () => [...new Set(genderPrograms.map((p) => p.state).filter(Boolean))].sort(),
    [genderPrograms]
  )
  const stateSchools = useMemo(
    () =>
      genderPrograms
        .filter((p) => p.state === browseState)
        .sort((a, b) => a.school.localeCompare(b.school)),
    [genderPrograms, browseState]
  )
  const genderLabel = bGender === 'W' ? "women's" : bGender === 'M' ? "men's" : ''

  const resultProgram =
    programs.find((p) => `${p.school}|${p.division}` === programKey) || programs[0] || null
  const browseProgram =
    stateSchools.find((p) => `${p.school}|${p.division}` === browseKey) || null
  const program = source === 'browse' ? browseProgram : resultProgram

  const draftAthlete =
    source === 'browse'
      ? { position: bPosition, gender: bGender, hometown_state: bState, class_year: bClass || null }
      : athlete

  // The draft endpoint requires position + gender (enum-validated), so browse must
  // have both before drafting. State / class year / GPA / why / clip stay optional.
  const browseReady = Boolean(bPosition && bGender)
  const canDraft =
    Boolean(program) &&
    (source === 'results' ? Boolean(athlete) : browseReady) &&
    status !== 'loading'

  async function onDraft(e) {
    e.preventDefault()
    if (!program || !draftAthlete) return
    setStatus('loading')
    setError(null)
    setCopied(false)
    try {
      const res = await draftOutreach({
        position: draftAthlete.position,
        hometown_state: draftAthlete.hometown_state,
        gender: draftAthlete.gender,
        class_year: draftAthlete.class_year || undefined,
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

  const showResultsEmpty = source === 'results' && programs.length === 0

  return (
    <>
      <form className="outreach-form" onSubmit={onDraft}>
        <fieldset className="field">
          <legend className="field__label">Which program?</legend>
          <div className="segmented" role="group" aria-label="Choose a program source">
            <button
              type="button"
              className={`segmented__option ${source === 'browse' ? 'is-selected' : ''}`}
              aria-pressed={source === 'browse'}
              onClick={() => setSource('browse')}
            >
              Browse all programs
            </button>
            <button
              type="button"
              className={`segmented__option ${source === 'results' ? 'is-selected' : ''}`}
              aria-pressed={source === 'results'}
              onClick={() => setSource('results')}
            >
              From my results
            </button>
          </div>
        </fieldset>

        {showResultsEmpty ? (
          <div className="placeholder">
            <p className="placeholder__title">No Comparator results yet</p>
            <p className="placeholder__sub">
              Run a search in the Comparator above to pick from real players’ programs
              — or switch to <strong>Browse all programs</strong> to pick any program
              without a search.
            </p>
            <a className="btn-secondary outreach-empty__cta" href="#comparator">
              Go to the Comparator ↑
            </a>
          </div>
        ) : (
          <>
            {source === 'results' ? (
              <div className="field">
                <label className="field__label" htmlFor="outreach-program">
                  Program (from your Comparator results)
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
            ) : (
              <>
                <p className="outreach-hint">
                  Pick any program and tell us a bit about yourself. Position and squad
                  are needed to write the email; anything else you leave blank becomes a
                  spot you fill in later.
                </p>

                <div className="field-grid">
                  <div className="field">
                    <label className="field__label" htmlFor="b-gender">Squad</label>
                    <select
                      id="b-gender"
                      className="select"
                      value={bGender}
                      onChange={(e) => {
                        setBGender(e.target.value)
                        setBrowseState('')
                        setBrowseKey('')
                      }}
                    >
                      <option value="">Choose…</option>
                      {GENDERS.map((g) => (
                        <option key={g.value} value={g.value}>{g.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="b-position">Position</label>
                    <select
                      id="b-position"
                      className="select"
                      value={bPosition}
                      onChange={(e) => setBPosition(e.target.value)}
                    >
                      <option value="">Choose…</option>
                      {POSITIONS.map((p) => (
                        <option key={p.value} value={p.value}>{p.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="b-class">
                      Class year <span className="field__optional">(optional)</span>
                    </label>
                    <select
                      id="b-class"
                      className="select"
                      value={bClass}
                      onChange={(e) => setBClass(e.target.value)}
                    >
                      <option value="">Any</option>
                      {CLASS_YEARS.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label className="field__label" htmlFor="b-state">
                      Home state <span className="field__optional">(optional)</span>
                    </label>
                    <select
                      id="b-state"
                      className="select"
                      value={bState}
                      onChange={(e) => setBState(e.target.value)}
                    >
                      <option value="">Choose…</option>
                      {US_STATES.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {!bGender ? (
                  <p className="outreach-hint">Choose your squad above to browse its programs.</p>
                ) : browseStatus === 'loading' ? (
                  <p className="outreach-hint">Loading the national program list…</p>
                ) : browseStatus === 'error' ? (
                  <div className="notice notice--error" role="alert">
                    <span className="notice__tag">Couldn’t load programs</span>
                    <p>{browseError}</p>
                  </div>
                ) : (
                  <>
                    <p className="outreach-hint">
                      Browsing the{' '}
                      <strong>{genderPrograms.length.toLocaleString()}</strong> {genderLabel}{' '}
                      NCAA &amp; NAIA programs nationwide. Pick a state, then a school.
                    </p>
                    <div className="field">
                      <label className="field__label" htmlFor="b-browse-state">State</label>
                      <select
                        id="b-browse-state"
                        className="select"
                        value={browseState}
                        onChange={(e) => {
                          setBrowseState(e.target.value)
                          setBrowseKey('')
                        }}
                      >
                        <option value="">Choose a state…</option>
                        {browseStates.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </div>
                    {browseState && (
                      <div className="field">
                        <label className="field__label" htmlFor="b-browse-school">
                          Program{' '}
                          <span className="field__optional">
                            ({stateSchools.length} in {browseState})
                          </span>
                        </label>
                        <select
                          id="b-browse-school"
                          className="select"
                          value={browseKey}
                          onChange={(e) => setBrowseKey(e.target.value)}
                        >
                          <option value="">Choose a school…</option>
                          {stateSchools.map((p) => (
                            <option key={`${p.school}|${p.division}`} value={`${p.school}|${p.division}`}>
                              {p.school} ({p.division}
                              {p.conference ? `, ${p.conference}` : ''})
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </>
                )}
              </>
            )}

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
                Why this program?{' '}
                <span className="field__optional">(optional, your own words)</span>
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

            {clips.length > 0 && (
              <div className="field">
                <label className="field__label" htmlFor="outreach-clip-pick">
                  Attach a Moment-Finder clip{' '}
                  <span className="field__optional">(optional — from this session)</span>
                </label>
                <select
                  id="outreach-clip-pick"
                  className="select"
                  value={clips.some((c) => c.url === clipUrl) ? clipUrl : ''}
                  onChange={(e) => setClipUrl(e.target.value)}
                >
                  <option value="">— none / paste a link below —</option>
                  {clips.map((c) => (
                    <option key={c.url} value={c.url}>{c.label}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="field">
              <label className="field__label" htmlFor="outreach-clip">
                Highlight clip link{' '}
                <span className="field__optional">
                  (optional{clips.length > 0 ? ' — or paste your own' : ' — paste a Moment-Finder clip URL'})
                </span>
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

            <button type="submit" className="cta" disabled={!canDraft}>
              {status === 'loading' ? 'Drafting…' : 'Draft outreach email'}
            </button>
          </>
        )}
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
              This is a draft to edit, not verified contact information. Confirm the
              coach’s name and email yourself (most athletics staff directories list
              them), and check your sport’s current NCAA contact-period rules — a
              non-response is often about timing, not interest.
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
    </>
  )
}
