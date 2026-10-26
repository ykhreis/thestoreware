import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI


def _json_from_model(text):
    text = (text or "").strip()
    fenced = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    return json.loads(text)


def _image_data_url(path):
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _average_hash(path):
    from PIL import Image
    with Image.open(path) as image:
        image = image.convert("L").resize((16, 16))
        pixels = list(image.getdata())
    avg = sum(pixels) / len(pixels)
    return tuple(1 if p >= avg else 0 for p in pixels)


def _hash_distance(a, b):
    return sum(x != y for x, y in zip(a, b))


def _remove_near_duplicates(paths, threshold=8):
    kept, previous = [], None
    for path in paths:
        current = _average_hash(path)
        if previous is None or _hash_distance(previous, current) > threshold:
            kept.append(path)
            previous = current
    return kept


def _resolve_video_stream(youtube_url):
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(youtube_url, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("YouTube metadata/stream information was not returned.")

    formats = info.get("formats") or []
    usable = []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        url = fmt.get("url")
        vcodec = fmt.get("vcodec")
        protocol = str(fmt.get("protocol") or "")
        height = int(fmt.get("height") or 0)
        if not url or not vcodec or vcodec == "none":
            continue
        # Prefer ordinary HTTP(S) media URLs so FFmpeg can seek with range requests.
        if protocol not in {"https", "http"}:
            continue
        if height and height > 720:
            continue
        usable.append(fmt)

    if not usable:
        # Broader fallback: any video-bearing format with a URL.
        for fmt in formats:
            if not isinstance(fmt, dict):
                continue
            if fmt.get("url") and fmt.get("vcodec") not in {None, "none"}:
                usable.append(fmt)

    if not usable:
        raise RuntimeError("No usable YouTube video stream was found.")

    # For question screenshots, 720p is preferred when available. Prefer direct
    # HTTP(S), then the highest resolution up to 720p.
    usable.sort(
        key=lambda f: (
            str(f.get("protocol") or "") in {"https", "http"},
            min(int(f.get("height") or 0), 720),
            float(f.get("tbr") or 0),
        ),
        reverse=True,
    )
    selected = usable[0]

    return {
        "url": selected["url"],
        "headers": selected.get("http_headers") or info.get("http_headers") or {},
        "format_id": str(selected.get("format_id") or ""),
        "height": int(selected.get("height") or 0),
        "title": str(info.get("title") or ""),
    }


def _extract_frames_from_stream(
    stream,
    frames_dir,
    start_seconds,
    end_seconds,
    interval_seconds=10,
    progress_callback=None,
    stop_callback=None,
):
    import shutil
    import imageio_ffmpeg

    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    interval = max(5, int(interval_seconds))
    start_seconds = float(start_seconds)
    end_seconds = float(end_seconds)

    timestamps = []
    ts = start_seconds
    while ts < end_seconds:
        timestamps.append(ts)
        ts += interval

    total = len(timestamps)
    created = []

    headers = stream.get("headers") or {}
    user_agent = headers.get("User-Agent") or headers.get("user-agent")
    referer = headers.get("Referer") or headers.get("referer")

    for index, timestamp in enumerate(timestamps, start=1):
        if stop_callback and stop_callback():
            return created

        output_path = frames_dir / f"frame_{index:05d}.jpg"

        command = [ffmpeg, "-hide_banner", "-loglevel", "error"]
        if user_agent:
            command += ["-user_agent", str(user_agent)]
        if referer:
            command += ["-referer", str(referer)]

        # Independent seek for ONE frame. We deliberately do not decode the
        # entire 5-minute interval. Each timestamp is a separate fast request.
        command += [
            "-ss", f"{timestamp:.3f}",
            "-i", stream["url"],
            "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-2",
            "-q:v", "3",
            "-an",
            "-y",
            str(output_path),
        ]

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                created.append(output_path)
        except subprocess.TimeoutExpired:
            # A single bad/slow timestamp must never freeze the whole part.
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass

        if progress_callback:
            # Keep compatibility with the existing callback shape while adding
            # frame counters/stage information for the Django job UI.
            progress_callback({
                "status": "sampling_frames",
                "frame_current": index,
                "frame_total": total,
                "frames_created": len(created),
                "timestamp_seconds": timestamp,
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "download_percent": round((index / total) * 100, 1) if total else 100.0,
                "speed_bps": 0.0,
                "eta_seconds": None,
            })

    return created



def _analyze_batch(frame_paths, transcript_text=""):
    client = OpenAI()
    model = os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini").strip()

    content = [{
        "type": "input_text",
        "text": (
            "Analyze these screenshots from an exam-preparation/training video. "
            "Return ONLY valid JSON. Detect only frames that visibly contain a complete "
            "or substantially complete multiple-choice/practice question. Extract visible "
            "wording without inventing missing text. JSON schema: "
            '{"questions":[{"frame_index":1,"question_number":"","question_text":"",'
            '"option_a":"","option_b":"","option_c":"","option_d":"","option_e":"",'
            '"visible_correct_answer":"","visible_explanation":"","confidence":0.0}]}. '
            "Omit non-question frames. Keep correct answer blank unless visibly indicated. "
            f"Supporting transcript context:\n{(transcript_text or '')[:10000]}"
        ),
    }]
    for path in frame_paths:
        content.append({
            "type": "input_image",
            "image_url": _image_data_url(path),
            "detail": "high",
        })

    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
    )
    parsed = _json_from_model(response.output_text)
    return parsed.get("questions", []) if isinstance(parsed, dict) else []


