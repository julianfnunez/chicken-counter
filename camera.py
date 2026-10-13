"""RTSP frame capture with FFmpeg."""
import subprocess

def capture(folder, url):
    if not url.startswith("rtsp://") or "replace-me" in url:
        raise RuntimeError("Set a valid RTSP URL for this coop in .env")
    command = ["ffmpeg","-hide_banner","-loglevel","error","-nostdin",
        "-rtsp_transport","tcp","-i",url,"-an","-vf","fps=1/10,scale=1280:-2",
        "-frames:v","4","-q:v","2",str(folder / "frame-%02d.jpg")]
    try:
        completed = subprocess.run(command,capture_output=True,timeout=75)
        if completed.returncode:
            raise RuntimeError("RTSP capture failed; check URL, camera and network")
    except subprocess.TimeoutExpired:
        raise RuntimeError("RTSP capture timed out") from None
    paths = sorted(folder.glob("frame-*.jpg"))
    if len(paths) != 4 or any(p.stat().st_size < 1000 for p in paths):
        raise RuntimeError("Camera did not provide four image files")
    return paths

