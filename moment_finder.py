"""
Moment-Finder: surface CANDIDATE highlight timestamps in raw soccer footage.

WHAT THIS DOES
    Flags moments in a match video that a human editor should LOOK AT, using two
    content-agnostic signals: hard scene cuts (replays, angle changes) and
    sustained bursts of on-field motion (sprints, scrambles, celebrations).

WHAT THIS DOES NOT DO
    It does not recognize events. It has no concept of a goal, a foul, a save or
    a shot, and it never claims one. A candidate is "something moved a lot here"
    or "the video cut here" -- nothing more. High motion is just as likely to be a
    goalmouth scramble as a throw-in near a panning camera. The output is a review
    queue that cuts editing time; it does not replace editing judgment, and a
    candidate carries no confidence that anything notable happened.

    The ranking is a suggested REVIEW ORDER, not a likelihood. Nothing here is a
    probability and nothing should be presented to a user as one.

USAGE
    python moment_finder.py match.mp4 --outdir clips/
    python moment_finder.py match.mp4 --motion-percentile 95 --content-threshold 30

Every threshold is a parameter -- see CLI flags -- because sensible values depend
entirely on the footage (broadcast vs. sideline tripod vs. phone) and are meant to
be tuned against real video.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# VIDEO ASSUMPTIONS (what to feed this)
#
#   Container/codec : anything OpenCV + ffmpeg can decode. H.264 .mp4 is the
#                     expected case; .mov/.mkv/.avi generally work too.
#   Resolution      : any. Frames are downscaled to MOTION_WIDTH px wide before
#                     motion analysis, so 4K costs decode time but not analysis
#                     time. No minimum resolution is enforced, but below ~480p
#                     players get small enough that residual motion is noisy.
#   Frame rate      : read from the file. Variable-frame-rate video (common from
#                     phones) will produce drifting timestamps -- transcode VFR to
#                     constant frame rate first if timings look off.
#   Content         : one continuous match recording. Broadcast footage with
#                     existing replays/cuts is fine and is exactly what the scene
#                     detector is for. Tripod/fixed-camera footage is also fine:
#                     the camera-motion compensation simply becomes a no-op.
#   Audio           : ignored entirely. Crowd noise is probably the single
#                     strongest highlight cue available and this pipeline does not
#                     use it. That is a known gap, not an oversight.
# ---------------------------------------------------------------------------

MOTION_WIDTH = 320          # analysis width in px; motion is scale-invariant enough
DIFF_PIXEL_THRESH = 25      # per-pixel intensity delta counted as "moved" (0-255)
# Cap the width of the video actually fed to analysis. Peak memory otherwise scales
# with the UPLOAD's resolution: a 512MB container holds the Python process AND the
# ffmpeg subprocess together, and full-res frame decode + PySceneDetect + libx264
# clip encoding at 4K blows past that. 640px is well above the 320px the motion
# stage needs and keeps scene-cut detail, while collapsing the footprint to a fixed
# ceiling no matter what a user uploads.
PREPROCESS_MAX_WIDTH = 640


def find_ffmpeg():
    """System ffmpeg if present, else the pip-installed static binary."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _safe_unlink(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _video_width(video_path):
    """Frame width in px via OpenCV metadata (0 if unreadable). Cheap; no decode."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if cap.isOpened() else 0
    finally:
        cap.release()


def downscale_for_analysis(video_path, ffmpeg, max_width=PREPROCESS_MAX_WIDTH):
    """
    Return a video no wider than `max_width`, transcoding down only if needed.

    This is the memory safety net: every downstream stage (frame decode, scene
    detection, per-clip re-encoding) then runs at a bounded resolution, so a 4K
    upload and a 480p upload land at roughly the same footprint. ffmpeg does the
    downscale in a streaming pass, so the transcode itself stays light too.

    Only ever downscales -- a sub-`max_width` input is returned untouched (it is
    already cheap, and upscaling would waste work). Returns (path_to_use, is_temp);
    when is_temp is True the caller owns the temp file and must delete it.
    """
    if not ffmpeg:
        return video_path, False
    w = _video_width(video_path)
    if not w or w <= max_width:
        return video_path, False

    fd, out = tempfile.mkstemp(prefix="mf_scaled_", suffix=".mp4")
    os.close(fd)
    # -threads 2 on BOTH the decoder (before -i) and encoder (after) is the key
    # memory bound here: multi-threaded 4K H.264 decode otherwise holds one large
    # reference frame per thread, and an unbounded auto-thread count on a many-core
    # host balloons that to gigabytes. Two threads keeps decode buffers small while
    # still transcoding faster than real time. ultrafast trims encoder lookahead too.
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-threads", "2", "-i", str(video_path),
           # scale=W:-2 preserves aspect ratio and forces an even height (libx264).
           "-vf", f"scale={max_width}:-2",
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
           "-threads", "2", "-c:a", "aac", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
        # Fall back to the original rather than crash, but say so loudly -- on a
        # huge input this reintroduces the OOM risk this step exists to remove.
        print(f"  WARNING: downscale failed ({w}px input), analyzing original: "
              f"{r.stderr.strip()[:160]}")
        _safe_unlink(out)
        return video_path, False
    return out, True


@dataclass
class Candidate:
    time: float
    sources: list = field(default_factory=list)   # {"motion", "scene_cut"}
    motion_score: float = 0.0                     # residual motion, NOT a confidence
    clip_path: str = None


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------
def motion_series(video_path, sample_stride=3, progress=True):
    """
    Per-sample on-field motion intensity, with camera panning removed.

    METHOD: frame differencing with global-motion compensation, chosen over dense
    optical flow (Farneback) for one practical reason and one honest one.

      Practical: a 90-minute match is ~160k frames. Dense flow is roughly an order
      of magnitude slower per frame and would push a full match into hours. Frame
      differencing on downscaled greyscale runs faster than real time, which is
      what makes threshold tuning against real footage actually iterable.

      Honest: naive frame differencing is nearly useless on soccer, because the
      broadcast camera pans almost continuously and a pan lights up every pixel in
      the frame. So before differencing, the dominant frame-to-frame translation
      (i.e. the camera move) is estimated with phase correlation and warped out.
      What remains is motion RELATIVE to the camera -- players running, bodies
      colliding, a ball crossing the box -- which is the thing we actually want.

    This compensation is translation-only. Camera zooms and rotations are not
    modelled and will still register as motion; on a hard zoom expect a false
    positive. Returns (times, scores, meta).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open {video_path!r}. "
                           "Check the path and that the codec is decodable.")

    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not fps or fps <= 0 or np.isnan(fps):
        cap.release()
        raise RuntimeError("Could not read a valid frame rate. If this is "
                           "variable-frame-rate video, transcode to CFR first.")

    scale = MOTION_WIDTH / width if width > MOTION_WIDTH else 1.0
    dsize = (int(width * scale), int(height * scale))
    hann = cv2.createHanningWindow(dsize, cv2.CV_32F)

    times, scores = [], []
    prev = None
    idx = 0
    while True:
        ok = cap.grab()                      # grab() skips decode on unused frames
        if not ok:
            break
        if idx % sample_stride == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            small = cv2.cvtColor(cv2.resize(frame, dsize), cv2.COLOR_BGR2GRAY)
            small = cv2.GaussianBlur(small, (5, 5), 0)

            if prev is not None:
                # 1. estimate the camera's translation between the two samples
                dx, dy = cv2.phaseCorrelate(prev.astype(np.float32),
                                            small.astype(np.float32), hann)[0]
                # 2. undo it, so the pitch lines up and only players have moved
                M = np.float32([[1, 0, dx], [0, 1, dy]])
                warped = cv2.warpAffine(prev, M, dsize,
                                        borderMode=cv2.BORDER_REPLICATE)
                # 3. what is left over is motion relative to the camera
                diff = cv2.absdiff(warped, small)
                scores.append(float((diff > DIFF_PIXEL_THRESH).mean()))
                times.append(idx / fps)

            prev = small
            if progress and n_frames and idx % (sample_stride * 500) == 0:
                pct = 100 * idx / n_frames
                print(f"\r  motion analysis {pct:5.1f}%", end="", flush=True)
        idx += 1

    cap.release()
    if progress:
        print("\r  motion analysis 100.0%")

    meta = {"fps": fps, "frames": idx, "width": width, "height": height,
            "duration": idx / fps}
    return np.array(times), np.array(scores), meta


