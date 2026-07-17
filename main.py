"""
Recruiting-Fit-Engine API.

Wraps two validated, content-agnostic tools:

  * find_comparables()  -> real roster rows matching a player's profile.
  * moment_finder       -> CANDIDATE highlight timestamps in match footage.

Neither predicts, scores, or classifies. The comparables endpoint returns real
players, not a fit score. The moments pipeline surfaces timestamps for a human to
review; it does not know what happened at any of them and never claims to. That
framing is load-bearing and is repeated in the response bodies on purpose -- see
MOMENT_FINDER_NOTES.

Moment analysis is asynchronous: POST /api/moments/submit accepts the upload and
returns a job_id immediately; GET /api/moments/status/{job_id} is polled until the
job is complete or failed.

Run:
    uvicorn main:app --reload
"""
import csv
import hmac
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import anthropic
import cv2
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import moment_finder
from compare_athletes import find_comparables

# --- config ------------------------------------------------------------------
VALID_POSITIONS = {"GK", "D", "M", "F"}
VALID_GENDERS = {"M", "W"}
VALID_CLASS_YEARS = {"Fr", "So", "Jr", "Sr"}

MAX_UPLOAD_BYTES = 500 * 1024 * 1024        # 500 MB
# 20-minute cap. Analysis now runs as a BACKGROUND job (see /api/moments/submit),
# so the request no longer blocks on CPU and a full half is in reach. At the
# measured Render Starter rate (~1 min processing per ~1.8 min of footage) 20 min
# of footage is ~11 min of background work; the client submits, gets a job_id back
# immediately, and polls /api/moments/status/{job_id}.
MAX_DURATION_SEC = 20 * 60                  # 20 minutes
UPLOAD_CHUNK = 1024 * 1024                  # 1 MB streaming chunks
CLIP_TTL_SEC = 60 * 60                      # serve extracted clips for 1 hour
JOB_TTL_SEC = 60 * 60                       # keep finished job results for 1 hour

# One background worker on purpose: uvicorn runs --workers 1 and each CV job peaks
# a few hundred MB, so serializing jobs keeps the container under its 512MB limit.
# A second submission uploads and gets a job_id immediately; only its processing
# queues behind the first. This is deliberately not a real task queue.
_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_JOBS = {}                                  # job_id -> {status, created_at, result|error}
_JOBS_LOCK = threading.Lock()

# moment_finder's module defaults are still the original pre=3/post=5; the
# validated tuning from real-footage testing is pre=4.5/post=5 at the 92nd
# percentile. Pin those here so the API's behavior is explicit and does not drift
# with the module, rather than relying on the library defaults.
MOTION_PERCENTILE = 92.0
CLIP_PRE_SEC = 4.5
CLIP_POST_SEC = 7.0

# Vite dev server (local) + deployed frontend. The Vercel entry is the stable
# production domain (per-deploy hash URLs are not covered).
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://recruiting-fit-engine.vercel.app",
]

# Shared-secret gate for the compute-heavy /api/moments endpoint. Read from the
# environment; never hardcode. /api/comparables and /api/health stay open.
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

# Outreach Assistant (/api/outreach/draft) config.
#
# COST NOTE: unlike everything else in this app, this endpoint makes a paid
# Anthropic API call on every request -- it costs real money per draft. It stays
# behind the same X-API-Key gate as /api/moments, and it must NOT be called in a
# loop during testing. Model + token budget are deliberately small: a first-
# contact recruiting email is short prose, so Haiku with a ~500-token cap is
# plenty (and cheap). Key is read live from the env, same pattern as the others.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
# Sonnet 5, not Haiku: testing showed Haiku unreliably dropped specific provided
# facts (the athlete's own reasons for interest) and genericized the email, even
# with a foregrounded prompt. A first-contact email is short and low-volume, so
# the stronger model's cost is negligible and the fidelity is worth it.
OUTREACH_MODEL = "claude-sonnet-5"
OUTREACH_MAX_TOKENS = 500

