"""Automatic output quality checks for generated reels."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def check(path, expected_w=1080, expected_h=1920, max_duration=0, audio_required=False):
    """Return a small, serializable QA report; never raises for a bad media file."""
    p = Path(path)
    report = {
        "ok": False,
        "exists": p.is_file(),
        "size": p.stat().st_size if p.is_file() else 0,
        "video": False,
        "audio": False,
        "audio_required": bool(audio_required),
        "video_codec": None,
        "audio_codec": None,
        "fps": 0.0,
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
            report["video_codec"] = video.get("codec_name")
            # 🛡️ avg_frame_rate قد يكون "0/0" (قيمة صحيحة الشكل لكن صفرية) — نجرّب الاثنين
            def _fps(s):
                try:
                    n, d = str(s or "").split("/", 1)
                    d = float(d)
                    return float(n) / d if d and float(n) > 0 else 0.0
                except (ValueError, TypeError, ZeroDivisionError):
                    return 0.0
            report["fps"] = round(max(_fps(video.get("avg_frame_rate")),
                                      _fps(video.get("r_frame_rate"))), 3)
        if audio:
            report["audio_codec"] = audio.get("codec_name")
        report["duration"] = round(float((data.get("format") or {}).get("duration") or 0), 2)
        if not video:
            report["issues"].append("لا يوجد مسار فيديو")
        if audio_required and not audio:
            report["issues"].append("اختفى مسار الصوت من المخرج")
        if video and report["fps"] <= 0:
            report["issues"].append("معدل الإطارات غير صالح")
        if video and expected_w and expected_h and (report["width"], report["height"]) != (expected_w, expected_h):
            report["issues"].append(f"الأبعاد {report['width']}x{report['height']} بدل {expected_w}x{expected_h}")
        if max_duration and report["duration"] > float(max_duration) + max(0.25, 0.02 * float(max_duration)):
            report["issues"].append("المدة تتجاوز الحد المطلوب")
        report["ok"] = report["video"] and not report["issues"]
    except Exception as exc:
        report["issues"].append(f"خطأ فحص: {type(exc).__name__}")
    return report
