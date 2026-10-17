"""encode — اختيار مرمّز الفيديو (GPU / CPU) موحّداً لكل مسارات الترميز.

كان `libx264` مثبّتاً بالقوة في كل مكان (render / replay / montage / التهذيب)
رغم أن الجهاز المستهدف فيه RTX — فتبقى المعالجة على المعالج أبطأ 3-6 مرات.

الفكرة: فحص **حقيقي** لمرمّز NVENC (ترميز فعلي لإطارات تجريبية، لا مجرد ظهوره
في `ffmpeg -encoders` — النسخ المبنية بـnvenc تظهر في القائمة حتى بلا كرت!).

  from reelkit import encode
  enc, vargs = encode.video_args("auto", crf=20, preset="medium")
  cmd = ["ffmpeg", ... *vargs ...]

الأولوية: --encoder > REEL_ENCODER > config.encoder > auto.
"""
from __future__ import annotations

import os
import subprocess

# نتيجة الفحص الحقيقي لـNVENC (None = لم يُفحص بعد) — الفحص مرة واحدة لكل عملية
_PROBE = {"nvenc": None}

# خريطة أسماء presets الشائعة (x264) إلى مستويات NVENC p1..p7
_NV_PRESET = {
    "ultrafast": "p1", "superfast": "p2", "veryfast": "p2",
    "faster": "p3", "fast": "p3", "medium": "p4",
    "slow": "p5", "slower": "p6", "veryslow": "p7",
}


def nvenc_ok(timeout=45):
    """فحص حقيقي: هل h264_nvenc يستطيع فعلاً الترميز على هذا الجهاز؟

    نرمّز إطارات تجريبية **بنفس وسائط الإنتاج** (rc vbr + cq) وبأبعاد فوق حدّ NVENC
    الأدنى — الظهور في قائمة encoders لا يكفي (نسخ مبنية بـnvenc تظهر بلا كرت!).
    النتيجة تُخزّن للعملية كلها (الفحص يكلّف ~ثانية).
    """
    if _PROBE["nvenc"] is not None:
        return _PROBE["nvenc"]
    ok = False
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.3:r=10",
             "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "20",
             "-b:v", "0", "-f", "null", "-"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)
        ok = (r.returncode == 0)
    except Exception:
        ok = False
    _PROBE["nvenc"] = ok
    return ok


def pick(prefer="auto"):
    """يحسم الاختيار ويرجّع 'nvenc' أو 'x264'.

    prefer: auto | nvenc | cpu (مع تجاوز بالبيئة REEL_ENCODER).
    nvenc صريح بلا كرت ⇒ تراجع صامت لـx264 (نفس فلسفة --device: لا نموت بسبب GPU).
    """
    # الأولوية: اختيار صريح (--encoder/cpu) > REEL_ENCODER > auto
    pref = str(prefer or "auto").strip().lower()
    if pref in ("auto", ""):
        pref = str(os.environ.get("REEL_ENCODER") or "auto").strip().lower()
    if pref in ("cpu", "x264", "libx264", "software"):
        return "x264"
    if pref in ("nvenc", "gpu", "cuda", "nvidia"):
        return "nvenc" if nvenc_ok() else "x264"
    return "nvenc" if nvenc_ok() else "x264"


def args_for(enc, crf=20, preset="medium"):
    """وسائط ffmpeg للمرمّز المختار.

    NVENC: ‎-rc vbr -cq N -b:v 0‎ (جودة ثابتة شبيهة بـcrf) + preset p1..p7.
    """
    if enc == "nvenc":
        p = _NV_PRESET.get(str(preset).strip().lower(), "p4")
        try:
            cq = max(0, min(51, int(crf)))
        except Exception:
            cq = 20
        return ["-c:v", "h264_nvenc", "-preset", p, "-rc", "vbr",
                "-cq", str(cq), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", str(preset), "-crf", str(crf)]


def video_args(prefer="auto", crf=20, preset="medium"):
    """الواجهة المختصرة: (اسم المرمّز, وسائطه)."""
    enc = pick(prefer)
    return enc, args_for(enc, crf=crf, preset=preset)


def describe(enc):
    return {"nvenc": "🚀 GPU (NVENC)", "x264": "🖥️ CPU (libx264)"}.get(enc, enc)


def should_retry_x264(enc, error_text):
    if enc != "nvenc":
        return False
    message = str(error_text or "").lower()
    return any(term in message for term in (
        "cuda_error_out_of_memory",
        "out of memory",
        "no capable devices found",
        "cannot load libcuda",
        "device setup failed",
    ))
