"""voice — تعليق عربي مولّد (TTS) ليصير الفيديو إنتاجك الخاص لا مجرد إعادة نشر.

محرّكان:
  1) Gemini TTS  — جودة عالية، يحتاج مفتاح Gemini (نفس مفتاح العنوان)
  2) Edge TTS    — مجاني تماماً بلا مفاتيح، وفيه **صوت جزائري** (ar-DZ-IsmaelNeural)

الاستخدام:
    from reelkit.voice import say
    say("هدف رائع لمنتخب الجزائر!", "voice.wav")   # يجرّب Gemini ثم Edge
"""
import base64, json, math, os, re, time, urllib.error, urllib.request, wave

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts",
              "gemini-3.1-flash-tts-preview", "gemini-2.5-pro-preview-tts"]
CURRENT_TTS_MODELS = {"gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"}
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
    "voice_rate": 10, "voice_pitch": 0, "commentary_pitch": 0, "commentary_energy": 70,
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
    commentary_pitch = _bounded_int(values.get("commentary_pitch", DEFAULTS["commentary_pitch"]),
                                    "طبقة التعليق المُولّد", -4, 4)
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
        "voice_rate": rate, "voice_pitch": pitch, "commentary_pitch": commentary_pitch,
        "commentary_energy": energy, "commentary_words": words, "voice_mix": mix,
        "voice_gain": gain, "voice_duck": duck,
    }


def commentary_pitch_filters(semitones):
    semitones = _bounded_int(semitones, "طبقة التعليق المُولّد", -4, 4)
    if semitones == 0:
        return ()
    ratio = 2.0 ** (semitones / 12.0)
    target_rate = int(round(48000 * ratio))
    tempo = 48000.0 / target_rate
    return (
        f"rubberband=pitch={ratio:.8f}:tempo=1.0",
        f"aresample=48000,asetrate={target_rate},atempo={tempo:.8f},aresample=48000",
    )


def shift_commentary_pitch(path, semitones, timeout=120):
    """غيّر طبقة صوت TTS فقط مع حفظ المدة؛ لا يلمس مسار صوت الفيديو الأصلي."""
    import subprocess
    import tempfile
    from pathlib import Path

    semitones = _bounded_int(semitones, "طبقة التعليق المُولّد", -4, 4)
    source = Path(path)
    if semitones == 0:
        return str(source)
    if not source.is_file():
        raise ValueError("ملف التعليق المُولّد غير موجود")
    source_duration = audio_seconds(str(source))
    if source_duration <= 0:
        raise RuntimeError("تعذّر قياس مدة التعليق المُولّد")
    fd, output = tempfile.mkstemp(prefix="commentary-pitch-", suffix=".wav", dir=str(source.parent))
    os.close(fd)
    try:
        for audio_filter in commentary_pitch_filters(semitones):
            Path(output).unlink(missing_ok=True)
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:a:0", "-vn",
                 "-af", audio_filter, "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", output],
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0 or not Path(output).is_file() or Path(output).stat().st_size < 100:
                continue
            output_duration = audio_seconds(output)
            if output_duration > 0 and abs(output_duration - source_duration) <= max(0.15, source_duration * 0.025):
                return output
        raise RuntimeError("تعذّر تعديل طبقة التعليق المُولّد")
    except Exception:
        Path(output).unlink(missing_ok=True)
        raise


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


def _gemini_tts_request(req, timeout):
    retryable_statuses = {408, 429, 500, 502, 503, 504}
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                raise RuntimeError("استجابة Gemini TTS ليست JSON") from None
        except urllib.error.HTTPError as exc:
            if exc.code in retryable_statuses and attempt == 0:
                time.sleep(1)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == 0:
                time.sleep(1)
                continue
            raise