def _question_key(item):
    text = str(item.get("question_text") or "").lower()
    return re.sub(r"\W+", " ", text).strip()[:220]


def scan_youtube_part(
    youtube_url,
    start_seconds,
    end_seconds,
    transcript_text="",
    interval_seconds=8,
    progress_callback=None,
    stop_callback=None,
    download_callback=None,
):
    def progress(percent, stage, frames_done=0, frames_total=0, questions=0):
        if progress_callback:
            progress_callback(percent, stage, frames_done, frames_total, questions)

    def stopped():
        return bool(stop_callback and stop_callback())

    with tempfile.TemporaryDirectory(prefix="tsw_youtube_part_") as workdir:
        progress(5, "Preparing selected video part")
        if stopped():
            return {"stopped": True, "questions": []}

        stream = _resolve_video_stream(youtube_url)
        progress(12, "Video stream resolved")
        if stopped():
            return {"stopped": True, "questions": []}

        frames = _extract_frames_from_stream(
            stream,
            Path(workdir) / "frames",
            start_seconds,
            end_seconds,
            interval_seconds=max(8, int(interval_seconds)),
            progress_callback=download_callback,
            stop_callback=stop_callback,
        )
        progress(35, "Sample frames extracted directly from stream", 0, len(frames), 0)
        if stopped():
            return {"stopped": True, "questions": []}

        unique = _remove_near_duplicates(frames)[:150]
        total = len(unique)
        progress(40, "Duplicate frames removed", 0, total, 0)

        questions = []
        batch_size = 6
        for start in range(0, total, batch_size):
            if stopped():
                return {"stopped": True, "questions": questions}

            batch = unique[start:start + batch_size]
            found = _analyze_batch(batch, transcript_text=transcript_text)

            for item in found:
                if not isinstance(item, dict):
                    continue
                try:
                    local_index = int(item.get("frame_index", 0))
                except (TypeError, ValueError):
                    local_index = 0
                if 1 <= local_index <= len(batch):
                    global_frame = start + local_index
                    approx = int(start_seconds + (global_frame - 1) * interval_seconds)
                    item["approx_seconds"] = approx
                    item["approx_timestamp"] = (
                        f"{approx // 3600:02d}:"
                        f"{(approx % 3600) // 60:02d}:"
                        f"{approx % 60:02d}"
                    )
                questions.append(item)

            done = min(start + len(batch), total)
            pct = 40 + int((done / max(total, 1)) * 55)
            progress(pct, "Scanning frames with OpenAI", done, total, len(questions))

        deduped, seen = [], set()
        for item in questions:
            key = _question_key(item)
            if key and key not in seen:
                seen.add(key)
                deduped.append(item)

        progress(100, "Completed", total, total, len(deduped))
        return {
            "stopped": False,
            "video_title": str(stream.get("title") or ""),
            "questions": deduped,
            "frames_total": total,
        }
