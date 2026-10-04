"""ai — عنوان ووصف وتاجات احترافية بالعربية عبر Gemini (صور + كابشن + OCR).

الاستخدام:
    from reelkit.ai import gemini_title
    meta = gemini_title("reel.mp4", caption="د82' | هدف ثانٍ لـ المغرب...", brand="الجزائر الجديدة TV")
    # -> {title, description, tags, hashtags, model}

المفتاح: config.json -> "gemini_api_key"  أو  متغير البيئة GEMINI_API_KEY
"""
import base64, json, os, re, subprocess, time, urllib.request, urllib.error

DEFAULT_MODELS = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash",
                  "gemini-2.5-flash", "gemini-flash-latest"]
API = "https://generativelanguage.googleapis.com/v1beta"


def _key(api_key=None):
    k = api_key or os.environ.get("GEMINI_API_KEY")
    if k:
        return k
    try:                                   # من config.json
        import json as _j
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "config.json"
        if p.exists():
            return (_j.loads(p.read_text(encoding="utf-8")) or {}).get("gemini_api_key")
    except Exception:
        pass
    return None


def _http(url, payload=None, key=None, timeout=90, retries=4):
    """طلب مع إعادة محاولة تلقائية (503/timeout شائعة في وقت الذروة)."""
    data = json.dumps(payload).encode() if payload is not None else None
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data,
                                         headers={"Content-Type": "application/json",
                                                  "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (408, 429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (2 ** attempt))     # 1.5s, 3s, 6s
                continue
            raise
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1.5 * (2 ** attempt)); continue
            raise
    raise last


def list_models(api_key=None):
    key = _key(api_key)
    if not key:
        raise RuntimeError("ما فيه مفتاح Gemini (config.gemini_api_key أو GEMINI_API_KEY)")
    d = _http(f"{API}/models", key=key)
    return [m["name"].replace("models/", "") for m in d.get("models", [])
            if "generateContent" in m.get("supportedGenerationModels", m.get("supportedGenerationMethods", []))]


def pick_model(api_key=None, prefer=None):
    """يختار أفضل موديل flash متاح فعلياً على المفتاح."""
    if prefer:
        return prefer
    try:
        avail = list_models(api_key)
    except Exception:
        return DEFAULT_MODELS[0]
    for want in DEFAULT_MODELS:
        if want in avail:
            return want
    flash = [m for m in avail if "flash" in m and not any(x in m for x in ("image", "tts", "lite", "preview", "transcribe"))]
    if flash:
        return sorted(flash, key=lambda s: [int(x) for x in re.findall(r"\d+", s)] or [0], reverse=True)[0]
    return avail[0] if avail else DEFAULT_MODELS[0]


def _frames(video, times=(0.25, 0.6), width=900):
    """لقطات من الفيديو (نسبة من المدة) -> [ (base64 jpeg), ... ]"""
    out = []
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", video], capture_output=True, text=True,
                                    timeout=30).stdout or 0)
    except Exception:
        dur = 0
    for frac in times:
        t = max(0.3, dur * frac)
        try:
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", video,
                                  "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2",
                                  "-c:v", "mjpeg", "-q:v", "4", "pipe:1"],
                                 capture_output=True, timeout=60).stdout
            if raw:
                out.append(base64.b64encode(raw).decode())
        except Exception:
            pass
    return out


def _extract(txt, key):
    """JSON متسامح: يقبل رد مقصوص أو فيه نص زائد."""
    txt = re.sub(r"^```(json)?|```$", "", (txt or "").strip(), flags=re.M).strip()
    try:
        return json.loads(txt)
    except Exception:
        pass
    m = re.search(r'\{[^{}]*"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', txt, re.S)
    if m:
        try:
            return json.loads('{"' + key + '":"' + m.group(1) + '"}')
        except Exception:
            return {key: m.group(1)}
    m = re.search(r'"' + key + r'"\s*:\s*"?(.*)$', txt, re.S)   # رد مقصوص
    if m:
        return {key: m.group(1).rstrip('"').strip()}
    return {key: (txt or "").strip().strip('"')}