def motion_bursts(times, scores, fps, sample_stride, percentile=92.0,
                  abs_threshold=None, smooth_sec=1.0, min_burst_sec=1.0):
    """
    Sustained runs of high motion, not single-frame spikes.

    Scores are smoothed over `smooth_sec` before thresholding, so a one-frame
    flash (compression artifact, a bird, a lens flare) cannot produce a candidate;
    motion has to persist for at least `min_burst_sec` to count.

    The threshold is a PERCENTILE of this video's own motion distribution by
    default, because absolute residual-motion values are not comparable across
    resolutions, encoders or camera setups -- a fixed constant that works on
    broadcast footage will fire on everything in a shaky sideline recording.
    Pass `abs_threshold` to override with a fixed value once you have tuned one.
    """
    if len(scores) == 0:
        return []

    eff_fps = fps / sample_stride                      # samples per second
    win = max(1, int(round(smooth_sec * eff_fps)))
    kernel = np.ones(win) / win
    smooth = np.convolve(scores, kernel, mode="same")

    thresh = abs_threshold if abs_threshold is not None \
        else float(np.percentile(smooth, percentile))

    above = smooth > thresh
    min_len = max(1, int(round(min_burst_sec * eff_fps)))

    bursts, start = [], None
    for i, hot in enumerate(above):
        if hot and start is None:
            start = i
        elif not hot and start is not None:
            if i - start >= min_len:
                seg = smooth[start:i]
                peak = start + int(np.argmax(seg))
                bursts.append((float(times[peak]), float(smooth[peak])))
            start = None
    if start is not None and len(above) - start >= min_len:
        seg = smooth[start:]
        peak = start + int(np.argmax(seg))
        bursts.append((float(times[peak]), float(smooth[peak])))

    return bursts


