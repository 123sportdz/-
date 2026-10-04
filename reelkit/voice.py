"""voice — تعليق عربي مولّد (TTS) ليصير الفيديو إنتاجك الخاص لا مجرد إعادة نشر.

محرّكان:
  1) Gemini TTS  — جودة عالية، يحتاج مفتاح Gemini (نفس مفتاح العنوان)
  2) Edge TTS    — مجاني تماماً بلا مفاتيح، وفيه **صوت جزائري** (ar-DZ-IsmaelNeural)

الاستخدام:
    from reelkit.voice import say
    say("هدف رائع لمنتخب الجزائر!", "voice.wav")   # يجرّب Gemini ثم Edge
"""
import base64, json, os, time, urllib.request, wave

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
TTS_MODELS = ["gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"]
# أصوات Gemini المتعددة اللغات (Kore/Fenrir تعمل جيداً بالعربية)
GEMINI_VOICES = ["Fenrir", "Kore", "Charon", "Orus", "Puck"]
EDGE_DEFAULT = "ar-DZ-IsmaelNeural"          # جزائري 🇩🇿
EDGE_ALT = "ar-MA-JamalNeural"               # مغاربي
STYLE = "اقرأ بصوت مذيع رياضي متحمس ومحترف، بإيقاع سريع وواضح: "


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


def tts_gemini(text, out_wav, api_key=None, model=None, voice="Fenrir", timeout=180):
    key = _key(api_key)
    if not key:
        raise RuntimeError("ما فيه مفتاح Gemini")
    models = ([model] if model else []) + [m for m in TTS_MODELS if m != model]
    last = None
    for m in models:
        try:
            body = {"contents": [{"parts": [{"text": STYLE + text}]}],
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
                    if "rate=" in mt:
                        rate = int(mt.split("rate=")[-1])
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


def say(text, out_wav, engine="auto", api_key=None, voice=None, gemini_model=None):
    """يولّد ملف wav للتعليق. engine: auto | gemini | edge"""
    text = (text or "").strip()
    if not text:
        raise ValueError("نص التعليق فاضي")
    errors = []
    order = {"auto": ["gemini", "edge"], "gemini": ["gemini"], "edge": ["edge"]}[engine]
    for e in order:
        try:
            if e == "gemini":
                p = tts_gemini(text, out_wav, api_key=api_key, model=gemini_model,
                               voice=voice or "Fenrir")
            else:
                p = tts_edge(text, out_wav, voice=voice or EDGE_DEFAULT)
            return {"path": p, "engine": e, "seconds": wav_seconds(p)}
        except Exception as ex:
            errors.append(f"{e}: {ex}")
    raise RuntimeError("فشل توليد التعليق — " + " | ".join(errors))


def wav_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / float(w.getframerate() or 1), 2)
    except Exception:
        return 0.0
