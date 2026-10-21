"""⏱️ تقدير زمن الرندر قبل البدء — أولوية 5 من PROJECT_STATUS_AR.md.

تقدير استرشادي (heuristic) بالضرب بعوامل معروفة، لا قياس فعلي:
- سرعة المعالجة الأساسية: عدد ثوانٍ المعالجة لكل ثانية فيديو على CPU.
- GPU (NVENC/CUDA) يقصّر الرندر 3-6×، والجودة العالية تطيله.
- الشاشة المقسومة والإعادة البطيئة يضاعفان العمل على الفريمات.
القيم دليل تخطيطي فقط لتوقع الانتظار — ليست وعداً بأداء.
"""

from __future__ import annotations

from typing import Any, Dict

# معامل الجودة الأساسي (multiplier على سرعة المعالجة)
_QUALITY_FACTOR = {"auto": 1.0, "fast": 0.8, "balanced": 1.0, "high": 1.4, "ultra": 2.0}

# ثوانٍ معالجة لكل ثانية فيديو على CPU (كشف + تتبع + رندر 1080x1920)
_CPU_SPF = {"fast": 1.2, "pro": 2.5}


def human_seconds(seconds: float) -> str:
    """صياغة عربية مختصرة: 92 → «دقيقة و32 ثانية»."""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} ثانية"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} دقيقة و{sec} ثانية" if sec else f"{minutes} دقيقة"
    hours, minutes = divmod(minutes, 60)
    out = f"{hours} ساعة"
    if minutes:
        out += f" و{minutes} دقيقة"
    return out


def estimate_render_seconds(duration_s: float, *, quality: str = "auto",
                            split_screen: bool = False, replay: bool = False,
                            engine: str = "pro", gpu: bool = False,
                            max_duration: float = 0.0) -> Dict[str, Any]:
    """يرجع نطاق تقديري (min/max بالثواني) + صياغة عربية للعرض في اللوحة."""
    try:
        duration = abs(float(duration_s or 0))
    except (TypeError, ValueError):
        duration = 0.0
    try:
        cap = float(max_duration or 0)
    except (TypeError, ValueError):
        cap = 0.0
    if cap > 0:                      # المخرج مقصوص: الزمن على طول اللقطة لا المصدر
        duration = min(duration, cap) if duration > 0 else cap
    factor = _QUALITY_FACTOR.get(str(quality or "auto").lower(), 1.0)
    base = _CPU_SPF.get("pro" if str(engine or "pro").lower() != "fast" else "fast")
    spf = base * factor
    if split_screen:
        spf *= 1.4
    if replay:
        spf *= 1.3                    # الإعادة البطيئة رندر إضافي كامل
    if gpu:
        spf /= 4.0                    # NVENC/CUDA: أسرع 3-6× (نأخذ وسطاً محافظاً)
    seconds_low = duration * spf * 0.85
    seconds_high = duration * spf * 1.35
    return {
        "source_duration": round(duration, 2),
        "min": round(seconds_low, 1),
        "max": round(seconds_high, 1),
        "human": human_seconds((seconds_low + seconds_high) / 2),
        "assumptions": {"quality": str(quality), "engine": str(engine),
                        "gpu": bool(gpu), "split_screen": bool(split_screen),
                        "replay": bool(replay)},
    }
