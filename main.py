"""
Recruiting-Fit-Engine API.

Wraps two validated, content-agnostic tools:

  * find_comparables()  -> real roster rows matching a player's profile.
  * moment_finder       -> CANDIDATE highlight timestamps in match footage.

Neither predicts, scores, or classifies. The comparables endpoint returns real
players, not a fit score. The moments endpoint surfaces timestamps for a human to
review; it does not know what happened at any of them and never claims to. That
framing is load-bearing and is repeated in the response bodies on purpose -- see
MOMENT_FINDER_NOTES.

Run:
    uvicorn main:app --reload
"""
import hmac
import os
import shutil
import tempfile
import time
import uuid

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
# 15-minute cap for the DEPLOYED environment (tightened from 30 locally): Render
# compute is unproven against the locally-validated ~1 min processing per ~8 min
# of footage, so cap the worst-case synchronous wait at ~2 minutes until measured.
MAX_DURATION_SEC = 15 * 60                  # 15 minutes
UPLOAD_CHUNK = 1024 * 1024                  # 1 MB streaming chunks
CLIP_TTL_SEC = 60 * 60                      # serve extracted clips for 1 hour

# moment_finder's module defaults are still the original pre=3/post=5; the
# validated tuning from real-footage testing is pre=4.5/post=5 at the 92nd
# percentile. Pin those here so the API's behavior is explicit and does not drift
# with the module, rather than relying on the library defaults.
MOTION_PERCENTILE = 92.0
CLIP_PRE_SEC = 4.5
CLIP_POST_SEC = 5.0

# Vite dev server (local) + deployed frontend. The Vercel entry is a PLACEHOLDER
# to be swapped for the real domain once the frontend ships.
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://recruiting-fit-engine.vercel.app",
]

# Shared-secret gate for the compute-heavy /api/moments endpoint. Read from the
# environment; never hardcode. /api/comparables and /api/health stay open.
API_SECRET_KEY = os.environ.get("API_SECRET_KEY")

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

app = FastAPI(
    title="Recruiting-Fit-Engine API",
    description="Comparables lookup + candidate highlight-moment finder. "
                "No prediction, scoring, or event classification anywhere.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


class MomentsResponse(BaseModel):
    """
    Candidate highlight moments for human review.

    SYNCHRONOUS endpoint: it blocks until analysis finishes. Processing runs at
    roughly 1 minute per 8 minutes of footage, so a 15-minute upload (the cap)
    takes on the order of 2 minutes. Set your client timeout accordingly. No
    background-job polling is provided by design -- the 15-minute upload cap keeps
    the wait short enough that it is not needed.
    """
    total_candidates: int
    video_duration_sec: float
    both_signals: int = Field(..., description="How many candidates were flagged "
                              "by motion AND scene_cut together.")
    candidates: list[MomentCandidate]
    notes: list[str] = Field(..., description="Known limitations. Surface these "
                             "to the user; do not present candidates as events.")


# --- helpers -----------------------------------------------------------------
def _sweep_expired_clips():
    """Delete served clip dirs older than the TTL so repeated testing can't fill
    the disk. Called opportunistically at the start of each analysis request."""
    now = time.time()
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


@app.post("/api/moments", response_model=MomentsResponse)
def moments(file: UploadFile = File(...), _auth: None = Depends(require_api_key)):
    """
    Find CANDIDATE highlight timestamps in an uploaded match video.

    Requires a valid X-API-Key header (shared secret). Uploads are scoped to a
    single half or segment: max 15 minutes / 500 MB. This is the product's
    intended usage, not a technical limit -- trim to the relevant segment before
    uploading. Synchronous; expect ~1 min of processing per ~8 min of footage.
    """
    _sweep_expired_clips()

    job_id = uuid.uuid4().hex[:12]
    src_path = os.path.join(UPLOAD_DIR, f"{job_id}.mp4")
    job_clips = os.path.join(CLIPS_DIR, job_id)

    # 1. stream to disk, enforcing the size cap mid-stream so we never buffer a
    #    huge upload fully into memory or fully onto disk before rejecting it.
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

    # 2. duration cap (before doing minutes of CV work on an over-long video)
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
                   f"{MAX_DURATION_SEC // 60} min. Uploads are scoped to one half "
                   "or segment -- upload a half or the relevant passage instead.")

    # 3. run the existing pipeline (imported, not reimplemented) with the
    #    validated tuning pinned above.
    try:
        cands = moment_finder.find_moments(
            src_path,
            outdir=job_clips,
            motion_percentile=MOTION_PERCENTILE,
            pre=CLIP_PRE_SEC,
            post=CLIP_POST_SEC,
            write_clips=True,
        )
    except Exception as e:
        _safe_remove(src_path)
        shutil.rmtree(job_clips, ignore_errors=True)
        raise HTTPException(status_code=500,
                            detail=f"Analysis failed: {type(e).__name__}: {e}")
    finally:
        # The source video is not needed once clips are extracted; delete it
        # immediately. Extracted clips remain under the TTL for playback.
        _safe_remove(src_path)

    out = []
    for i, c in enumerate(cands, 1):
        signal = "both" if len(c.sources) > 1 else c.sources[0]
        clip_url = None
        if c.clip_path:
            clip_url = f"/clips/{job_id}/{os.path.basename(c.clip_path)}"
        out.append(MomentCandidate(
            rank=i, timestamp_sec=round(c.time, 2), timestamp=_fmt_ts(c.time),
            signal=signal, motion_score=round(c.motion_score, 4),
            clip_url=clip_url,
        ))

    return MomentsResponse(
        total_candidates=len(out),
        video_duration_sec=round(duration, 1),
        both_signals=sum(1 for c in cands if len(c.sources) > 1),
        candidates=out,
        notes=MOMENT_FINDER_NOTES,
    )


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
