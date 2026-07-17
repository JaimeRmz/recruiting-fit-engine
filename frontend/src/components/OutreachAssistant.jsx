import { useMemo, useState } from 'react'
import { draftOutreach } from '../api.js'
import { useInView } from '../hooks/useInView.js'

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

// Feature 03. Always rendered. It's the connective feature: it pulls a real
// program from the Comparator's session results and (optionally) a clip URL from
// Moment-Finder's session results, in whatever order those two were run. The
// drafting call, fabrication safeguards, and honesty disclaimer are unchanged --
// this component only owns layout + which session state it reads from.
export default function OutreachAssistant({ comparables, clips = [] }) {
  const [introRef, introInView] = useInView()
  const hasResults =
    comparables && comparables.results && comparables.results.length > 0

  return (
    <section className="feature" id="outreach" aria-labelledby="outreach-heading">
      <div ref={introRef} className={`feature__intro ${introInView ? 'is-revealed' : ''}`}>
        <p className="eyebrow">Feature 03 — Outreach Assistant</p>
        <h2 id="outreach-heading" className="feature__title">
          Draft the first email
        </h2>
        <p className="feature__lede">
          <strong>Optional</strong>, and it’s the piece that connects the other
          two: pick a real program from your Comparator results, optionally attach
          a Moment-Finder clip, and get a first-contact email draft you can edit.
          It writes from what you enter — it never looks up or invents a coach’s
          name, email, or dates.
        </p>
      </div>

      <div className="outreach">
        {hasResults ? (
          // Key on the program set so a NEW Comparator search re-initializes the
          // form (its selected program) instead of pointing at a stale option.
          <OutreachForm
            key={comparables.results.map((r) => `${r.school}|${r.division}`).join('~')}
            comparables={comparables}
            clips={clips}
          />
        ) : (
          <div className="placeholder">
            <p className="placeholder__title">No program picked yet</p>
            <p className="placeholder__sub">
              Run a search in the Comparator above to pull up real programs, then
              come back here to draft an outreach email for one of them.
            </p>
            <a className="btn-secondary outreach-empty__cta" href="#comparator">
              Go to the Comparator ↑
            </a>
          </div>
        )}
      </div>
    </section>
  )
}

function OutreachForm({ comparables, clips }) {
  const { results, athlete } = comparables

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
    <>
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
                <option key={c.url} value={c.url}>
                  {c.label}
                </option>
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
    </>
  )
}
