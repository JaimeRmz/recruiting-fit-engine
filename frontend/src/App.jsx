import { useEffect, useRef, useState } from 'react'
import Header from './components/Header.jsx'
import Comparator from './components/Comparator.jsx'
import MomentFinder from './components/MomentFinder.jsx'
import OutreachAssistant from './components/OutreachAssistant.jsx'
import photo1 from './photos/1.jpeg'
import photo2 from './photos/2.jpg'
import photo3 from './photos/3.jpg'
import photo4 from './photos/4.webp'

const HERO_PHOTOS = [photo1, photo2, photo3, photo4]

const STATS = [
  { number: '2,062', label: 'Real players' },
  { number: '43', label: 'Schools scraped' },
  { number: '2,244', label: 'Programs nationwide' },
]

// Shared "TechFootball Recruiting" red wordmark+monogram (red-only version --
// served from public/, not bundled, same as favicon.svg).
const TECHFOOTBALL_LOGO = '/techfootballrecruitinglogored.png'
const TECHFOOTBALL_URL = 'https://techfootball.vercel.app/'

export default function App() {
  const gridRef = useRef(null)

  // Session state shared with the Outreach Assistant (Feature 03). Lifted here so
  // that section can read results from BOTH features no matter which ran first:
  //   comparables -> { results, athlete } from the latest Comparator search
  //   clips       -> [{ url, label }] from the latest Moment-Finder run
  const [comparables, setComparables] = useState(null)
  const [clips, setClips] = useState([])

  // Subtle cursor parallax: the dot grid drifts a few px opposite the pointer.
  // Fully disabled (no listener) when the user prefers reduced motion.
  useEffect(() => {
    const grid = gridRef.current
    const hero = grid?.parentElement
    if (!grid || !hero) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const MAX = 10 // px of travel at the hero edges
    function onMove(e) {
      const r = hero.getBoundingClientRect()
      const dx = (e.clientX - (r.left + r.width / 2)) / r.width // -0.5..0.5
      const dy = (e.clientY - (r.top + r.height / 2)) / r.height
      grid.style.transform = `translate(${-dx * MAX}px, ${-dy * MAX}px)`
    }
    function reset() {
      grid.style.transform = 'translate(0px, 0px)'
    }
    hero.addEventListener('mousemove', onMove)
    hero.addEventListener('mouseleave', reset)
    return () => {
      hero.removeEventListener('mousemove', onMove)
      hero.removeEventListener('mouseleave', reset)
    }
  }, [])

  return (
    <>
      <Header />
      <section id="top" className="hero">
        <div ref={gridRef} className="hero__grid" aria-hidden="true" />
        <div className="hero__photos" aria-hidden="true">
          {HERO_PHOTOS.map((src, i) => (
            <img
              key={i}
              src={src}
              alt=""
              className="hero__photo"
              loading={i === 0 ? 'eager' : 'lazy'}
              decoding="async"
              style={{ animationDelay: `${i * 7.25}s` }}
            />
          ))}
        </div>
        <div className="hero__content">
          <h1 className="hero__title">
            The recruiting edge is mostly access. This narrows the gap.
          </h1>
          <p className="hero__thesis">
            Getting recruited runs on things money buys — club dues, showcase travel,
            an editor to cut your highlights. This is a demo of two tools that hand
            some of that back to the player: see <strong>real college players</strong> who
            share your position and hometown and the programs they play for, and
            surface the <strong>moments worth reviewing</strong> in your own footage
            without paying anyone to scrub it — and, if you want it, an assistant that
            turns that into a first-contact email you can edit and send.
          </p>
          <p className="hero__caveat">
            Two validated capabilities, plus one optional assistant built on top of
            them. The first two show you real data and real timestamps — they don’t
            predict your future or score your ability, and they’re candid about what
            they can’t do. The third turns that into a draft — it never invents a
            coach’s name, email, or date.
          </p>
        </div>
      </section>

      <section className="stats" aria-labelledby="stats-heading">
        <div className="stats__inner">
          <h2 id="stats-heading" className="stats__heading">
            Performance Metrics
          </h2>
          <div className="stats__grid">
            {STATS.map((s) => (
              <div className="stat" key={s.label}>
                <span className="stat__dot" aria-hidden="true" />
                <p className="stat__number mono">{s.number}</p>
                <p className="stat__label">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <main>
        <Comparator onResults={setComparables} />
        <MomentFinder onClips={setClips} />
        <OutreachAssistant comparables={comparables} clips={clips} />
      </main>

      <footer className="site-footer">
        <div className="site-footer__rule" aria-hidden="true" />
        <p className="mono">
          Recruiting Fit Engine — two tools I tested until I trusted them, plus a
          helper that turns the results into outreach. No accounts, no tracking,
          nothing stored.
        </p>
        <a
          className="site-footer__link mono"
          href="https://github.com/JaimeRmz/recruiting-fit-engine"
          target="_blank"
          rel="noopener noreferrer"
        >
          View source on GitHub ↗
        </a>
        <a
          className="site-footer__link site-footer__credit"
          href={TECHFOOTBALL_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          <img
            src={TECHFOOTBALL_LOGO}
            alt="TechFootball Recruiting"
            width="150"
            height="84"
            loading="lazy"
            className="site-footer__logo"
          />
        </a>
      </footer>
    </>
  )
}
