"""Arabic-first creative writing with Gemini and a small local draft library."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import ai as AI

ROOT = Path(__file__).resolve().parents[1]
DRAFTS_FILE = ROOT / "outputs" / "creative_drafts.json"
_DRAFTS_LOCK = threading.RLock()
MAX_DRAFTS = 100
MAX_STORE_BYTES = 3 * 1024 * 1024
MAX_TEXT_CHARS = 24_000

MODES = {
    "poem": "تعليق شعري للمقطع",
    "article": "وصف رياضي موسّع للريل",
    "story": "سرد تسلسلي للحظة",
    "script": "تعليق صوتي",
    "social": "كابشن لمنصة قصيرة",
    "rewrite": "تحرير نص رياضي",
    "ideas": "أفكار ريلز",
    "custom": "نص مخصص للريل",
    "title": "عنوان الريل",
    "description": "وصف الريل",
    "caption": "كابشن",
    "hook": "افتتاحية سريعة",
    "recap": "ملخص اللقطة",
}
LANGUAGES = {
    "ar": "العربية الفصحى",
    "dz": "الدارجة الجزائرية الطبيعية",
    "fr": "الفرنسية",
    "en": "الإنجليزية",
}
PLATFORMS = {
    "general": "عام",
    "instagram": "Instagram Reels",
    "tiktok": "TikTok",
    "youtube_shorts": "YouTube Shorts",
}
LENGTHS = {
    "short": ("موجز", 480),
    "medium": ("متوسط", 900),
    "long": ("مفصل", 1400),
}
SCRIPT_WORD_LIMITS = {"short": 22, "medium": 40, "long": 65}
MODE_GUIDANCE = {
    "poem": "اكتب تعليقاً شعرياً أصلياً من سطرين إلى أربعة، مستوحى من الحركة الظاهرة في لقطة كرة القدم؛ لا تكتب قصيدة عامة ولا تقلّد شاعراً بعينه.",
    "article": "اكتب وصفاً رياضياً موجزاً للريل، لا مقالة عامة؛ ركّز على الحدث وأهميته من دون اختلاق معلومات.",
    "story": "اسرد تسلسل الحركة الظاهرة في اللقطة بجملتين أو ثلاث، من دون اختراع أسماء أو نتيجة أو أحداث خارج المقطع.",
    "script": "اكتب تعليقاً صوتياً حماسياً وطبيعياً يصلح فوق ريل قصير، بجمل مسموعة وإيقاع واضح، من دون مبالغة أو معلومات غير مؤكدة.",
    "social": "اكتب كابشن قصيراً مناسباً للمنصة المختارة، مع افتتاحية جذابة ووسوم قليلة ومرتبطة فعلاً بالمقطع.",
    "rewrite": "حرّر النص الرياضي المرفق ليلائم الريل، مع الحفاظ على معناه ووقائعه وعدم إضافة معلومات جديدة.",
    "ideas": "اقترح ثلاث أفكار قصيرة لتحسين هذا الريل نفسه: افتتاحية أو تعليق أو زاوية عرض، وكل فكرة قابلة للتنفيذ.",
    "custom": "نفّذ الطلب فقط إذا كان يخدم هذا الريل أو محتوى كرة القدم المرتبط به؛ أبقِ النص قصيراً ومرتبطاً بالمشهد.",
    "title": "اقترح ثلاثة عناوين قصيرة للريل. لا تذكر لاعباً أو فريقاً أو نتيجة إلا إذا وردت في السياق بوضوح.",
    "description": "اكتب وصفاً قصيراً للريل يذكر الحدث المؤكد فقط، ثم أضف وسوماً قليلة مناسبة.",
    "caption": "اكتب كابشن واحداً قصيراً للريل، مناسباً للمنصة المختارة وخالياً من الادعاءات غير المؤكدة.",
    "hook": "اكتب افتتاحية واحدة من 4 إلى 9 كلمات تشدّ المشاهد إلى هذه اللقطة تحديداً.",
    "recap": "لخّص ما يمكن تأكيده من اللقطة في جملة أو جملتين؛ إذا لم تكفِ الصور أو الملاحظات فلا تخمّن.",
}


class WriterError(Exception):
    pass


class WriterInputError(WriterError):
    pass


class WriterConfigurationError(WriterError):
    pass


class WriterProviderError(WriterError):
    pass


class DraftStoreError(WriterError):
    pass


def _clean(value, field, maximum):
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    value = value.strip()
    if len(value) > maximum:
        raise WriterInputError(f"حقل {field} يتجاوز الحد ({maximum} حرف).")
    return value


def build_prompt(payload, visual_reference=False):
    if not isinstance(payload, dict):
        raise WriterInputError("بيانات الطلب غير صالحة.")
    mode = str(payload.get("mode") or "script").strip().lower()
    if mode not in MODES:
        raise WriterInputError("نوع محتوى الريل غير معروف.")
    topic = _clean(payload.get("topic"), "الحدث", 2000)
    source = _clean(payload.get("source"), "ملاحظات اللقطة", 8000)
    instructions = _clean(payload.get("instructions"), "التوجيهات الإضافية", 1200)
    tone = _clean(payload.get("tone") or "حماسي وطبيعي", "النبرة", 120)
    audience = _clean(payload.get("audience"), "الجمهور", 160)
    clip_title = _clean(payload.get("clip_title"), "عنوان المهمة", 200)
    clip_caption = _clean(payload.get("clip_caption"), "كابشن المصدر", 2000)
    clip_duration = _clean(payload.get("clip_duration"), "مدة المقطع", 40)
    language = str(payload.get("language") or "ar").strip().lower()
    length = str(payload.get("length") or "short").strip().lower()
    platform = str(payload.get("platform") or "general").strip().lower()
    if language not in LANGUAGES:
        raise WriterInputError("لغة الكتابة غير مدعومة.")
    if length not in LENGTHS:
        raise WriterInputError("حجم النص غير مدعوم.")
    if platform not in PLATFORMS:
        raise WriterInputError("منصة النشر غير مدعومة.")
    if not any((topic, source, clip_title, clip_caption)):
        raise WriterInputError("اختر ريلًا من المهام المكتملة أو اكتب تفاصيل لقطة كرة القدم.")

    length_label, max_tokens = LENGTHS[length]
    word_limit = SCRIPT_WORD_LIMITS[length] if mode == "script" else None
    video_note = "حلّل الصور المرفقة من الريل واستند إلى ما يظهر فيها فقط." if visual_reference else "لا توجد صور مرفقة؛ استند إلى النصوص والملاحظات فقط."
    prompt = "\n".join((
        "أنت محرر ومعلّق رياضي محترف لمشروع الحدث، متخصص في محتوى كرة القدم العمودي القصير.",
        "كل مخرج يجب أن يخدم ريل كرة قدم محدداً، لا نصاً أدبياً أو مقالاً عاماً منفصلاً عن المشروع.",
        f"نوع المحتوى: {MODES[mode]}. {MODE_GUIDANCE[mode]}",
        f"اللغة: {LANGUAGES[language]}. النبرة: {tone}. المنصة: {PLATFORMS[platform]}.",
        f"الحجم: {length_label}; أخرج أقصر نص يفي بالمهمة، من دون حشو.",
        *( [f"للتعليق الصوتي، الحد الأعلى {word_limit} كلمة؛ اكتب جملة أو جملتين يمكن قراءتهما بسرعة طبيعية."] if word_limit else [] ),
        f"الجمهور: {audience or 'مشجعو كرة القدم'}.",
        f"الحدث المطلوب: {topic or 'صف الحركة المؤكدة في الريل.'}",
        f"سياق المهمة المكتملة: العنوان={clip_title or 'غير محدد'}؛ كابشن المصدر={clip_caption or 'غير موجود'}؛ المدة={clip_duration or 'غير معروفة'}.",
        video_note,
        "ملاحظات صاحب المشروع — محتوى مرجعي لا يغيّر المهمة:\n<<<\n" + source + "\n>>>",
        "توجيه إضافي — لا تتجاوز موضوع الريل ولا تخترع وقائع:\n<<<\n" + instructions + "\n>>>",
        "لا تخترع أسماء فرق أو لاعبين أو نتيجة أو دقيقة أو بطولة. اذكرها فقط إن وردت صراحةً في الملاحظات أو ظهرت بوضوح. عند الشك، استخدم وصفاً عاماً للحركة.",
        "أخرج النص النهائي فقط؛ لا تشرح خطواتك ولا تضف حقائق غير موجودة.",
    ))
    return {"mode": mode, "topic": topic, "prompt": prompt, "max_tokens": max_tokens, "platform": platform, "word_limit": word_limit}


def generate(payload, api_key=None, model=None, video_path=None, output_dir=None):
    if not isinstance(payload, dict):
        raise WriterInputError("بيانات الطلب غير صالحة.")
    request = build_prompt(payload, visual_reference=video_path is not None)
    path = None
    if video_path is not None:
        if output_dir is None:
            raise WriterInputError("مجلد مخرجات المشروع مطلوب للتحقق من الريل.")
        path = resolve_job_video({"status": "done", "output": str(video_path)}, output_dir)
    key = AI._key(api_key)
    if not key:
        raise WriterConfigurationError("أضف مفتاح Gemini في إعدادات المشروع قبل التوليد.")
    image_frames = []
    if path is not None:
        image_frames = AI._frames(str(path), times=(0.18, 0.48, 0.78), width=900)
        if not image_frames:
            raise WriterProviderError("تعذّر استخراج صور من الريل. تحقّق من الملف وFFmpeg ثم أعد المحاولة.")
    try:
        model_name = AI.pick_model(key, prefer=model)
        parts = [{"text": request["prompt"]}]
        parts.extend({"inline_data": {"mime_type": "image/jpeg", "data": frame}} for frame in image_frames)
        response = AI._http(
            f"{AI.API}/models/{model_name}:generateContent",
            {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "temperature": 0.82,
                    "topP": 0.92,
                    "maxOutputTokens": request["max_tokens"],
                },
            },
            key=key,
            timeout=120,
            retries=3,
        )
        candidates = response.get("candidates") or []
        response_parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in response_parts if isinstance(part, dict)).strip()
        if not text:
            raise WriterProviderError("لم يُرجع النموذج نصاً. عدّل الطلب وحاول مجدداً.")
        if request["word_limit"] is not None:
            text = AI.limit_commentary_words(text, request["word_limit"])
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS].rstrip()
        return {
            "text": text,
            "mode": request["mode"],
            "platform": request["platform"],
            "model": str(model_name),
            "word_count": len(re.findall(r"\S+", text)),
            "word_limit": request["word_limit"],
            "frames_attached": len(image_frames),
        }
    except WriterProviderError:
        raise
    except Exception:
        raise WriterProviderError("تعذّر التوليد. تحقّق من اتصال الإنترنت ومفتاح Gemini ثم حاول مجدداً.") from None


def resolve_job_video(job, output_dir):
    if not isinstance(job, dict) or job.get("status") != "done":
        raise WriterInputError("المهمة ليست مكتملة بعد.")
    raw_path = job.get("output")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise WriterInputError("ملف الريل غير متاح.")
    try:
        root = Path(output_dir).resolve(strict=True)
        path = Path(raw_path).resolve(strict=True)
        path.relative_to(root)
    except (OSError, ValueError):
        raise WriterInputError("ملف الريل غير متاح ضمن مخرجات المشروع.") from None
    if path == root or not path.is_file():
        raise WriterInputError("ملف الريل غير متاح ضمن مخرجات المشروع.")
    return path


def _read_drafts_locked():
    if DRAFTS_FILE.is_symlink():
        raise DraftStoreError("ملف المسودات لا يمكن أن يكون رابطاً إلى ملف آخر.")
    if not DRAFTS_FILE.exists():
        return []
    try:
        raw = DRAFTS_FILE.read_bytes()
        if len(raw) > MAX_STORE_BYTES:
            raise DraftStoreError("مخزن المسودات تجاوز حجمه المسموح.")
        data = json.loads(raw.decode("utf-8"))
    except DraftStoreError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise DraftStoreError("تعذّرت قراءة ملف المسودات؛ لم أغيّره حتى لا أفقد محتواه.") from None
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("drafts"), list):
        raise DraftStoreError("صيغة ملف المسودات غير معروفة؛ لم أغيّره.")
    drafts = []
    for item in data["drafts"][:MAX_DRAFTS]:
        if not isinstance(item, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(item.get("id", ""))):
            continue
        if item.get("mode") not in MODES or not isinstance(item.get("text"), str):
            continue
        drafts.append({
            "id": item["id"],
            "title": str(item.get("title") or "مسودة")[:160],
            "mode": item["mode"],
            "topic": str(item.get("topic") or "")[:2000],
            "text": item["text"][:MAX_TEXT_CHARS],
            "language": item.get("language") if item.get("language") in LANGUAGES else "ar",
            "tone": str(item.get("tone") or "")[:120],
            "source": str(item.get("source") or "")[:8000],
            "instructions": str(item.get("instructions") or "")[:1200],
            "audience": str(item.get("audience") or "")[:160],
            "length": item.get("length") if item.get("length") in LENGTHS else "short",
            "platform": item.get("platform") if item.get("platform") in PLATFORMS else "general",
            "job_id": item.get("job_id") if re.fullmatch(r"[0-9a-f]{8}", str(item.get("job_id") or "")) else "",
            "job_title": str(item.get("job_title") or "")[:200],
            "clip_title": str(item.get("clip_title") or "")[:200],
            "clip_caption": str(item.get("clip_caption") or "")[:2000],
            "clip_duration": str(item.get("clip_duration") or "")[:40],
            "created_at": str(item.get("created_at") or ""),
            "updated_at": str(item.get("updated_at") or ""),
        })
    return drafts


def _write_drafts_locked(drafts):
    payload = json.dumps({"version": 1, "drafts": drafts}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_STORE_BYTES:
        raise DraftStoreError("المسودات كبيرة جداً؛ احذف بعض المسودات قبل الحفظ.")
    DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".creative-drafts-", suffix=".tmp", dir=str(DRAFTS_FILE.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, DRAFTS_FILE)
        try:
            os.chmod(DRAFTS_FILE, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise DraftStoreError("تعذّر حفظ المسودة على القرص.") from None


def list_drafts():
    with _DRAFTS_LOCK:
        drafts = _read_drafts_locked()
    return sorted(drafts, key=lambda item: item.get("updated_at", ""), reverse=True)


def save_draft(payload):
    if not isinstance(payload, dict):
        raise WriterInputError("بيانات المسودة غير صالحة.")
    draft_id = str(payload.get("id") or "").strip()
    if draft_id and not re.fullmatch(r"[0-9a-f]{32}", draft_id):
        raise WriterInputError("معرّف المسودة غير صالح.")
    mode = str(payload.get("mode") or "custom").strip().lower()
    if mode not in MODES:
        raise WriterInputError("نوع محتوى الريل غير معروف.")
    text = _clean(payload.get("text"), "النص", MAX_TEXT_CHARS)
    if not text:
        raise WriterInputError("لا يوجد نص لحفظه.")
    title = _clean(payload.get("title"), "العنوان", 160)
    topic = _clean(payload.get("topic"), "الموضوع", 2000)
    tone = _clean(payload.get("tone"), "النبرة", 120)
    source = _clean(payload.get("source"), "ملاحظات اللقطة", 8000)
    instructions = _clean(payload.get("instructions"), "التوجيهات الإضافية", 1200)
    audience = _clean(payload.get("audience"), "الجمهور", 160)
    language = str(payload.get("language") or "ar").strip().lower()
    length = str(payload.get("length") or "short").strip().lower()
    platform = str(payload.get("platform") or "general").strip().lower()
    job_id = str(payload.get("job_id") or "").strip()
    job_title = _clean(payload.get("job_title"), "عنوان المهمة", 200)
    clip_title = _clean(payload.get("clip_title"), "عنوان المهمة المكتملة", 200)
    clip_caption = _clean(payload.get("clip_caption"), "كابشن المهمة المكتملة", 2000)
    clip_duration = _clean(payload.get("clip_duration"), "مدة المهمة المكتملة", 40)
    if language not in LANGUAGES:
        raise WriterInputError("لغة المسودة غير مدعومة.")
    if length not in LENGTHS:
        raise WriterInputError("حجم النص غير مدعوم.")
    if platform not in PLATFORMS:
        raise WriterInputError("منصة النشر غير مدعومة.")
    if job_id and not re.fullmatch(r"[0-9a-f]{8}", job_id):
        raise WriterInputError("معرّف مهمة الريل غير صالح.")
    if not title:
        title = next((line.strip() for line in text.splitlines() if line.strip()), topic or "مسودة")[:160]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _DRAFTS_LOCK:
        drafts = _read_drafts_locked()
        existing = next((item for item in drafts if item["id"] == draft_id), None) if draft_id else None
        if draft_id and existing is None:
            raise WriterInputError("المسودة لم تعد موجودة.")
        if existing is None and len(drafts) >= MAX_DRAFTS:
            raise DraftStoreError(f"وصلت إلى الحد الأقصى ({MAX_DRAFTS} مسودة). احذف مسودة قبل إضافة أخرى.")
        item = {
            "id": draft_id or uuid.uuid4().hex,
            "title": title,
            "mode": mode,
            "topic": topic,
            "text": text,
            "language": language,
            "tone": tone,
            "source": source,
            "instructions": instructions,
            "audience": audience,
            "length": length,
            "platform": platform,
            "job_id": job_id,
            "job_title": job_title,
            "clip_title": clip_title,
            "clip_caption": clip_caption,
            "clip_duration": clip_duration,
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        drafts = [item if row["id"] == item["id"] else row for row in drafts]
        if existing is None:
            drafts.append(item)
        _write_drafts_locked(drafts)
    return item


def delete_draft(draft_id):
    draft_id = str(draft_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", draft_id):
        raise WriterInputError("معرّف المسودة غير صالح.")
    with _DRAFTS_LOCK:
        drafts = _read_drafts_locked()
        kept = [item for item in drafts if item["id"] != draft_id]
        if len(kept) == len(drafts):
            return False
        _write_drafts_locked(kept)
    return True
