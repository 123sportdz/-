"""تحويل أخطاء النشر إلى رسائل عربية مع الخطوة التالية بدل الاستثناء الخام.

هذا الوحدة توضيحية فقط: يبقى القرار العملي في مراجعة YouTube Studio
وسجل الحقوق. لا تغطي الرسائل مطالبة ولا تمنح حق استخدام.
"""

from __future__ import annotations

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
    ("HttpError", "رفض YouTube الطلب (HTTP) — راجع تفاصيل الخطأ في السجل وأعد المحاولة."),
    ("ResumableUploadError", "فشل الرفع القابل للاستئناف — أعد المحاولة؛ الرفع يكمل من حيث توقف."),
    ("RuntimeError", "إعداد مفقود أو غير مكتمل — أكمل إعداد الحساب وأعد المحاولة."),
    ("ValueError", "قيمة إدخال غير مقبولة — صحّح الحقول في نموذج النشر وأعد المحاولة."),
)


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

