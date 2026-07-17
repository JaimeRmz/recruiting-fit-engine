import { useEffect, useRef, useState } from 'react'

// Reveal-once helper: returns [ref, inView]. Sets inView to true the first time
// the element scrolls into view, then stops observing (never re-animates on
// scroll-back). Purely presentational -- drives a CSS class, no data logic.
export function useInView({ threshold = 0.15, rootMargin = '0px 0px -10% 0px' } = {}) {
  const ref = useRef(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    // Without IntersectionObserver, show immediately rather than stay hidden.
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setInView(true)
          obs.disconnect()
        }
      },
      { threshold, rootMargin }
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [threshold, rootMargin])

  return [ref, inView]
}
