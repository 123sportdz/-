"""voice — تعليق عربي مولّد (TTS) ليصير الفيديو إنتاجك الخاص لا مجرد إعادة نشر.

محرّكان:
  1) Gemini TTS  — جودة عالية، يحتاج مفتاح Gemini (نفس مفتاح العنوان)
  2) Edge TTS    — مجاني تماماً بلا مفاتيح، وفيه **صوت جزائري** (ar-DZ-IsmaelNeural)

الاستخدام:
    from reelkit.voice import say
    say("هدف رائع لمنتخب الجزائر!", "voice.wav")   # يجرّب Gemini ثم Edge
"""
import base64, json, os, re, time, urllib.request, wave

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"]
# أصوات Gemini المتعددة اللغات (Kore/Fenrir تعمل جيداً بالعربية)
GEMINI_VOICES = ("Fenrir", "Kore", "Charon", "Orus", "Puck")
EDGE_VOICES = {
    "ar-DZ-IsmaelNeural": "جزائري — إسماعيل (رجالي)",
    "ar-DZ-AminaNeural": "جزائري — أمينة (نسائي)",
    "ar-MA-JamalNeural": "مغاربي — جمال (رجالي)",
    "ar-MA-MounaNeural": "مغاربي — مونة (نسائي)",
    "ar-TN-HediNeural": "تونسي — هادي (رجالي)",
    "ar-EG-ShakirNeural": "مصري — شاكر (رجالي)",
    "ar-SA-HamedNeural": "خليجي — حامد (رجالي)",
    "ar-SA-ZariyahNeural": "خليجي — زارية (نسائي)",
}
EDGE_DEFAULT = "ar-DZ-IsmaelNeural"
EDGE_ALT = "ar-MA-JamalNeural"
COMMENTARY_STYLES = {
    "broadcast": {
        "label": "معلّق رياضي حماسي",
        "text": "معلّق كرة قدم محترف، حماسي ومتزن، بجمل قصيرة وصور لغوية واضحة.",
        "tts": "أدِّ النص بصوت معلّق كرة قدم محترف، حماسي ومتزن، مع وضوح مخارج الحروف.",
    },
    "algerian": {
        "label": "روح جزائرية",
        "text": "تعليق رياضي بلمسة جزائرية مفهومة، قريب من الجمهور، دون اختلاق أسماء أو معلومات.",
        "tts": "أدِّ النص بلمسة جزائرية دافئة وحماس أصيل، مع نطق واضح وغير متكلف.",
    },
    "analyst": {
        "label": "محلّل هادئ",
        "text": "محلل رياضي هادئ يصف ما يظهر فعلاً في اللعب، بلا صراخ أو مبالغة.",
        "tts": "أدِّ النص بصوت محلل رياضي هادئ وواثق، بسرعة متوسطة ووقفات واضحة.",
    },
    "cinematic": {
        "label": "سينمائي متصاعد",
        "text": "تعليق سينمائي موجز يتصاعد تدريجياً نحو لحظة الحدث، بلا صراخ مصطنع.",
        "tts": "أدِّ النص بإيقاع سينمائي قصير يتصاعد تدريجياً، ثم اختم بثبات ووضوح.",
    },
    "calm": {
        "label": "ملخص هادئ",
        "text": "تعليق واضح وهادئ مناسب للملخص والتحليل، مع تجنب المبالغة.",
        "tts": "أدِّ النص بنبرة هادئة وواضحة، بسرعة مريحة وبدون انفعال زائد.",
    },
}
DEFAULTS = {
    "voice_engine": "auto", "commentary_style": "broadcast",
    "edge_voice": EDGE_DEFAULT, "gemini_voice": "Fenrir",
    "voice_rate": 10, "voice_pitch": 0, "commentary_energy": 70,
    "commentary_words": 22, "voice_gain": 1.9, "voice_duck": 0.22, "voice_mix": "auto",
}
STYLE = COMMENTARY_STYLES["broadcast"]["tts"]


def _bounded_int(value, name, low, high):
    if isinstance(value, bool):
        raise ValueError(f"{name} يجب أن يكون رقماً صحيحاً")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} يجب أن يكون رقماً صحيحاً") from None
    if isinstance(value, float) and value != number:
        raise ValueError(f"{name} يجب أن يكون رقماً صحيحاً")
    if not low <= number <= high:
        raise ValueError(f"{name} يجب أن يكون بين {low} و{high}")
    return number