PROMPT = """أنت محرر رياضي محترف في قناة «{brand}» الإخبارية الجزائرية، ومتخصص في كتابة عناوين يوتيوب/شورتس عربية تجيب مشاهدات.

عندك مقطع هدف كرة قدم. معلومات متوفرة:
- كابشن المصدر: {caption}
- نص مقروء من لوحة النتيجة (OCR): {ocr}
- الصور المرفقة: لقطات من المقطع (شاهد لوحة النتيجة، الألوان، الفريقين، اللاعبين).

اكتب محتوى عربي احترافي واحترافي جداً:
1) العنوان: جذاب، دقيق، يبدأ بحدث قوي، يذكر الفريقين والمناسبة إن أمكن، أقل من 90 حرفاً، بدون علامات مبالغة رخيصة وبدون إيموجي في العنوان.
2) الوصف: 2-4 أسطر عربية فصيحة موجزة + سطر دعوة للمتابعة + هاشتاقات مهمة.
3) 10-14 وسم (tags) عربية وإنجليزية مختصرة تخدم الوصول.
4) درجة الثقة 0-1 بمعلومات المقطع.

قواعد صارمة:
- لا تخترع أسماء لاعبين أو نتيجة أو منافسة غير مؤكدة. لو المنافسة غير واضحة لا تذكرها.
- لا تكتب "شاهد" في بداية العنوان. ابدأ بالحدث نفسه.
- العنوان أقل من 90 حرفاً، بلا إيموجي."
أعد النتيجة JSON فقط بهذا الشكل:
{{"title":"...","description":"...","tags":["..."],"confidence":0.0}}"""


def gemini_title(video=None, caption="", ocr="", brand="الجزائر الجديدة TV",
                 api_key=None, model=None, extra="", timeout=120):
    """يولّد عنوان/وصف/تاجات بالذكاء الاصطناعي من (صور المقطع + الكابشن + OCR)."""
    key = _key(api_key)
    if not key:
        raise RuntimeError("ما فيه مفتاح Gemini — حطه في config.json باسم gemini_api_key")
    mdl = pick_model(key, prefer=model)
    parts = [{"text": PROMPT.format(brand=brand, caption=caption or "—", ocr=ocr or "—")
              + (("\n\nملاحظات إضافية: " + extra) if extra else "")}]
    if video and os.path.exists(video):
        for b64 in _frames(video):
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.95, "topP": 0.95, "maxOutputTokens": 2048,
                                 "responseMimeType": "application/json"}}
    last = None
    for m in [mdl] + [x for x in DEFAULT_MODELS if x != mdl][:2]:
        try:
            r = _http(f"{API}/models/{m}:generateContent", body, key=key, timeout=timeout)
            txt = "".join(p.get("text", "") for p in
                          r["candidates"][0]["content"]["parts"])
            j = _extract(txt, "title")
            j["model"] = m
            j.setdefault("tags", [])
            return j
        except urllib.error.HTTPError as e:
            last = f"{m}: HTTP {e.code} {e.read().decode()[:120]}"
            continue
        except Exception as e:
            last = f"{m}: {type(e).__name__} {str(e)[:120]}"
            continue
    raise RuntimeError(f"فشل توليد العنوان: {last}")


COMMENTARY_PROMPT = """أنت معلّق رياضي عربي محترف. اكتب **تعليقاً صوتياً قصيراً جداً** (جملة أو جملتان،
بحد أقصى 22 كلمة) يُقرأ فوق مقطع هدف كرة قدم. المعلومات المتاحة:
- كابشن المصدر: {caption}
- OCR لوحة النتيجة: {ocr}
- العنوان: {title}
- الصور: لقطات من المقطع.

قواعد:
- عربية فصيحة مبسّطة، حماسية، بلا مبالغات رخيصة.
- اذكر الفريق/اللاعب/الدقيقة فقط لو تأكدت منها من المعلومات أو الصور.
- لا تكتب أي تنسيق أو عنوان أو رموز — النص فقط كما يُقال بالصوت.
أعد JSON: {{"commentary":"..."}}"""