# The one instruction that makes this feature honest: it drafts PROSE from given
# facts, it does not retrieve facts. Everything the athlete didn't supply becomes
# a bracketed placeholder they must verify -- never an invented name/email/date.
OUTREACH_SYSTEM_PROMPT = """You draft a short, first-contact recruiting email from a high-school soccer player to a college coach.

ABSOLUTE RULES -- never break these:
- Use ONLY facts explicitly provided in the user's message. Do not invent, guess, or infer anything not given.
- NEVER invent a coach's name, an email address, a phone number, a specific date, an NCAA contact-period window, roster spots, program history, or any school-specific fact that was not provided.
- For anything the email needs but was not provided, insert a clearly bracketed placeholder for the athlete to fill in, e.g. "[Coach's name -- check the athletics staff directory]" or "[verify your sport's current NCAA contact period]". When a normal email would name the coach, use the placeholder rather than omitting it.
- Do NOT imply the athlete has already contacted, spoken with, met, or heard from anyone. This is a FIRST contact.
- Do not fabricate statistics, achievements, or reasons for interest. If "why interested" is not provided, use a neutral bracketed placeholder like "[in your own words: what specifically draws you to this program]" instead of making something up.

REQUIRED STRUCTURE -- every draft, no exceptions:
- If you include a subject line, put it on the first line.
- The email body MUST open with exactly this greeting line, verbatim: "Dear [Coach's name -- check the athletics staff directory]," -- use it in EVERY draft, always, because a coach's name is never provided. Never start with anything else and never omit the greeting.
- Then two or three short paragraphs, then a brief sign-off with bracketed placeholders for the athlete's name and contact info.

USE EVERY PROVIDED FACT -- never drop one:
- Incorporate every fact given in the user's message into the body: position, class year, and home state always; GPA whenever it is provided (state the GPA explicitly, e.g. "I carry a 3.8 GPA").
- If "why interested" is provided, it is the MOST IMPORTANT content of the email: build the message around it and make it the most prominent part, faithful to the athlete's own words and reasons. NEVER drop it or replace it with generic language.
- If "why interested" is NOT provided, use the bracketed placeholder for it (never invent a reason).
- If a highlight clip is provided, reference/link it near the end.

STYLE (researched best practice):
- Lead with genuine, specific interest in THIS program and why the athlete is a fit -- not a stats dump.
- Concise and professional; warm but not overfamiliar; no hype and no exclamation-point spam. It must read well in a coach's inbox.
- Weave the facts in naturally, not as a bulleted resume.
- End with a clear, low-pressure ask (interest in the program and willingness to share more film or info).

WORKED EXAMPLE (illustrative only -- a DIFFERENT athlete and sport; the real athlete's sport, position, and facts always come from the user message below). It shows how to weave every specific reason into the body instead of genericizing it away:

Given these facts:
  CENTRAL THEME: "I'm drawn to your marine biology program and the fast, aggressive serve-receive system your team plays, and I want to stay on the West Coast."
  - Athlete's position: outside hitter
  - Squad: women's volleyball
  - Athlete's home state: Oregon
  - Athlete's class year: junior
  - Target program: Coastal State University (D2)
  - Athlete's GPA: 3.7

A strong email body:

Dear [Coach's name -- check the athletics staff directory],

I'm a junior outside hitter from Oregon, and I'm reaching out because two things about Coastal State stand out to me: your marine biology program and the fast, aggressive serve-receive system your team plays. Staying on the West Coast matters to me as well, and Coastal State fits that. I carry a 3.7 GPA and take academics as seriously as I take my game.

I'd love to learn whether my game is a fit for what you're building. I'd be glad to send match film or answer any questions you have.

Thank you for your time and for considering my interest.

Best regards,
[Your name]
[Your phone number]
[Your email address]

Notice how the marine biology program, the serve-receive style, the West-Coast reason, the 3.7 GPA, the position, the state, and the class year ALL appear in the body -- none dropped, none replaced with generic "balancing academics and athletics" filler. Do exactly this with whatever specifics the real athlete provides.

Now write ONLY the email itself, for the athlete described in the next message. You may include a subject line as the first line. No preamble, no commentary, no markdown formatting."""