# ---------------------------------------------------------------------------
# Scene cuts
# ---------------------------------------------------------------------------
def scene_cuts(video_path, content_threshold=27.0, min_scene_sec=1.0):
    """
    Hard cuts via PySceneDetect ContentDetector: replays, angle changes, graphics.

    On a continuous single-camera recording this will legitimately find almost
    nothing -- that is correct behaviour, not a failure. It earns its keep on
    broadcast footage, where a director cutting to a replay is itself a strong
    hint that something worth seeing just happened.
    """
    from scenedetect import ContentDetector, detect

    scenes = detect(str(video_path),
                    ContentDetector(threshold=content_threshold,
                                    min_scene_len=max(1, int(min_scene_sec * 15))))
    # scene[0] is the start of each scene; the first is t=0, which is not a cut.
    return [s[0].seconds for s in scenes[1:]]


# ---------------------------------------------------------------------------
# Combine
# ---------------------------------------------------------------------------
def merge_candidates(bursts, cuts, merge_window=2.0):
    """
    Fold the two signals into one deduplicated, review-ordered list.

    Anything landing within `merge_window` seconds of an existing candidate is
    merged into it rather than added -- a replay cut fires right after the motion
    burst that caused it, and those are one moment, not two.

    ORDERING is a review heuristic and NOT a score: candidates confirmed by both
    signals sort first (two independent things noticed the same instant), then by
    residual motion. `motion_score` is exposed for tuning, not for display to an
    end user, and it means nothing in absolute terms.
    """
    raw = ([Candidate(t, ["motion"], s) for t, s in bursts]
           + [Candidate(t, ["scene_cut"], 0.0) for t in cuts])
    raw.sort(key=lambda c: c.time)

    merged = []
    for c in raw:
        if merged and abs(c.time - merged[-1].time) <= merge_window:
            prev = merged[-1]
            for s in c.sources:
                if s not in prev.sources:
                    prev.sources.append(s)
            prev.motion_score = max(prev.motion_score, c.motion_score)
        else:
            merged.append(c)

    merged.sort(key=lambda c: (-len(c.sources), -c.motion_score))
    return merged


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------
def extract_clip(ffmpeg, video_path, t, outdir, idx, pre=3.0, post=5.0,
                 duration=None):
    start = max(0.0, t - pre)
    end = t + post
    if duration:
        end = min(end, duration)
    length = end - start
    if length <= 0:
        return None

    out = os.path.join(outdir, f"cand_{idx:03d}_t{int(t // 60):02d}m{int(t % 60):02d}s.mp4")
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-ss", f"{start:.3f}", "-i", str(video_path), "-t", f"{length:.3f}",
           # Re-encode rather than -c copy: stream-copy can only cut on keyframes,
           # which on match footage can be seconds away from the moment we want.
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ffmpeg failed on candidate {idx}: {r.stderr.strip()[:120]}")
        return None
    return out


