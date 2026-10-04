"""rights — أدوات المحتوى التحويلي والامتثال لحقوق النشر.

⚠️ نطاق صريح: هذه الوحدة **لا** تخفي المطالبات ولا تتلاعب ببصمة المحتوى (Content ID).
كل ما تفعله مشروع: تُظهر إسناد المصدر، وتوثّق عناصر العمل الأصلي/التحويلي، وتُنتج
**حزمة اعتراض** جاهزة يدعم بها المستخدم اعتراضاً حقيقياً على يوتيوب إذا اعتقد أن
عمله تحويلي (نقد/تحليل/تعليق). قرار المشروع يُترك للمدّعي/يوتيوب، والمسؤولية على
الناشر. راجع القسم القانوني في README.

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


# --------------------------------------------------------------- قائمة الامتثال
CHECKLIST = [
    {"id": "own_commentary",
     "label": "تعليق/تحليل أصلي مسموع (ليس صوت البث)",
     "hint": "شغّل --commentary (يولّد تعليقاً عربياً بصوتك) — هذا أقوى عنصر تحويلي.",
     "weight": 3},
    {"id": "source_credit",
     "label": "إسناد المصدر ظاهر في الفيديو",
     "hint": "استخدم --source-credit \"المصدر: …\" فيُرسم سطر إسناد.",
     "weight": 2},
    {"id": "own_brand",
     "label": "هوية/علامة قناتك ظاهرة",
     "hint": "--name و--url (شريط الهوية).",
     "weight": 1},
    {"id": "short_clip",
     "label": "مقتطف قصير (لا يُنشر البث كاملاً)",
     "hint": "استخدم --max-dur 58 أو --start/--end.",
     "weight": 2},
    {"id": "rights_package",
     "label": "حزمة الاعتراض موثّقة (ملف _dispute.md)",
     "hint": "--rights-package يولّد الملف بجانب الريل.",
     "weight": 2},
    {"id": "no_full_match",
     "label": "المقطع ليس بثّاً كاملاً لمباراة",
     "hint": "لا تنشر تسجيلات بث كاملة — مطالبة UEFA تغطّي البث كاملاً.",
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
    """درجة جاهزية تحوّلية 0..100 (موزونة). ليست ضماناً قانونياً — إرشاد فقط."""
    present = present or {}
    total = sum(i["weight"] for i in CHECKLIST) or 1
    got = sum(i["weight"] for i in CHECKLIST if present.get(i["id"]))
    return int(round(got * 100 / total))


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
    """يبني ملف حزمة الاعتراض `<out>_dispute.md` ويرجّع مساره (أو None عند الفشل).

    القيم المنطقية تُمرَّر صراحةً (source_credit/own_brand/commentary_present) بدل
    تخمينها من نص العناصر — تخمين النص كان يعطي نتائج مضلّلة (خطأ في التقييم).
    `short_clip` و`no_full_match` يُحسبان من `duration`/`max_dur` بعتبة حقيقية.
    """
    try:
        base = os.path.splitext(out_path)[0]
        path = base + "_dispute.md"
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
        lines.append(f"# 🛡️ حزمة اعتراض على مطالبة حقوق — {os.path.basename(out_path)}\n")
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
        lines.append(f"- **درجة الجاهزية التحوّلية (إرشادية): {sc}/100**\n")

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

        lines.append("## 5) أساس الاعتراض المقترح (للصياغة النهائية)")
        if has_commentary:
            base_txt = ("أُضيف هذا المقطع ضمن عمل **تحويلي**: تعليق صوتي/تحليل أصلي أنتجه "
                        "صاحب القناة (انظر القسم 3)، مع إسناد المصدر وهوية القناة.")
            if short_clip:
                base_txt += (" المقتطف **قصير ومُنتقى** ويُستخدم لغرض النقد/التحليل الرياضي، "
                             "لا لإعادة بثّ المباراة.")
            else:
                base_txt += (" ⚠️ لكن المقطع **غير مُقتَطع** (طوله كامل) — إن كان بثّاً "
                             "طويلاً فهذا يُضعف الحجّة كثيراً؛ اقتطعه إلى مقتطف قصير.")
            base_txt += " أطلب مراجعة المطالبة يدوياً وضمن سياق الاستخدام العادل."
            lines.append(base_txt)
        else:
            lines.append(
                "⚠️ لا يوجد تعليق أصلي مسجّل لهذا الملف. الاعتراض بلا عمل تحويلي واضح "
                "ضعيف قانونياً وقد يُرفض (وربما يُحتسب اعتراضاً كاذباً). أنصح بتفعيل "
                "`--commentary` وإعادة الإنتاج قبل الاعتراض.")
        lines.append("")

        lines.append("## 6) تنبيه")
        lines.append(
            "هذه الحزمة **توثيق تقني** لما أضفته القناة، وليست رأياً قانونياً ولا ضماناً "
            "لقبول الاعتراض. يوتيوب/المدّعي يقرّر النتيجة. لا تستخدم هذه الحزمة لادّعاء "
            "ملكية لا تملكها — الاعتراض الكاذب قد يعرّض القناة للعقوبات. لا تعِد نشر بثّ "
            "كامل مهما كانت التعديلات.")
        lines.append("")

        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return path
    except Exception:
        return None


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--checklist":
        print(json.dumps(checklist(), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