# Known limitations, echoed in every /api/moments response. These are the ceiling
# of what the tool claims; the frontend should surface them, not bury them.
MOMENT_FINDER_NOTES = [
    "These are CANDIDATE timestamps for human review, not detected events. The "
    "tool does not recognize goals, shots, fouls, or any specific play.",
    "Ranking is by motion magnitude, which is NOT the same as importance -- a "
    "dead-ball restart can outrank a real attacking sequence.",
    "Expect false positives on dead-ball restarts, pre-game warmup, and hard "
    "camera zooms.",
]

# Temp roots. Uploads live in a dir that is NEVER served and are deleted right
# after processing. Clips live in a served dir and are swept on a TTL.
WORK_ROOT = os.path.join(tempfile.gettempdir(), "rfe_api")
UPLOAD_DIR = os.path.join(WORK_ROOT, "uploads")
CLIPS_DIR = os.path.join(WORK_ROOT, "clips")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

# Program-level national directory for the Outreach Assistant's "browse all"
# selector: school/division/conference/state/gender, ~2,200 real soccer programs.
# This is SEPARATE from the Comparator's roster file (program_roster_master.csv) and
# holds no player data. Loaded once at startup and served read-only via /api/programs.
# See build_all_programs.py for how it's sourced (Wikipedia D1/D2, NCSA D3/NAIA).
PROGRAMS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "all_programs.csv")


def _load_programs():
    fields = ["school", "division", "conference", "state", "gender"]
    try:
        with open(PROGRAMS_CSV, newline="", encoding="utf-8") as fh:
            rows = [{k: (r.get(k) or "").strip() for k in fields}
                    for r in csv.DictReader(fh)]
    except FileNotFoundError:
        return []
    rows.sort(key=lambda r: r["school"].lower())   # alphabetical by school
    return rows


_PROGRAMS = _load_programs()

app = FastAPI(
    title="Recruiting-Fit-Engine API",
    description="Comparables lookup + candidate highlight-moment finder. "
                "No prediction, scoring, or event classification anywhere.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # Also allow any localhost / 127.0.0.1 port. The Vite dev server falls back off
    # 5173 to 5174+ whenever 5173 is busy, which silently changes the browser's
    # Origin and is the usual cause of a "No Access-Control-Allow-Origin" preflight
    # failure in local dev. Production origins stay explicit in CORS_ORIGINS above.
    # Private LAN ranges (10/8, 192.168/16, 172.16-31/12) are allowed too, so the
    # dev server reached from a phone on the same wifi (e.g. http://192.168.x.x:5173)
    # isn't blocked. Those origins only exist on a local network, and /api/moments
    # stays gated by X-API-Key.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|10(\.\d{1,3}){3}|192\.168(\.\d{1,3}){2}|172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2}):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # wildcard already reflects X-API-Key on the preflight
)
# Extracted clips are served here so the frontend can play them directly.
# URL shape: /clips/<job_id>/<clip_filename>.mp4
app.mount("/clips", StaticFiles(directory=CLIPS_DIR), name="clips")


# --- schemas -----------------------------------------------------------------
class ComparablesRequest(BaseModel):
    position: str = Field(..., description="One of GK, D, M, F (exact).",
                          examples=["GK"])
    hometown_state: str = Field(..., description="US state; full name or "
                                "abbreviation, e.g. 'Texas' or 'TX'.",
                                examples=["Texas"])
    gender: str = Field(..., description="M or W (exact).", examples=["W"])
    class_year: str | None = Field(
        None, description="Optional Fr/So/Jr/Sr. Soft preference only -- "
        "same-year players sort first, but it never filters matches out.",
        examples=["Sr"])


class ComparablePlayer(BaseModel):
    school: str
    division: str
    gender: str
    class_year: str | None
    hometown: str
    match_type: str = Field(..., description="'state' for an exact state match, "
                            "'region' when the state was too thin and results "
                            "fell back to the surrounding region.")


class ComparablesResponse(BaseModel):
    count: int
    match_type: str | None = Field(
        None, description="Overall match basis: 'state', 'region', or null if "
        "no matches. On 'region', results are NOT from the requested state.")
    results: list[ComparablePlayer]


