import { useEffect, useRef, useState } from 'react'
import Comparator from './components/Comparator.jsx'
import MomentFinder from './components/MomentFinder.jsx'
import OutreachAssistant from './components/OutreachAssistant.jsx'

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
      <header className="hero">
        <div ref={gridRef} className="hero__grid" aria-hidden="true" />
        <div className="hero__content">
          <p className="hero__kicker">Recruiting Fit Engine</p>
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
          <nav className="hero__nav" aria-label="Jump to a feature">
            <a href="#comparator" className="hero__link">
              Comparator
            </a>
            <a href="#moment-finder" className="hero__link">
              Moment-Finder
            </a>
            <a href="#outreach" className="hero__link">
              Outreach Assistant
            </a>
          </nav>
        </div>
      </header>

      <main className="page">
        <Comparator onResults={setComparables} />
        <div className="section-divider" role="separator" aria-hidden="true" />
        <MomentFinder onClips={setClips} />
        <div className="section-divider" role="separator" aria-hidden="true" />
        <OutreachAssistant comparables={comparables} clips={clips} />
      </main>

      <footer className="site-footer">
        <div className="site-footer__rule" aria-hidden="true" />
        <p className="mono">
          Recruiting Fit Engine — a demo of two validated capabilities, plus an
          optional assistant that turns them into outreach. No accounts, no tracking,
          no stored data.
        </p>
        <a
          className="site-footer__link mono"
          href="https://github.com/JaimeRmz/recruiting-fit-engine"
          target="_blank"
          rel="noopener noreferrer"
        >
          View source on GitHub ↗
        </a>
      </footer>
    </>
  )
}