def commentary(video=None, caption="", ocr="", title="", api_key=None, model=None, timeout=90):
    """يكتب نص التعليق الصوتي (جملة قصيرة)."""
    key = _key(api_key)
    if not key:
        raise RuntimeError("ما فيه مفتاح Gemini")
    mdl = pick_model(key, prefer=model)
    parts = [{"text": COMMENTARY_PROMPT.format(caption=caption or "—", ocr=ocr or "—",
                                               title=title or "—")}]
    if video and os.path.exists(video):
        for b64 in _frames(video, times=(0.35,)):
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.95, "maxOutputTokens": 2048,
                                 "responseMimeType": "application/json"}}
    r = _http(f"{API}/models/{mdl}:generateContent", body, key=key, timeout=timeout)
    txt = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
    j = _extract(txt, "commentary")
    return {"commentary": (j.get("commentary") or "").strip(), "model": mdl, "raw": txt[:200]}


def ai_meta(video, caption="", ocr="", brand="", api_key=None, model=None):
    """يحاول Gemini، ولو فشل يرجع لمحلّل الكابشن العادي (بلا توقف)."""
    from . import title as T
    err = None
    try:
        j = gemini_title(video, caption=caption, ocr=ocr, brand=brand, api_key=api_key, model=model)
        if (j.get("title") or "").strip():
            j.setdefault("description", "")
            j.setdefault("tags", [])
            j["source"] = "gemini"
            return j
        err = "gemini: empty title"      # نجح الطلب لكن بلا عنوان صالح → نكمل للبديل
    except Exception as e:
        err = str(e)[:200]
    try:
        fb = T.from_caption(caption, brand=brand or "الحدث") if caption else {}
        fb = fb or T.suggest(video, brand=brand or "الحدث")
        fb["source"] = "caption-fallback"
        if err:
            fb["ai_error"] = err
        return fb
    except Exception:
        return {}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="توليد عنوان احترافي بالذكاء الاصطناعي")
    ap.add_argument("--video", required=True)
    ap.add_argument("--caption", default="")
    ap.add_argument("--brand", default="")
    ap.add_argument("--ocr", default="")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    out = ai_meta(a.video, caption=a.caption, ocr=a.ocr, brand=a.brand, model=a.model)
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 🌍 الترجمة
TRANS_PROMPT = """أنت مسؤول نشر رياضي. ترجم هذا العنوان العربي لعدة لغات لوصف يوتيوب.
العنوان: {title}
الوصف المختصر: {desc}

أعد JSON فقط:
{{"en": "short punchy english title (<=70 chars, include the goal/highlight wording)",
  "fr": "titre français court et vif (<=70 chars)",
  "en_desc": "one english sentence (<=120 chars)",
  "fr_desc": "une phrase française (<=120 chars)",
  "en_tags": ["english","keywords","max 6"],
  "fr_tags": ["mots","clés","français","max 6"]}}"""


def translate_meta(title, desc="", api_key=None, model=None, timeout=90):
    """🌍 ترجمة العنوان/الوصف لـEN/FR (لا تفشل المسار: ترجّع {} عند أي خطأ)."""
    key = _key(api_key)
    if not key or not (title or "").strip():
        return {}
    mdl = pick_model(key, prefer=model)
    body = {"contents": [{"role": "user", "parts": [
                {"text": TRANS_PROMPT.format(title=title, desc=(desc or "")[:300])}]}],
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1024,
                                 "responseMimeType": "application/json"}}
    for m in [mdl] + [x for x in DEFAULT_MODELS if x != mdl][:1]:
        try:
            r = _http(f"{API}/models/{m}:generateContent", body, key=key, timeout=timeout)
            txt = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
            j = _extract(txt, "en")
            if isinstance(j, dict) and (j.get("en") or j.get("fr")):
                return j
        except Exception:
            continue
    return {}


def multilang_block(trans, sep="\n"):
    """يبني بلوك الوصف متعدد اللغات."""
    if not trans:
        return ""
    out = []
    if trans.get("en"):
        out.append(f"🇬🇧 {trans['en']}")
        if trans.get("en_desc"):
            out.append(f"   {trans['en_desc']}")
    if trans.get("fr"):
        out.append(f"🇫🇷 {trans['fr']}")
        if trans.get("fr_desc"):
            out.append(f"   {trans['fr_desc']}")
    return sep.join(out)
