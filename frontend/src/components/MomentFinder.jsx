import { useEffect, useRef, useState } from 'react'
import { submitMoments, getMomentStatus, clipUrl } from '../api.js'
import { useInView } from '../hooks/useInView.js'
import JerseyBadge from './JerseyBadge.jsx'

const POLL_INTERVAL_MS = 4000

const SIGNAL_LABELS = {
  motion: 'Motion',
  scene_cut: 'Scene cut',
  both: 'Motion + cut',
}

// Maps an ApiError.kind to a message in the interface's voice.
function messageFor(err) {
  switch (err.kind) {
    case 'auth':
      return (
        err.message ||
        'The API key is missing or invalid. Check VITE_API_KEY in frontend/.env.local.'
      )
    case 'too_large':
      return (
        err.message ||
        'That clip is over the limit. Trim it to 20 minutes / 500MB — the segment you want reviewed — and try again.'
      )
    case 'unconfigured':
      return 'The analysis service is temporarily unavailable (server key not set). Try again shortly.'
    case 'network':
      return 'Could not reach the analysis service. Check your connection and try again.'
    default:
      return err.message || 'Analysis failed on the server. Try a different clip.'
  }
}

// onClips lifts completed clip URLs up to App so the Outreach Assistant section
// can offer them as attachments, regardless of which feature was run first.
export default function MomentFinder({ onClips = () => {} }) {
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | done | error
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  const [introRef, introInView] = useInView()

  // Polling control. runId invalidates a stale poll loop when the user resubmits
  // or the component unmounts, so we never keep hitting the endpoint after done.
  const runIdRef = useRef(0)
  const timerRef = useRef(null)

  useEffect(() => () => {
    runIdRef.current += 1
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [])

  function schedulePoll(jobId, myRun) {
    timerRef.current = setTimeout(async () => {
      if (runIdRef.current !== myRun) return // superseded — stop polling
      try {
        const res = await getMomentStatus(jobId)
        if (runIdRef.current !== myRun) return
        if (res.status === 'complete') {
          setData(res)
          setStatus('done')
          // Surface this run's clips to the Outreach Assistant (absolute URLs).
          onClips(
            (res.candidates || [])
              .filter((c) => c.clip_url)
              .map((c) => ({ url: clipUrl(c.clip_url), label: `#${c.rank} · ${c.timestamp}` }))
          )
        } else if (res.status === 'failed') {
          setError(res.error || 'Analysis failed on the server. Try a different clip.')
          setStatus('error')
        } else {
          schedulePoll(jobId, myRun) // still processing — poll again
        }
      } catch (err) {
        if (runIdRef.current !== myRun) return
        setError(messageFor(err))
        setStatus('error')
      }
    }, POLL_INTERVAL_MS)
  }

  async function onSubmit(e) {
    e.preventDefault()
    if (!file) return
    const myRun = (runIdRef.current += 1) // cancel any in-flight poll loop
    if (timerRef.current) clearTimeout(timerRef.current)
    setStatus('loading')
    setError(null)
    setData(null)
    try {
      const { job_id } = await submitMoments(file)
      if (runIdRef.current !== myRun) return
      schedulePoll(job_id, myRun)
    } catch (err) {
      if (runIdRef.current !== myRun) return
      setError(messageFor(err))
      setStatus('error')
    }
  }

  return (
    <section className="feature" id="moment-finder" aria-labelledby="moments-heading">
      <div ref={introRef} className={`feature__intro ${introInView ? 'is-revealed' : ''}`}>
        <p className="eyebrow">Feature 02 — Moment-Finder</p>
        <h2 id="moments-heading" className="feature__title">
          Find the moments worth reviewing
        </h2>
        <p className="feature__lede">
          Upload raw match footage. The pipeline flags candidate timestamps — spikes
          of on-field motion and hard scene cuts — so you can jump straight to them
          instead of scrubbing the whole match.
        </p>
      </div>

      <form className="moments-form" onSubmit={onSubmit}>
        <div className="constraint" role="note">
          <span className="constraint__icon" aria-hidden="true">↑</span>
          <p>
            <strong>Upload a clip up to 20 minutes and 500MB.</strong> Trim to the
            segment you want reviewed — a half, a period, or the passage you care
            about.
          </p>
        </div>

        <label className={`dropzone ${file ? 'has-file' : ''}`}>
          <input
            ref={inputRef}
            type="file"
            accept="video/mp4,video/*"
            className="dropzone__input"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <span className="dropzone__label">
            {file ? (
              <>
                <span className="mono dropzone__name">{file.name}</span>
                <span className="dropzone__hint">
                  {(file.size / (1024 * 1024)).toFixed(1)} MB — click to choose a different file
                </span>
              </>
            ) : (
              <>
                <span className="dropzone__cta">Choose a video file</span>
                <span className="dropzone__hint">MP4 or similar, up to 20 min / 500MB</span>
              </>
            )}
          </span>
        </label>

        <button type="submit" className="cta" disabled={!file || status === 'loading'}>
          {status === 'loading' ? 'Analyzing…' : 'Find candidate moments'}
        </button>
      </form>

      <div className="moments-results" aria-live="polite">
        {status === 'idle' && (
          <div className="placeholder">
            <p className="placeholder__title">No footage analyzed yet</p>
            <p className="placeholder__sub">
              Upload a short clip above to surface candidate moments.
            </p>
          </div>
        )}

        {status === 'loading' && (
          <div className="analyzing">
            <div className="analyzing__bar" aria-hidden="true">
              <span />
            </div>
            <p className="analyzing__title">Analyzing your footage</p>
            <p className="analyzing__sub">
              This can take up to ~11 minutes for a full-length upload — the
              pipeline reads every frame and extracts a clip for each candidate.
              Feel free to leave this tab open in the background; results appear
              here automatically when it finishes.
            </p>
          </div>
        )}

        {status === 'error' && (
          <div className="notice notice--error" role="alert">
            <span className="notice__tag">Couldn’t analyze that</span>
            <p>{error}</p>
          </div>
        )}

        {status === 'done' && data && <MomentResults data={data} />}
      </div>
    </section>
  )
}

function MomentResults({ data }) {
  return (
    <div>
      {/* CRITICAL honesty panel — always visible, never collapsed. */}
      <aside className="honesty" aria-labelledby="honesty-heading">
        <h3 id="honesty-heading" className="honesty__heading">
          Read this before you trust the list
        </h3>
        <ul className="honesty__list">
          {data.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      </aside>

      <div className="moments-summary">
        <p className="results-count">
          <span className="mono">{data.total_candidates}</span> candidate{' '}
          {data.total_candidates === 1 ? 'moment' : 'moments'} in{' '}
          <span className="mono">{(data.video_duration_sec / 60).toFixed(1)}</span> min
          {data.both_signals > 0 && (
            <>
              {' '}· <span className="mono">{data.both_signals}</span> flagged by both
              signals
            </>
          )}
        </p>
      </div>

      {data.total_candidates === 0 ? (
        <div className="placeholder">
          <p className="placeholder__title">No candidates crossed the threshold.</p>
          <p className="placeholder__sub">
            That can happen with calm passages or very steady footage. Try a segment
            with more end-to-end play.
          </p>
        </div>
      ) : (
        <ol className="moment-list">
          {data.candidates.map((c) => (
            <li className="moment-card" key={c.rank}>
              <div className="moment-card__head">
                <span className="moment-card__rank mono">#{c.rank}</span>
                <span className="moment-card__time mono">{c.timestamp}</span>
                <span className={`signal signal--${c.signal}`}>
                  {SIGNAL_LABELS[c.signal] || c.signal}
                </span>
              </div>
              {c.clip_url ? (
                <video
                  className="moment-card__video"
                  controls
                  preload="metadata"
                  src={clipUrl(c.clip_url)}
                >
                  Your browser can’t play this clip.
                </video>
              ) : (
                <p className="moment-card__noclip mono">clip unavailable</p>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