# ---------------------------------------------------------------------------
def find_moments(video_path, outdir="clips", content_threshold=27.0,
                 motion_percentile=92.0, motion_abs_threshold=None,
                 smooth_sec=1.0, min_burst_sec=1.0, merge_window=2.0,
                 pre=3.0, post=5.0, sample_stride=3, max_candidates=None,
                 write_clips=True, preprocess=True,
                 preprocess_max_width=PREPROCESS_MAX_WIDTH):
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    print(f"analyzing {video_path}")
    ffmpeg = find_ffmpeg()

    # Memory safety net: run the whole pipeline against a resolution-capped copy so
    # peak memory never scales with the upload. motion_series, scene_cuts, AND clip
    # extraction all read `work_path`, so none of them ever touch a full 4K frame.
    work_path, is_temp = (
        downscale_for_analysis(video_path, ffmpeg, preprocess_max_width)
        if preprocess else (video_path, False))
    if is_temp:
        print(f"  pre-scaled to <= {preprocess_max_width}px wide for analysis "
              "(bounds peak memory)")

    try:
        times, scores, meta = motion_series(work_path, sample_stride)
        print(f"  {meta['width']}x{meta['height']} @ {meta['fps']:.2f} fps, "
              f"{meta['duration'] / 60:.1f} min, {meta['frames']} frames "
              f"({len(scores)} sampled)")

        bursts = motion_bursts(times, scores, meta["fps"], sample_stride,
                               percentile=motion_percentile,
                               abs_threshold=motion_abs_threshold,
                               smooth_sec=smooth_sec, min_burst_sec=min_burst_sec)
        print(f"  motion bursts : {len(bursts)}")

        print("  scene detection...")
        cuts = scene_cuts(work_path, content_threshold)
        print(f"  scene cuts    : {len(cuts)}")

        cands = merge_candidates(bursts, cuts, merge_window)
        if max_candidates:
            cands = cands[:max_candidates]

        if write_clips:
            if not ffmpeg:
                print("\n  ffmpeg not found -- skipping clip extraction.")
                print("  install it, or: pip install imageio-ffmpeg")
            else:
                os.makedirs(outdir, exist_ok=True)
                print(f"  extracting {len(cands)} clips -> {outdir}/")
                for i, c in enumerate(cands, 1):
                    c.clip_path = extract_clip(ffmpeg, work_path, c.time, outdir, i,
                                               pre, post, meta["duration"])

        summarize(cands, meta)
        return cands
    finally:
        if is_temp:
            _safe_unlink(work_path)


def summarize(cands, meta):
    print("\n" + "=" * 68)
    print(f"{len(cands)} CANDIDATE moments "
          f"(for human review -- no event classification, no confidence)")
    print("=" * 68)
    if not cands:
        print("none found. loosen --motion-percentile (e.g. 85) or "
              "--content-threshold (e.g. 22).")
        return
    print(f"  {'#':>3s} {'timestamp':>10s} {'signals':<18s} {'motion':>7s}  clip")
    for i, c in enumerate(cands, 1):
        m, s = divmod(c.time, 60)
        ts = f"{int(m):02d}:{s:05.2f}"
        src = "+".join(c.sources)
        clip = os.path.basename(c.clip_path) if c.clip_path else "-"
        print(f"  {i:3d} {ts:>10s} {src:<18s} {c.motion_score:7.4f}  {clip}")
    both = sum(1 for c in cands if len(c.sources) > 1)
    print(f"\n  {both} confirmed by BOTH signals (reviewed first); "
          f"{len(cands) - both} by one.")
    print("  'motion' is residual motion for threshold tuning -- not a "
          "probability, not a\n  confidence, and not a claim that anything "
          "happened. Review order only.")


def main():
    p = argparse.ArgumentParser(
        description="Find CANDIDATE highlight timestamps in match footage. "
                    "Surfaces moments to review; does not classify events.")
    p.add_argument("video")
    p.add_argument("--outdir", default="clips")
    p.add_argument("--content-threshold", type=float, default=27.0,
                   help="scene-cut sensitivity; LOWER = more cuts (default 27)")
    p.add_argument("--motion-percentile", type=float, default=92.0,
                   help="motion threshold as a percentile of this video's own "
                        "motion; LOWER = more candidates (default 92)")
    p.add_argument("--motion-abs-threshold", type=float, default=None,
                   help="fixed motion threshold, overrides --motion-percentile")
    p.add_argument("--smooth-sec", type=float, default=1.0,
                   help="motion smoothing window (default 1.0s)")
    p.add_argument("--min-burst-sec", type=float, default=1.0,
                   help="motion must persist this long to count (default 1.0s)")
    p.add_argument("--merge-window", type=float, default=2.0,
                   help="dedupe candidates within this many seconds (default 2.0)")
    p.add_argument("--pre", type=float, default=3.0, help="clip seconds before")
    p.add_argument("--post", type=float, default=5.0, help="clip seconds after")
    p.add_argument("--sample-stride", type=int, default=3,
                   help="analyze every Nth frame (default 3; raise to go faster)")
    p.add_argument("--max-candidates", type=int, default=None)
    p.add_argument("--no-clips", action="store_true",
                   help="analyze only, write no clips (fast threshold tuning)")
    a = p.parse_args()

    find_moments(a.video, a.outdir, a.content_threshold, a.motion_percentile,
                 a.motion_abs_threshold, a.smooth_sec, a.min_burst_sec,
                 a.merge_window, a.pre, a.post, a.sample_stride,
                 a.max_candidates, write_clips=not a.no_clips)


if __name__ == "__main__":
    sys.exit(main())