def _write_gemini_audio(encoded, out_wav, mime_type=""):
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        raise RuntimeError("بيانات صوت Gemini غير صالحة") from None
    if not audio:
        raise RuntimeError("Gemini أعاد صوتاً فارغاً")
    if audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
        with open(out_wav, "wb") as output:
            output.write(audio)
        return out_wav
    mime = str(mime_type or "").lower()
    if "l16" not in mime and "pcm" not in mime:
        raise RuntimeError("صيغة صوت Gemini غير مدعومة")
    match = re.search(r"(?:rate|sample_rate)\s*=\s*(\d+)", mime)
    rate = int(match.group(1)) if match else 24000
    if not 8000 <= rate <= 192000 or len(audio) % 2:
        raise RuntimeError("بيانات PCM من Gemini غير صالحة")
    return _pcm_to_wav(audio, out_wav, rate=rate)


def tts_gemini(text, out_wav, api_key=None, model=None, voice="Fenrir", timeout=60,
               style="broadcast", energy=70):
    key = _key(api_key)
    if not key:
        raise RuntimeError("ما فيه مفتاح Gemini")
    models = list(dict.fromkeys(([model] if model else []) + TTS_MODELS))
    last = None
    for model_name in models:
        try:
            energy = _bounded_int(energy, "حماسة التعليق", 0, 100)
            style_instruction = COMMENTARY_STYLES.get(style, COMMENTARY_STYLES["broadcast"])["tts"]
            energy_note = f"درجة الحماسة {energy} من 100؛ حافظ على وضوح الكلام ولا تصرخ."
            if model_name in CURRENT_TTS_MODELS:
                part = {"text": text, "speech_metadata": {
                    "style": f"{style_instruction} {energy_note}"}}
                voice_config = {"voice": voice}
            else:
                part = {"text": f"{style_instruction} {energy_note}\n\nاقرأ النص كما هو دون إضافة معلومات: {text}"}
                voice_config = {"prebuiltVoiceConfig": {"voiceName": voice}}
            body = {
                "contents": [{"role": "user", "parts": [part]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": voice_config},
                },
            }
            req = urllib.request.Request(
                f"{GEMINI_API}/models/{model_name}:generateContent",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
            )
            response = _gemini_tts_request(req, timeout)
            candidates = response.get("candidates") if isinstance(response, dict) else None
            if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
                raise RuntimeError("استجابة بلا مرشحين")
            content = candidates[0].get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                raise RuntimeError("استجابة بلا أجزاء صوتية")
            for response_part in parts:
                if not isinstance(response_part, dict):
                    continue
                inline = response_part.get("inlineData") or response_part.get("inline_data")
                if isinstance(inline, dict) and inline.get("data"):
                    mime_type = inline.get("mimeType") or inline.get("mime_type", "")
                    return _write_gemini_audio(inline["data"], out_wav, mime_type)
            raise RuntimeError("بلا صوت في الرد")
        except urllib.error.HTTPError as exc:
            last = f"{model_name}: HTTP {exc.code}"
            if exc.code in (401, 403):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = f"{model_name}: {type(exc).__name__}"
            break
        except Exception as exc:
            detail = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
            last = f"{model_name}: {detail}"
    raise RuntimeError(f"Gemini TTS فشل — {last or 'لا يوجد نموذج متاح'}")


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
        if getattr(out, "returncode", 0) != 0:
            return 0.0
        duration = float((out.stdout or "").strip())
        if not math.isfinite(duration) or duration <= 0:
            return 0.0
        return round(duration, 2)
    except Exception:
        return 0.0

def fit_word_limit(word_count, clip_seconds, speech_seconds, delay_seconds=0.5, tail_seconds=0.25, safety=0.9):
    try:
        count = max(0, int(word_count))
        clip = float(clip_seconds)
        speech = float(speech_seconds)
        delay = float(delay_seconds)
        tail = float(tail_seconds)
        margin = float(safety)
    except (TypeError, ValueError, OverflowError):
        return max(0, int(word_count)) if isinstance(word_count, int) and not isinstance(word_count, bool) else 0
    if count <= 1 or not all(math.isfinite(value) for value in (clip, speech, delay, tail, margin)) or clip <= 0 or speech <= 0 or not 0 < margin <= 1:
        return count
    available = max(0.0, clip - max(0.0, delay) - max(0.0, tail))
    if speech <= available:
        return count
    if available <= 0:
        return 1
    estimate = max(1, int(count * available / speech * margin))
    return min(count - 1, estimate)
