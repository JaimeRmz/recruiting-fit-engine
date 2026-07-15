"""
Build-time smoke check for the two native dependencies most likely to break
SILENTLY at runtime in a Linux container -- OpenCV and the ffmpeg binary.

Run this in the Render build command AFTER pip install. It exits non-zero on any
problem so the DEPLOY fails loudly, instead of the first /api/moments request
500-ing in production.

    python check_deps.py
"""
import subprocess
import sys


def fail(msg):
    print(f"\n[check_deps] FAIL: {msg}\n", file=sys.stderr)
    sys.exit(1)


def check_opencv():
    # The classic Linux failure: `scenedetect` hard-depends on the NON-headless
    # `opencv-python`, whose cv2 links libGL.so.1, which is absent from Render's
    # slim Python image -> `ImportError: libGL.so.1`. The build must have replaced
    # it with opencv-python-headless. Importing cv2 here proves that worked.
    try:
        import cv2
    except Exception as e:
        fail(f"`import cv2` failed ({type(e).__name__}: {e}). On Linux this is "
             "almost always the non-headless opencv-python pulling libGL. Ensure "
             "the build uninstalls opencv-python and installs "
             "opencv-python-headless.")
    # Exercise a real codepath (not just import) to be sure the .so is functional.
    try:
        import numpy as np
        cv2.cvtColor(np.zeros((4, 4, 3), np.uint8), cv2.COLOR_BGR2GRAY)
    except Exception as e:
        fail(f"cv2 imported but a basic call failed ({type(e).__name__}: {e}).")
    print(f"[check_deps] OK  opencv cv2 {cv2.__version__} imports and runs")


def check_ffmpeg():
    # imageio-ffmpeg ships a platform-specific static binary per wheel. On Linux
    # x86_64 the manylinux wheel bundles a Linux ffmpeg; confirm it is present AND
    # actually executes here, rather than discovering that at request time.
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        fail(f"could not locate the imageio-ffmpeg binary ({type(e).__name__}: {e}).")
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True,
                             timeout=30)
    except Exception as e:
        fail(f"the ffmpeg binary at {exe} did not execute ({type(e).__name__}: {e}). "
             "The bundled binary may be missing the +x bit or be the wrong arch.")
    if out.returncode != 0 or "ffmpeg version" not in out.stdout.lower():
        fail(f"ffmpeg ran but returned an unexpected result (code {out.returncode}).")
    print(f"[check_deps] OK  ffmpeg binary runs: {exe}")
    print(f"                 {out.stdout.splitlines()[0]}")


if __name__ == "__main__":
    check_opencv()
    check_ffmpeg()
    print("[check_deps] all native deps verified.")
