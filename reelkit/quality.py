"""Automatic output quality checks for generated reels."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def check(path, expected_w=1080, expected_h=1920, max_duration=0):
    """Return a small, serializable QA report; never raises for a bad media file."""
    p = Path(path)
    report = {
        "ok": False,
        "exists": p.is_file(),
        "size": p.stat().st_size if p.is_file() else 0,
        "video": False,
        "audio": False,
        "width": None,
        "height": None,
        "duration": 0.0,
        "issues": [],
    }
    if not p.is_file() or report["size"] < 1024:
        report["issues"].append("الملف غير موجود أو صغير جداً")
        return report
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            report["issues"].append("ffprobe فشل في قراءة الملف")
            return report
        data = json.loads(r.stdout or "{}")
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        report["video"] = bool(video)
        report["audio"] = bool(audio)
        if video:
            report["width"] = int(video.get("width") or 0)
            report["height"] = int(video.get("height") or 0)
        report["duration"] = round(float((data.get("format") or {}).get("duration") or 0), 2)
        if not video:
            report["issues"].append("لا يوجد مسار فيديو")
        elif expected_w and expected_h and (report["width"], report["height"]) != (expected_w, expected_h):
            report["issues"].append(f"الأبعاد {report['width']}x{report['height']} بدل {expected_w}x{expected_h}")
        if max_duration and report["duration"] > float(max_duration) + 1.0:
            report["issues"].append("المدة تتجاوز الحد المطلوب")
        report["ok"] = report["video"] and not report["issues"]
    except Exception as exc:
        report["issues"].append(f"خطأ فحص: {type(exc).__name__}")
    return report