class Program(BaseModel):
    school: str
    division: str = Field(..., description="D1, D2, D3, or NAIA.")
    conference: str = Field("", description="Blank for D3/NAIA (source has no "
                            "conference; left blank rather than guessed).")
    state: str
    gender: str = Field(..., description="M or W.")


class ProgramsResponse(BaseModel):
    count: int
    programs: list[Program]


class OutreachRequest(BaseModel):
    # Already-known athlete data (from the Comparator inputs) + the chosen real
    # program (from a Comparator result row). Optional fields are exactly that --
    # anything left blank becomes a bracketed placeholder in the draft, never an
    # invented fact.
    position: str = Field(..., description="GK, D, M, F (exact).", examples=["M"])
    hometown_state: str = Field(..., examples=["Texas"])
    gender: str = Field(..., description="M or W (exact).", examples=["W"])
    class_year: str | None = Field(None, examples=["Jr"])
    school: str = Field(..., description="The chosen real program.",
                        examples=["Trinity University"])
    division: str = Field(..., examples=["D3"])
    gpa: str | None = Field(None, description="Optional; free text so '3.8' or "
                            "'3.8 unweighted' both work.", examples=["3.8"])
    why_interested: str | None = Field(
        None, description="Optional; the athlete's own words on why this program.")
    clip_url: str | None = Field(
        None, description="Optional highlight-clip URL to reference in the email.")


class OutreachResponse(BaseModel):
    draft: str = Field(..., description="Editable email DRAFT. Not verified contact "
                       "info; placeholders must be filled in by the athlete.")


class MomentCandidate(BaseModel):
    rank: int = Field(..., description="Suggested REVIEW ORDER, not a ranking of "
                      "importance or likelihood.")
    timestamp_sec: float
    timestamp: str = Field(..., description="mm:ss.ss into the uploaded video.")
    signal: str = Field(..., description="'motion', 'scene_cut', or 'both'. "
                        "Which detector(s) fired -- not a confidence.")
    motion_score: float = Field(..., description="Residual on-field motion, for "
                                "threshold tuning only. NOT a probability or "
                                "confidence, and not a claim anything happened.")
    clip_url: str | None = Field(None, description="Relative URL to the 9.5s "
                                 "extracted clip (4.5s before to 5s after).")


class MomentJobSubmit(BaseModel):
    """Returned immediately from /api/moments/submit once the upload is accepted."""
    job_id: str = Field(..., description="Opaque, unguessable id. Poll "
                        "GET /api/moments/status/{job_id}.")
    status: str = Field("processing", description="Always 'processing' here.")


class MomentJobStatus(BaseModel):
    """
    Polled result of a moment-analysis job.

    While running: {"status": "processing"}. On success the candidate fields are
    populated (same shape the old synchronous endpoint returned, honesty notes
    included). On failure: {"status": "failed", "error": ...}. At the measured
    Render rate (~1 min per ~1.8 min of footage) a 20-minute upload is ~11 minutes
    of work, so poll on the order of every few seconds.
    """
    status: str = Field(..., description="'processing', 'complete', or 'failed'.")
    total_candidates: int | None = None
    video_duration_sec: float | None = None
    both_signals: int | None = Field(
        None, description="How many candidates were flagged by motion AND scene_cut.")
    candidates: list[MomentCandidate] | None = None
    notes: list[str] | None = Field(
        None, description="Known limitations. Surface these to the user; do not "
        "present candidates as events.")
    error: str | None = Field(None, description="Set only when status is 'failed'.")


# --- job store ---------------------------------------------------------------
def _set_job(job_id, **fields):
    with _JOBS_LOCK:
        _JOBS.setdefault(job_id, {}).update(fields)


def _get_job(job_id):
    with _JOBS_LOCK:
        rec = _JOBS.get(job_id)
        return dict(rec) if rec else None


