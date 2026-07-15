// The signature element: a position (GK/D/M/F) rendered as a jersey number patch.
// Used everywhere a position appears -- filter controls and result rows -- so the
// same visual language reads consistently across both features.

const POSITION_LABELS = {
  GK: 'Goalkeeper',
  D: 'Defender',
  M: 'Midfielder',
  F: 'Forward',
}

export default function JerseyBadge({ position, size = 'md', active = false }) {
  const label = POSITION_LABELS[position] || position
  return (
    <span
      className={`jersey-badge jersey-badge--${size} ${active ? 'is-active' : ''}`}
      role="img"
      aria-label={label}
      title={label}
    >
      <span className="jersey-badge__text">{position}</span>
    </span>
  )
}
