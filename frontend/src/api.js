// Thin client for the deployed Recruiting-Fit-Engine API.
// Comparables is open; moments requires the X-API-Key shared secret.

const API_BASE =
  import.meta.env.VITE_API_BASE || 'https://recruiting-fit-engine-api.onrender.com'

const API_KEY = import.meta.env.VITE_API_KEY

// Absolute URL for a clip whose path the API returns relative (e.g. /clips/<id>/x.mp4).
export function clipUrl(path) {
  if (!path) return null
  return path.startsWith('http') ? path : `${API_BASE}${path}`
}

// Distinguishes error kinds so the UI can speak in its own voice per case.
export class ApiError extends Error {
  constructor(kind, message) {
    super(message)
    this.kind = kind // 'auth' | 'too_large' | 'unconfigured' | 'server' | 'network' | 'bad_request'
  }
}

async function detailOf(res) {
  try {
    const body = await res.json()
    return typeof body.detail === 'string' ? body.detail : null
  } catch {
    return null
  }
}

export async function getComparables({ position, hometown_state, gender, class_year }) {
  let res
  try {
    res = await fetch(`${API_BASE}/api/comparables`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        position,
        hometown_state,
        gender,
        ...(class_year ? { class_year } : {}),
      }),
    })
  } catch {
    throw new ApiError('network', 'Could not reach the server.')
  }
  if (!res.ok) {
    const detail = await detailOf(res)
    throw new ApiError('bad_request', detail || `Request failed (${res.status}).`)
  }
  return res.json()
}

// POST /api/outreach/draft -> { draft }
// Requires the X-API-Key secret (same as moments). NOTE: each call is a real,
// paid LLM request server-side -- the UI should not call this in a loop.
export async function draftOutreach(payload) {
  if (!API_KEY || API_KEY === 'your-api-key-here') {
    throw new ApiError(
      'auth',
      'No API key is configured. Set VITE_API_KEY in frontend/.env.local and restart the dev server.'
    )
  }

  let res
  try {
    res = await fetch(`${API_BASE}/api/outreach/draft`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new ApiError('network', 'Could not reach the drafting service.')
  }

  if (!res.ok) {
    const detail = await detailOf(res)
    if (res.status === 401) throw new ApiError('auth', detail)
    if (res.status === 503) throw new ApiError('unconfigured', detail)
    if (res.status === 400) throw new ApiError('bad_request', detail)
    throw new ApiError('server', detail || `Draft failed (${res.status}).`)
  }
  return res.json()
}

// GET /api/programs -> { count, programs: [{school, division, conference, state, gender}] }
// Public (no auth). The national browse-all directory for the Outreach Assistant.
export async function getPrograms() {
  let res
  try {
    res = await fetch(`${API_BASE}/api/programs`)
  } catch {
    throw new ApiError('network', 'Could not reach the program directory.')
  }
  if (!res.ok) {
    const detail = await detailOf(res)
    throw new ApiError('server', detail || `Program list failed (${res.status}).`)
  }
  return res.json()
}

// Moment analysis is a background job: submit the upload for a job_id, then poll
// the status endpoint until it is 'complete' or 'failed'.

// POST /api/moments/submit -> { job_id, status: 'processing' }
export async function submitMoments(file) {
  // Surface a missing key before spending an upload on a guaranteed 401.
  if (!API_KEY || API_KEY === 'your-api-key-here') {
    throw new ApiError(
      'auth',
      'No API key is configured. Set VITE_API_KEY in frontend/.env.local and restart the dev server.'
    )
  }

  const form = new FormData()
  form.append('file', file)

  let res
  try {
    res = await fetch(`${API_BASE}/api/moments/submit`, {
      method: 'POST',
      headers: { 'X-API-Key': API_KEY },
      body: form,
    })
  } catch {
    throw new ApiError('network', 'Could not reach the analysis service.')
  }

  if (!res.ok) {
    const detail = await detailOf(res)
    if (res.status === 401) throw new ApiError('auth', detail)
    if (res.status === 413) throw new ApiError('too_large', detail)
    if (res.status === 503) throw new ApiError('unconfigured', detail)
    throw new ApiError('server', detail || `Submit failed (${res.status}).`)
  }
  return res.json()
}

// GET /api/moments/status/{job_id} -> { status, ...candidates when complete }
export async function getMomentStatus(jobId) {
  let res
  try {
    res = await fetch(`${API_BASE}/api/moments/status/${jobId}`)
  } catch {
    throw new ApiError('network', 'Lost contact with the analysis service.')
  }
  if (!res.ok) {
    const detail = await detailOf(res)
    if (res.status === 404)
      throw new ApiError('server', detail || 'This analysis job expired or was not found.')
    throw new ApiError('server', detail || `Status check failed (${res.status}).`)
  }
  return res.json()
}