# --- helpers -----------------------------------------------------------------
def _sweep_expired():
    """Drop finished job records and served clip dirs older than the TTL so
    repeated use can't fill memory or disk. Called at the start of each submit."""
    now = time.time()
    with _JOBS_LOCK:
        for jid in [j for j, r in _JOBS.items()
                    if now - r.get("created_at", now) > JOB_TTL_SEC]:
            _JOBS.pop(jid, None)
    for name in os.listdir(CLIPS_DIR):
        path = os.path.join(CLIPS_DIR, name)
        try:
            if os.path.isdir(path) and now - os.path.getmtime(path) > CLIP_TTL_SEC:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _probe_duration(path):
    """Seconds via OpenCV frame-count / fps. Returns None if unreadable."""
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not fps or fps <= 0 or not frames or frames <= 0:
            return None
        return frames / fps
    finally:
        cap.release()


def _fmt_ts(sec):
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    """Gate for /api/moments. Fails CLOSED: if the server has no API_SECRET_KEY
    configured, the endpoint is unavailable rather than open. Compared in constant
    time so a wrong key leaks no timing signal."""
    # Read live from the env (not just the import-time constant) so the key can be
    # rotated by restarting the service without a code change.
    expected = os.environ.get("API_SECRET_KEY") or API_SECRET_KEY
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Server auth is not configured (API_SECRET_KEY is unset on "
                   "the server). /api/moments is unavailable until it is set.")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401,
                            detail="Missing or invalid X-API-Key header.")


# --- endpoints ---------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/comparables", response_model=ComparablesResponse)
def comparables(req: ComparablesRequest):
    """Real roster players matching a position, home state, and gender. Returns
    real rows only -- no fit score, no prediction, no ranking by quality."""
    pos = req.position.strip().upper()
    gen = req.gender.strip().upper()
    if pos not in VALID_POSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"position must be one of {sorted(VALID_POSITIONS)}; "
                   f"got {req.position!r}.")
    if gen not in VALID_GENDERS:
        raise HTTPException(
            status_code=400,
            detail=f"gender must be one of {sorted(VALID_GENDERS)}; "
                   f"got {req.gender!r}.")

    rows = find_comparables(pos, req.hometown_state, gen,
                            class_year=req.class_year)
    return ComparablesResponse(
        count=len(rows),
        match_type=rows[0]["match_type"] if rows else None,
        results=rows,
    )


@app.get("/api/programs", response_model=ProgramsResponse)
def programs():
    """Public program-level national soccer directory for the Outreach Assistant's
    browse-all selector: school, division, conference, state, gender. Sorted
    alphabetically by school. No auth -- this is public reference data, and it is
    SEPARATE from the Comparator's roster (that keeps using its own file)."""
    return ProgramsResponse(count=len(_PROGRAMS), programs=_PROGRAMS)


def _build_outreach_user_message(req: "OutreachRequest") -> str:
    """Render the provided facts into an explicit, labeled block, FOREGROUNDING the
    athlete's reason for interest as the email's central theme so the model builds
    around its specific content instead of genericizing it. Fields the athlete did
    NOT provide are simply absent here -- the system prompt turns each gap into a
    bracketed placeholder, never an invention."""
    pos = {"GK": "goalkeeper", "D": "defender", "M": "midfielder",
           "F": "forward"}.get(req.position.strip().upper(), req.position)
    squad = {"M": "men's", "W": "women's"}.get(req.gender.strip().upper(),
                                               req.gender)
    why = (req.why_interested or "").strip()

    lines = ["Draft a first-contact recruiting email using ONLY the facts below.",
             ""]

    # Foreground the reason FIRST and loudly when provided -- listing it as one
    # bullet among many led Haiku to weight it equally and flatten it.
    if why:
        lines += [
            "CENTRAL THEME of the email -- this is the athlete's own reason for "
            "interest, and it MUST be the most prominent content of the message. "
            "Build the email around the SPECIFIC points below and incorporate them "
            "faithfully (paraphrasing is fine; verbatim quoting is not required). "
            'Do NOT flatten them into generic "balancing academics and athletics" '
            "language that could describe any athlete -- the specific reasons must "
            "be recognizable in the final email:",
            f"    {why}",
            "",
        ]

    lines += [
        "Facts to include in the body:",
        f"- Athlete's position: {pos}",
        f"- Squad: {squad} soccer",
        f"- Athlete's home state: {req.hometown_state}",
    ]
    if req.class_year:
        lines.append(f"- Athlete's class year: {req.class_year}")
    lines.append(f"- Target program: {req.school} ({req.division})")
    if req.gpa and req.gpa.strip():
        lines.append(f"- Athlete's GPA: {req.gpa.strip()} (state this explicitly)")
    if not why:
        lines.append("- Why interested: NOT PROVIDED -- use a bracketed "
                     "placeholder, do not invent a reason.")

    if req.clip_url and req.clip_url.strip():
        lines += [
            "",
            "Highlight clip to reference near the end. Insert this URL as PLAIN "
            "TEXT, exactly as written -- do NOT wrap it in markdown link syntax, "
            "brackets, or parentheses:",
            f"    {req.clip_url.strip()}",
        ]

    lines += [
        "",
        "The coach's name and email address were NOT provided -- use bracketed "
        "placeholders for both. Do not invent any other program-specific fact.",
    ]
    return "\n".join(lines)


