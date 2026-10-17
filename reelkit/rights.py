"""أدوات لتسجيل معلومات الإنتاج دون ادعاء ترخيص أو أهلية قانونية.

لا تخفي هذه الوحدة المطالبات ولا تتلاعب ببصمة المحتوى (Content ID). التعليق،
والإسناد، وقِصر المقطع، والعلامة التجارية لا تمنح بحد ذاتها حق إعادة النشر ولا
تضمن استثناءً قانونياً أو قبول اعتراض. لا تعترض إلا على أساس صادق وموثّق.

الاستخدام:
    from reelkit import rights
    rights.build_package("out.mp4", source="…", commentary="…",
                         source_credit=True, own_brand=True, short_clip=True)
    rights.checklist({"own_commentary": True, …})   # قائمة امتثال
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

# عتبة "مقتطف قصير": 90 ثانية. فوقها لا نصف المقطع بأنه ليس بثّاً كاملاً.
SHORT_CLIP_MAX_S = 90.0

# أساس الاستخدام الذي يمكن للمستخدم توثيقه لنفسه. لا يعني اختيار أي قيمة أن
# البرنامج أصدر حكماً قانونياً؛ الغرض هو منع النشر العام بلا مراجعة واعية.
RIGHTS_BASES = {
    "own": "أملك حقوق الصورة والصوت",
    "licensed": "لدي ترخيص/عقد يغطي النشر على YouTube",
    "permission": "لدي إذن مكتوب من صاحب الحقوق",
    "public_domain": "المادة في الملك العام أو بترخيص يسمح بهذا الاستخدام",
    "unknown": "غير متأكد — أحتاج مراجعة قبل النشر العام",
}


# --------------------------------------------------------------- قائمة الامتثال
CHECKLIST = [
    {"id": "own_commentary",
     "label": "تعليق/تحليل أصلي مسجّل (معلومة إنتاجية)",
     "hint": "التعليق يضيف مادة أصلية لكنه لا يمنح الإذن ولا يضمن استثناءً.",
     "weight": 3},
    {"id": "source_credit",
     "label": "مصدر المحتوى محدد للتتبّع (ليس ترخيصاً)",
     "hint": "استخدم --source-credit لتسجيل المصدر؛ الإسناد وحده لا يسمح بإعادة النشر.",
     "weight": 2},
    {"id": "own_brand",
     "label": "هوية الناشر مسجّلة (لا تثبت ملكية اللقطات)",
     "hint": "--name و--url يسجلان العلامة المضافة فقط.",
     "weight": 1},
    {"id": "short_clip",
     "label": "مدة المقتطف مسجّلة",
     "hint": "استخدم --max-dur أو --start/--end؛ قِصر المقطع لا يمنح حق الاستخدام.",
     "weight": 2},
    {"id": "rights_package",
     "label": "ملف معلومات الإنتاج أُنشئ (ليس حزمة قانونية)",
     "hint": "--rights-package ينشئ ملفاً للمراجعة، ولا يثبت وجود ترخيص.",
     "weight": 2},
    {"id": "no_full_match",
     "label": "المقطع ليس تسجيلاً كاملاً للمباراة",
     "hint": "تقليل المدة لا يثبت الإذن ولا يضمن عدم المطالبة.",
     "weight": 2},
]


def checklist(present=None) -> list:
    """يرجّع قائمة الامتثال مع علامة satisfied حسب مفاتيح `present` (اختياري)."""
    present = present or {}
    out = []
    for item in CHECKLIST:
        row = dict(item)
        row["satisfied"] = bool(present.get(item["id"]))
        out.append(row)
    return out


def score(present=None) -> int:
    """مؤشر اكتمال عناصر التوثيق 0..100؛ لا يقيس الملكية أو الترخيص أو fair use."""
    present = present or {}
    total = sum(i["weight"] for i in CHECKLIST) or 1
    got = sum(i["weight"] for i in CHECKLIST if present.get(i["id"]))
    return int(round(got * 100 / total))


def validate_youtube_publish(present=None, privacy="private") -> dict:
    """تحقق تشغيلي قبل إرسال الفيديو إلى YouTube.

    هذا ليس فحص ملكية ولا رأياً قانونياً. YouTube يفحص الصوت والصورة حتى في
    الرفع الخاص؛ لذلك نطلب إقراراً واضحاً ومراجعاً للمصدر، ونمنع العام/غير
    المدرج عندما لا يوجد أساس استخدام موثق. الرفع الخاص يبقى متاحاً للمراجعة
    فقط مع تنبيه أن Content ID قد يضع مطالبة عليه.
    """
    p = present if isinstance(present, dict) else {}
    privacy = str(privacy or "private").strip().lower()
    basis = str(p.get("rights_basis") or "unknown").strip().lower()
    source = _clean(p.get("source_reference"), 1000)
    evidence = _clean(p.get("evidence_reference"), 1000)
    errors = []
    if privacy not in {"private", "unlisted", "public"}:
        errors.append("خصوصية YouTube غير صالحة")
    if p.get("rights_acknowledged") is not True:
        errors.append("يجب تأكيد قراءة تنبيه حقوق النشر")
    if p.get("visual_rights_confirmed") is not True:
        errors.append("يجب مراجعة حقوق المحتوى المرئي")
    if p.get("audio_rights_confirmed") is not True:
        errors.append("يجب مراجعة حقوق الصوت/الموسيقى")
    if not source:
        errors.append("أدخل مصدر الصورة أو مرجعها للتتبّع")
    if basis not in RIGHTS_BASES:
        errors.append("اختر أساس استخدام واضحاً")
    if basis in {"licensed", "permission"} and not evidence:
        errors.append("أدخل مرجع الترخيص أو الإذن (رابط/مسار/رقم عقد)")
    if privacy in {"public", "unlisted"} and basis in {"unknown", ""}:
        errors.append("لا يمكن النشر العام أو غير المدرج دون أساس استخدام موثق")
    if privacy in {"public", "unlisted"} and p.get("evidence_reviewed") is not True:
        errors.append("يجب تأكيد مراجعة مستند أو مرجع الحقوق قبل النشر")
    return {
        "ok": not errors,
        "errors": errors,
        "basis": RIGHTS_BASES.get(basis, basis),
        "privacy": privacy,
        "review_only": privacy == "private" and basis == "unknown",
        "warning": ("الرفع الخاص لا يمنع Content ID؛ راجع YouTube Studio قبل تغيير الخصوصية."
                    if privacy == "private" else "هذا الإقرار لا يلغي المطالبات ولا يثبت fair use."),
    }


def _clean(s, limit=4000):
    return " ".join(str(s or "").split())[:limit]


def is_short_clip(max_dur=None, duration=None) -> bool:
    """هل المقطع 'مقتطف قصير' فعلاً؟ (لا يكفي تمرير --max-dur بقيمة ضخمة)."""
    for v in (duration, max_dur):
        if v in (None, "", 0, "0", "0s"):
            continue
        try:
            sec = float(str(v).rstrip("sS").strip())
        except (TypeError, ValueError):
            continue
        if sec > 0:
            return sec <= SHORT_CLIP_MAX_S
    return False


def build_package(out_path, *, source="", caption="", commentary="",
                  features=(), channel="", duration=None, max_dur=None,
                  source_credit=None, own_brand=None, commentary_present=None,
                  rights_package=True):
    """يبني ملف معلومات إنتاج للمراجعة بجانب المخرج، ويرجّع مساره أو None عند الفشل.

    القيم المنطقية تُمرَّر صراحةً (source_credit/own_brand/commentary_present) بدل
    تخمينها من نص العناصر — تخمين النص كان يعطي نتائج مضلّلة (خطأ في التقييم).
    `short_clip` و`no_full_match` يُحسبان من `duration`/`max_dur` بعتبة حقيقية.
    """
    try:
        base = os.path.splitext(out_path)[0]
        path = base + "_production-notes.md"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        feats = [str(f) for f in (features or []) if f]

        short_clip = is_short_clip(max_dur=max_dur, duration=duration)
        has_commentary = bool(commentary) if commentary_present is None else bool(commentary_present)
        has_source_credit = bool(source) if source_credit is None else bool(source_credit)
        has_brand = None if own_brand is None else bool(own_brand)

        present = {
            "own_commentary": has_commentary,
            "source_credit": has_source_credit,
            "own_brand": bool(has_brand),
            "short_clip": short_clip,
            "rights_package": bool(rights_package),
            "no_full_match": short_clip,
        }
        sc = score(present)

        lines = []
        lines.append(f"# معلومات الإنتاج والحقوق — {os.path.basename(out_path)}\n")
        lines.append(f"_أُنشئت: {now}_\n")
        lines.append("## 1) ملخص العمل")
        if channel:
            lines.append(f"- القناة/الناشر: {channel}")
        lines.append(f"- الملف: `{os.path.basename(out_path)}`")
        if source:
            lines.append(f"- المصدر المُسنَد: {source}")
        if duration:
            lines.append(f"- مدة المخرج الفعلية: {duration}")
        elif max_dur:
            lines.append(f"- سقف المدة المطلوب: {max_dur}")
        lines.append(f"- **اكتمال عناصر التوثيق فقط: {sc}/100**\n")

        lines.append("## 2) عناصر العمل الأصلي/التحويلي المُضاف")
        if feats:
            for f in feats:
                lines.append(f"- {f}")
        else:
            lines.append("- (لم تُسجّل عناصر — فعّل التعليق والإسناد والهوية)")
        lines.append("")

        if commentary:
            lines.append("## 3) نص التعليق الأصلي (الذي أُنتجه فريق القناة)")
            lines.append("> " + _clean(commentary))
            lines.append("")

        if caption:
            lines.append("## 4) توصيف المقطع / الوصف الأصلي")
            lines.append("> " + _clean(caption, 600))
            lines.append("")

        lines.append("## 5) مراجعة الحقوق قبل أي اعتراض")
        lines.append(
            "هذا الملف يسجل عناصر الإنتاج فقط. أضف بنفسك أساسك القانوني المحدد والمستندات "
            "الداعمة، إن وُجدت؛ لا يقرر البرنامج أن الاستخدام تحويلي أو عادل ولا يقترح "
            "إرسال اعتراض. لا ترسل هذا النص كما هو.")
        lines.append("")

        lines.append("## 6) تنبيه")
        lines.append(
            "التعليق، والإسناد، والعلامة التجارية، وقِصر المقطع، والقصّ البصري لا تمنح "
            "بحد ذاتها ترخيصاً ولا تضمن إزالة مطالبة Content ID. احصل على ترخيص مكتوب "
            "يغطي النشر على YouTube والمناطق المطلوبة، أو استخدم مادة تملك حقوقها. لا "
            "تعترض إلا على أساس قانوني صادق ومدعوم؛ الاعتراض غير الصحيح قد يعرّض القناة "
            "للعقوبات. القرار للجهة المالكة/YouTube.")
        lines.append("")

        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return path
    except Exception as e:
        import sys
        # كان الابتلاع الصامت: فشل قرص/صلاحيات يمر بلا أثر حتى في السجل
        print(f"⚠️ تعذّر كتابة ملف معلومات الإنتاج: {type(e).__name__}: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--checklist":
        print(json.dumps(checklist(), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