def normalize_controls(values=None):
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ValueError("إعدادات الصوت غير صالحة")
    engine = str(values.get("voice_engine", values.get("engine", DEFAULTS["voice_engine"]))).strip()
    style = str(values.get("commentary_style", DEFAULTS["commentary_style"])).strip()
    edge_voice = str(values.get("edge_voice", DEFAULTS["edge_voice"])).strip()
    gemini_voice = str(values.get("gemini_voice", DEFAULTS["gemini_voice"])).strip()
    if engine not in ("auto", "edge", "gemini"):
        raise ValueError("محرّك الصوت غير معروف")
    if style not in COMMENTARY_STYLES:
        raise ValueError("أسلوب التعليق غير معروف")
    if edge_voice not in EDGE_VOICES:
        raise ValueError("صوت Edge غير معروف")
    if gemini_voice not in GEMINI_VOICES:
        raise ValueError("صوت Gemini غير معروف")
    energy = _bounded_int(values.get("commentary_energy", DEFAULTS["commentary_energy"]), "حماسة التعليق", 0, 100)
    words = _bounded_int(values.get("commentary_words", DEFAULTS["commentary_words"]), "طول التعليق", 8, 80)
    mix = str(values.get("voice_mix", DEFAULTS["voice_mix"])).strip()
    if mix not in ("auto", "fixed", "original", "voice_only"):
        raise ValueError("نمط مزج الصوت غير معروف")
    rate = _bounded_int(values.get("voice_rate", DEFAULTS["voice_rate"]), "سرعة الصوت", -20, 50)
    pitch = _bounded_int(values.get("voice_pitch", DEFAULTS["voice_pitch"]), "طبقة الصوت", -12, 12)
    try:
        gain_raw = values.get("voice_gain", DEFAULTS["voice_gain"])
        duck_raw = values.get("voice_duck", DEFAULTS["voice_duck"])
        if isinstance(gain_raw, bool) or isinstance(duck_raw, bool):
            raise ValueError
        gain, duck = float(gain_raw), float(duck_raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("مستويات الصوت غير صالحة") from None
    if not 0.5 <= gain <= 3.0:
        raise ValueError("مكسب صوت المعلّق يجب أن يكون بين 0.5 و3.0")
    if not 0.0 <= duck <= 1.0:
        raise ValueError("مستوى صوت الملعب يجب أن يكون بين 0 و1")
    return {
        "voice_engine": engine, "commentary_style": style,
        "edge_voice": edge_voice, "gemini_voice": gemini_voice,
        "voice_rate": rate, "voice_pitch": pitch, "commentary_energy": energy,
        "commentary_words": words, "voice_mix": mix, "voice_gain": gain, "voice_duck": duck,
    }


def normalize_script(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        raise ValueError("نص التعليق يجب أن يكون نصاً")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 500:
        raise ValueError("نص التعليق اليدوي لا يتجاوز 500 حرف")
    return text


def edge_rate(value):
    if isinstance(value, str) and value.strip().endswith("%"):
        offset = _bounded_int(value.strip()[:-1].replace("+", ""), "سرعة الصوت", -50, 100)
    else:
        offset = _bounded_int(value, "سرعة الصوت", -50, 100)
    return f"{offset:+d}%"


def edge_pitch(value):
    if isinstance(value, str) and value.strip().lower().endswith("hz"):
        offset = _bounded_int(value.strip()[:-2].replace("+", ""), "طبقة الصوت", -20, 20)
    else:
        offset = _bounded_int(value, "طبقة الصوت", -20, 20)
    return f"{offset:+d}Hz"


def _key(api_key=None):
    if api_key:
        return api_key
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "config.json"
        if p.exists():
            return (json.loads(p.read_text(encoding="utf-8")) or {}).get("gemini_api_key")
    except Exception:
        pass
    return None


def _pcm_to_wav(pcm, path, rate=24000, channels=1, width=2):
    with wave.open(path, "wb") as w:
        w.setnchannels(channels); w.setsampwidth(width); w.setframerate(rate)
        w.writeframes(pcm)
    return path


def tts_gemini(text, out_wav, api_key=None, model=None, voice="Fenrir", timeout=180,
               style="broadcast", energy=70):
    key = _key(api_key)
    if not key:
        raise RuntimeError("ما فيه مفتاح Gemini")
    models = ([model] if model else []) + [m for m in TTS_MODELS if m != model]
    last = None
    for m in models:
        try:
            style_instruction = COMMENTARY_STYLES.get(style, COMMENTARY_STYLES["broadcast"])["tts"]
            energy = _bounded_int(energy, "حماسة التعليق", 0, 100)
            energy_note = f"درجة الحماسة {energy} من 100؛ حافظ على وضوح الكلام ولا تصرخ."
            body = {"contents": [{"parts": [{"text": f"{style_instruction} {energy_note}\n\nاقرأ النص كما هو دون إضافة معلومات: {text}"}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"],
                                         "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig":
                                                                          {"voiceName": voice}}}}}
            req = urllib.request.Request(f"{GEMINI_API}/models/{m}:generateContent",
                                         data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "x-goog-api-key": key})
            d = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        d = json.loads(r.read())
                    break
                except Exception as _e:
                    if attempt == 2:
                        raise
                    time.sleep(2 * (attempt + 1))
            for part in d["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    rate = 24000
                    mt = part["inlineData"].get("mimeType", "")
                    mrate = re.search(r"rate=(\d+)", mt)   # كان split هشّاً لو أضافت قوقل معاملاً بعد rate
                    if mrate:
                        rate = int(mrate.group(1))
                    _pcm_to_wav(base64.b64decode(part["inlineData"]["data"]), out_wav, rate=rate)
                    return out_wav
            raise RuntimeError("بلا صوت في الرد")
        except Exception as e:
            last = f"{m}: {type(e).__name__} {str(e)[:100]}"
    raise RuntimeError(f"Gemini TTS فشل — {last}")


def tts_edge(text, out_wav, voice=EDGE_DEFAULT, rate="+10%", pitch="+0Hz", timeout=180):
    """مجاني بلا مفاتيح (Microsoft Edge). يحتاج إنترنت."""
    try:
        import edge_tts, asyncio
    except ImportError as e:
        raise RuntimeError("pip install edge-tts") from e

    async def _run():
        # ✅ v1.45: مهلة `timeout` كانت مهملة تماماً — نوصلها للمكتبة ونغلّف بـwait_for
        c = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                 connect_timeout=10, receive_timeout=max(30, int(timeout)))
        await c.save(out_wav)
    try:
        asyncio.run(asyncio.wait_for(_run(), timeout=float(timeout)))
    except asyncio.TimeoutError:
        raise RuntimeError(f"Edge TTS تجاوز المهلة ({timeout}s)")
    if not os.path.exists(out_wav) or os.path.getsize(out_wav) < 2000:
        raise RuntimeError("Edge TTS ما طلع صوت")
    return out_wav


def say(text, out_wav, engine="auto", api_key=None, voice=None, gemini_model=None,
        rate="+10%", pitch="+0Hz", style="broadcast", edge_voice=None,
        gemini_voice=None, energy=70):
    """يولّد ملف صوتي للتعليق. engine: auto | gemini | edge
    rate: سرعة Edge TTS (تُستخدم أيضاً عند إعادة المحاولة لتقصير تعليق أطول من المقطع)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("نص التعليق فاضي")
    if engine not in ("auto", "gemini", "edge"):
        raise ValueError("محرّك الصوت غير معروف")
    if style not in COMMENTARY_STYLES:
        raise ValueError("أسلوب التعليق غير معروف")
    if edge_voice is not None and edge_voice not in EDGE_VOICES:
        raise ValueError("صوت Edge غير معروف")
    if gemini_voice is not None and gemini_voice not in GEMINI_VOICES:
        raise ValueError("صوت Gemini غير معروف")
    energy = _bounded_int(energy, "حماسة التعليق", 0, 100)
    errors = []
    order = {"auto": ["gemini", "edge"], "gemini": ["gemini"], "edge": ["edge"]}[engine]
    for e in order:
        try:
            if e == "gemini":
                selected_voice = gemini_voice or "Fenrir"
                if voice in GEMINI_VOICES:
                    selected_voice = voice
                p = tts_gemini(text, out_wav, api_key=api_key, model=gemini_model,
                               voice=selected_voice, style=style, energy=energy)
            else:
                selected_voice = edge_voice or EDGE_DEFAULT
                if voice and voice not in GEMINI_VOICES:
                    selected_voice = voice
                p = tts_edge(text, out_wav, voice=selected_voice,
                             rate=edge_rate(rate), pitch=edge_pitch(pitch))
            return {"path": p, "engine": e, "seconds": audio_seconds(p)}
        except Exception as ex:
            errors.append(f"{e}: {ex}")
    raise RuntimeError("فشل توليد التعليق — " + " | ".join(errors))


def wav_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / float(w.getframerate() or 1), 2)
    except Exception:
        return 0.0


def audio_seconds(path):
    """مدة أي ملف صوتي (WAV أو MP3…) عبر ffprobe، مع رجوع لـwave للـWAV.

    ⚠️ Edge TTS يكتب **MP3** مهما كان امتداد الملف، فكان wave.open يفشل دائماً
    ويرجّع 0.0 ⇒ توقيت الكابشن كلمة-بكلمة ينضغط إلى 0.6s، وحارس «التعليق أطول
    من المقطع» في reel.py شرطه مستحيل. القياس عبر ffprobe يصلح المسارين."""
    s = wav_seconds(path)
    if s > 0:
        return s
    try:
        import subprocess
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=30)
        return round(float(out.stdout.strip()), 2)
    except Exception:
        return 0.0