@app.post("/api/outreach/draft", response_model=OutreachResponse)
def outreach_draft(req: OutreachRequest, _auth: None = Depends(require_api_key)):
    """
    Draft a first-contact recruiting email from the athlete's known facts and a
    real target program. PROSE GENERATION, not fact retrieval: it never invents a
    coach name, email, date, or any school-specific fact -- missing details come
    back as bracketed placeholders the athlete must verify.

    Requires X-API-Key. COST: each call hits the paid Anthropic API. Do not loop.
    """
    pos = req.position.strip().upper()
    gen = req.gender.strip().upper()
    if pos not in VALID_POSITIONS:
        raise HTTPException(400, f"position must be one of {sorted(VALID_POSITIONS)}.")
    if gen not in VALID_GENDERS:
        raise HTTPException(400, f"gender must be one of {sorted(VALID_GENDERS)}.")
    if not req.school.strip() or not req.division.strip():
        raise HTTPException(400, "school and division are required.")

    key = os.environ.get("ANTHROPIC_API_KEY") or ANTHROPIC_API_KEY
    if not key:
        raise HTTPException(
            status_code=503,
            detail="Outreach drafting is unavailable (ANTHROPIC_API_KEY is not "
                   "set on the server).")

    try:
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=OUTREACH_MODEL,
            max_tokens=OUTREACH_MAX_TOKENS,
            system=OUTREACH_SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": _build_outreach_user_message(req)}],
        )
    except anthropic.APIStatusError as e:
        # Upstream returned an HTTP error (rate limit, auth, overloaded, ...).
        raise HTTPException(
            status_code=502,
            detail=f"The drafting service returned an error ({e.status_code}). "
                   "Please try again in a moment.")
    except anthropic.APIError:
        # Connection/timeout/other SDK-level failure.
        raise HTTPException(
            status_code=502,
            detail="The drafting service is temporarily unreachable. Please try "
                   "again in a moment.")
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not generate a draft right now. Please try again.")

    text = "".join(b.text for b in msg.content
                   if getattr(b, "type", None) == "text").strip()
    if not text:
        raise HTTPException(status_code=502,
                            detail="The draft came back empty. Please try again.")
    return OutreachResponse(draft=text)


def _build_candidates(cands, job_id):
    """moment_finder Candidate objects -> serializable candidate dicts."""
    out = []
    for i, c in enumerate(cands, 1):
        signal = "both" if len(c.sources) > 1 else c.sources[0]
        clip_url = (f"/clips/{job_id}/{os.path.basename(c.clip_path)}"
                    if c.clip_path else None)
        out.append({
            "rank": i, "timestamp_sec": round(c.time, 2),
            "timestamp": _fmt_ts(c.time), "signal": signal,
            "motion_score": round(c.motion_score, 4), "clip_url": clip_url,
        })
    return out


