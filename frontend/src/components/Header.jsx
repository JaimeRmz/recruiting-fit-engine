import { useEffect, useState } from 'react'

const TECHFOOTBALL_LOGO = '/techfootballrecruitinglogored.png'

// Anchor-nav for now (each target is a plain in-page section id). Kept as a
// `to` field rather than inlining hrefs so swapping to react-router later is
// just: render <Link to={item.to}> instead of <a href={item.to}> below --
// the data and the section ids it points at don't change.
const NAV_ITEMS = [
  { to: '#comparator', label: 'Comparator' },
  { to: '#moment-finder', label: 'Moment-Finder' },
  { to: '#outreach', label: 'Outreach Assistant' },
]

// Persistent site header: logo + nav on desktop, logo + hamburger on mobile.
// Sticky (not fixed) so it never needs a manual height offset for the content
// below it -- html's scroll-padding-top (styles.css) handles the offset for
// anchor jumps instead.
// Matches TechFootball's own header-on-scroll trigger point.
const SCROLL_THRESHOLD = 50

export default function Header() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [isScrolled, setIsScrolled] = useState(false)

  // Escape closes the mobile menu; keeps it simple since focus-trapping a
  // full-screen nav with only three links is more machinery than it's worth.
  useEffect(() => {
    if (!menuOpen) return
    function onKey(e) {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])

  // Toggles a single class at the scroll threshold rather than recalculating
  // styles on every scroll event -- the transition itself is pure CSS.
  useEffect(() => {
    function onScroll() {
      setIsScrolled(window.scrollY > SCROLL_THRESHOLD)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className={`site-header ${isScrolled ? 'is-scrolled' : ''}`}>
      <div className="site-header__inner">
        <a href="#top" className="site-header__brand" aria-label="TechFootball Recruiting — back to top">
          <img
            src={TECHFOOTBALL_LOGO}
            alt="TechFootball Recruiting"
            width="150"
            height="84"
            loading="eager"
            className="site-header__logo"
          />
        </a>

        <nav className="site-header__nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <a key={item.to} href={item.to} className="site-header__link">
              {item.label}
            </a>
          ))}
        </nav>

        <button
          type="button"
          className="site-header__toggle"
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <span className="site-header__toggle-bar" aria-hidden="true" />
          <span className="site-header__toggle-bar" aria-hidden="true" />
          <span className="site-header__toggle-bar" aria-hidden="true" />
        </button>
      </div>

      <nav
        id="mobile-nav"
        className={`site-header__mobile-nav ${menuOpen ? 'is-open' : ''}`}
        aria-label="Mobile"
        aria-hidden={!menuOpen}
      >
        {NAV_ITEMS.map((item, i) => (
          <a
            key={item.to}
            href={item.to}
            className="site-header__mobile-link"
            style={{ transitionDelay: `${i * 100}ms` }}
            tabIndex={menuOpen ? 0 : -1}
            onClick={() => setMenuOpen(false)}
          >
            {item.label}
          </a>
        ))}
      </nav>
    </header>
  )
}
