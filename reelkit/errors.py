"""تحويل أخطاء النشر إلى رسائل عربية مع الخطوة التالية بدل الاستثناء الخام.

هذا الوحدة توضيحية فقط: يبقى القرار العملي في مراجعة YouTube Studio
وسجل الحقوق. لا تغطي الرسائل مطالبة ولا تمنح حق استخدام.
"""

from __future__ import annotations

import re
from typing import Optional

_MAPPINGS = (
    ("invalid_grant", "التوكن منتهي أو سُحب الإذن — أعد ربط الحساب: python link_youtube.py"),
    ("invalid_credentials", "التوكن غير صالح — أعد ربط الحساب: python link_youtube.py"),
    ("quotaExceeded", "تجاوزت حد الرفع اليومي لـ YouTube API — جرّب غداً أو استخدم مشروعاً آخر."),
    ("dailyLimitExceeded", "تجاوزت حد الرفع اليومي لـ YouTube API — جرّب غداً."),
    ("uploadLimitExceeded", "الحساب وصل حد الفيديوهات اليومي — انتظر 24 ساعة."),
    ("liveStreamingNotUsed", "الحساب غير مؤهل للرفع بعد (قد يحتاج تحققاً) — راجع youtube.com/verify."),
    ("invalidCategoryId", "رقم التصنيف غير صالح — استخدم 17 (رياضة) أو اتركه فارغاً."),
    ("duplicateVideo", "الفيديو مرفوع مسبقاً بنفس البيانات — غيّر العنوان أو احذف النسخة القديمة."),
    ("invalidValue", "رفض YouTube قيمة في الطلب — راجع العنوان والوصف والوسوم والجدولة."),
    ("privacyStatus", "قيمة الخصوصية غير مقبولة — private أو unlisted أو public فقط."),
    ("publishAt", "موعد الجدولة مرفوض — يجب أن يكون مستقبلاً وبصيغة ISO مع خصوصية private."),
    ("FileNotFoundError", "ملف الفيديو غير موجود على القرص — تأكد أن المهمة اكتملت والملف في مكانه."),
    ("ConnectionError", "انقطع الاتصال بالشبكة أثناء الرفع — تأكد من الإنترنت وأعد المحاولة."),
    ("TimeoutError", "انتهت مهلة الاتصال بـ YouTube — تأكد من الشبكة وأعد المحاولة."),
    ("RefreshError", "فشل تجديد التوكن — أعد ربط الحساب: python link_youtube.py"),
    ("HttpError", "رفض YouTube الطلب (HTTP) — راجع العنوان والوصف والوسوم في نموذج النشر ثم أعد المحاولة."),
    ("ResumableUploadError", "فشل الرفع القابل للاستئناف — أعد المحاولة؛ الرفع يكمل من حيث توقف."),
    ("RuntimeError", "إعداد مفقود أو غير مكتمل — راجع إعدادات اللوحة (الحساب والمفاتيح) ثم أعد المحاولة."),
    ("ValueError", "قيمة إدخال غير مقبولة — صحّح الحقول في نموذج النشر وأعد المحاولة."),
)

# أنماط نصية فقط: تظهر في نص الاستثناء دون اسم النوع (لأخطاء ملتقطة كنص).
_TEXT_MAPPINGS = (
    ("timed out", "انتهت مهلة الاتصال بالشبكة — تأكد من الإنترنت ثم أعد المحاولة."),
    ("timeout", "انتهت مهلة الاتصال بالشبكة — تأكد من الإنترنت ثم أعد المحاولة."),
    ("connection", "انقطع الاتصال بالشبكة — تأكد من الإنترنت ثم أعد المحاولة."),
    ("ssl", "تعذّر الاتصال الآمن بالخدمة — تحقق من الشبكة ثم أعد المحاولة."),
    ("unauthorized", "الوصول مرفوض — أعد ربط الحساب: python link_youtube.py"),
    ("forbidden", "الخدمة رفضت الوصول — تحقق من صلاحيات الحساب والمفتاح ثم أعد المحاولة."),
    ("rate limit", "تجاوزت حد الطلبات — انتظر قليلاً ثم أعد المحاولة."),
    ("not found", "العنصر المطلوب غير موجود — حدّث القائمة ثم أعد المحاولة."),
)

_ARABIC = re.compile(r"[\u0600-\u06FF]")


def friendly_error(exc: Optional[BaseException], fallback: str = "") -> str:
    """يعيد رسالة عربية قصيرة مع الخطوة التالية، دون نص الاستثناء الخام.

    نص الاستثناء قد يحمل توكن أو مسارات خاصة؛ لا يعاد إلى العميل أبداً.
    """
    if exc is None:
        return fallback or "حدث خطأ غير معروف — أعد المحاولة."
    text = str(exc) or ""
    for needle, message in _MAPPINGS:
        if needle.lower() in text.lower() or needle in type(exc).__name__:
            return message
    return fallback or "فشل النشر — راجع سجل المهمة وأعد المحاولة."


def error_detail(exc: Optional[BaseException], limit: int = 200) -> str:
    """تفصيل تشخيصي للاستخدام من جهة الخادم فقط (السجل/التدقيق)، لا يُرسل للعميل."""
    if exc is None:
        return ""
    return f"{type(exc).__name__}: {str(exc)[:limit]}"


def friendly_text(text: Optional[str], fallback: str = "") -> str:
    """رسالة آمنة من نص خطأ ملتقط مسبقاً (سجل الأتمتة، ردود البوت).

    رسائل التطبيق العربية تمر كما هي (هي مكتوبة للعميل أصلاً)؛ أي نص
    أجنبي يُصنَّف عبر الخرائط المعروفة، وما لا يُصنَّف لا يُعاد أبداً
    حتى لا يتسرب توكن أو مسار إلى واجهة المستخدم.
    """
    raw = (text or "").strip()
    if not raw:
        return fallback or "حدث خطأ غير معروف — أعد المحاولة."
    if _ARABIC.search(raw):
        return raw[:240]
    lowered = raw.lower()
    for needle, message in _MAPPINGS:
        if needle.lower() in lowered:
            return message
    for needle, message in _TEXT_MAPPINGS:
        if needle in lowered:
            return message
    return fallback or "فشل النشر — راجع سجل المهمة ثم أعد المحاولة."