def _run_moment_job(job_id, src_path, job_clips, duration):
    """Background worker: runs the (memory-bounded) pipeline and records the result
    on the job. Never raises -- failures are stored as status='failed'."""
    try:
        cands = moment_finder.find_moments(
            src_path, outdir=job_clips, motion_percentile=MOTION_PERCENTILE,
            pre=CLIP_PRE_SEC, post=CLIP_POST_SEC, write_clips=True)
        candidates = _build_candidates(cands, job_id)
        _set_job(job_id, status="complete", result={
            "total_candidates": len(candidates),
            "video_duration_sec": round(duration, 1),
            "both_signals": sum(1 for c in cands if len(c.sources) > 1),
            "candidates": candidates,
            "notes": MOMENT_FINDER_NOTES,
        })
    except Exception as e:
        shutil.rmtree(job_clips, ignore_errors=True)
        _set_job(job_id, status="failed",
                 error=f"Analysis failed: {type(e).__name__}: {e}")
    finally:
        # Source video is only needed during analysis; clips remain under the TTL.
        _safe_remove(src_path)


@app.post("/api/moments/submit", response_model=MomentJobSubmit)
def submit_moments(file: UploadFile = File(...),
                   _auth: None = Depends(require_api_key)):
    """
    Accept a match video for analysis and return a job_id immediately.

    Requires a valid X-API-Key header. Max 20 minutes / 500 MB per upload. The
    upload and validation happen here synchronously; the CV work runs in the
    background. Poll GET /api/moments/status/{job_id} for the result -- at the
    measured Render rate a 20-minute upload is ~11 minutes of processing.
    """
    _sweep_expired()

    job_id = uuid.uuid4().hex                 # 32 hex chars, unguessable
    src_path = os.path.join(UPLOAD_DIR, f"{job_id}.mp4")
    job_clips = os.path.join(CLIPS_DIR, job_id)

    # 1. stream to disk, enforcing the size cap mid-stream so we never buffer a
    #    huge upload fully into memory or onto disk before rejecting it.
    size = 0
    try:
        with open(src_path, "wb") as out:
            while True:
                chunk = file.file.read(UPLOAD_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    os.remove(src_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds the {MAX_UPLOAD_BYTES // (1024*1024)} MB "
                               "limit. Uploads are scoped to one half or segment -- "
                               "trim to the relevant portion and try again.")
                out.write(chunk)
    finally:
        file.file.close()

    if size == 0:
        _safe_remove(src_path)
        raise HTTPException(status_code=400, detail="Empty upload.")

    # 2. duration cap (before queuing minutes of CV work on an over-long video)
    duration = _probe_duration(src_path)
    if duration is None:
        _safe_remove(src_path)
        raise HTTPException(
            status_code=400,
            detail="Could not read the video. Expected a decodable H.264 .mp4 "
                   "(or similar). If this is variable-frame-rate phone video, "
                   "transcode to constant frame rate first.")
    if duration > MAX_DURATION_SEC:
        _safe_remove(src_path)
        raise HTTPException(
            status_code=413,
            detail=f"Video is {duration/60:.1f} min; the limit is "
                   f"{MAX_DURATION_SEC // 60} min. Upload a half or the relevant "
                   "passage instead.")

    # 3. register the job and hand the heavy work to the background worker.
    _set_job(job_id, status="processing", created_at=time.time())
    _EXECUTOR.submit(_run_moment_job, job_id, src_path, job_clips, duration)
    return MomentJobSubmit(job_id=job_id, status="processing")


@app.get("/api/moments/status/{job_id}", response_model=MomentJobStatus)
def moment_status(job_id: str):
    """
    Poll a submitted job. No auth -- job_ids are unguessable UUIDs.

    'processing' while running; 'complete' with the candidate list (same shape as
    the old synchronous response, honesty notes included) when done; 'failed' with
    a message otherwise. Unknown/expired ids return 404 (jobs are kept 1 hour).
    """
    rec = _get_job(job_id)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown or expired job_id. Jobs are kept for one hour after "
                   "submission.")
    status = rec.get("status")
    if status == "complete":
        return MomentJobStatus(status="complete", **rec["result"])
    if status == "failed":
        return MomentJobStatus(status="failed", error=rec.get("error"))
    return MomentJobStatus(status="processing")


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
