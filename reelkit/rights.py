"""rights — أدوات المحتوى التحويلي والامتثال لحقوق النشر.

⚠️ نطاق صريح: هذه الوحدة **لا** تخفي المطالبات ولا تتلاعب ببصمة المحتوى (Content ID).
كل ما تفعله مشروع: تُظهر إسناد المصدر، وتوثّق عناصر العمل الأصلي/التحويلي، وتُنتج
**حزمة اعتراض** جاهزة يدعم بها المستخدم اعتراضاً حقيقياً على يوتيوب إذا اعتقد أن
عمله تحويلي (نقد/تحليل/تعليق). قرار المشروع يُترك للمدّعي/يوتيوب، والمسؤولية على
الناشر. راجع القسم القانوني في README.

الاستخدام:
    from reelkit import rights
    rights.build_package("out.mp4", source="...", caption="...", commentary="...")
    rights.checklist()          # قائمة امتثال للعرض في اللوحة
"""
from __future__ import annotations

import os
from datetime import datetime, timezone


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
     "hint": "استخدم --start/--end أو --max-dur 58.",
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


def build_package(out_path, *, source="", caption="", commentary="",
                  features=(), channel="", max_dur="", extra=None):
    """يبني ملف حزمة الاعتراض `<out>_dispute.md` ويرجّع مساره (أو None عند الفشل)."""
    try:
        base = os.path.splitext(out_path)[0]
        path = base + "_dispute.md"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        feats = [str(f) for f in (features or []) if f]
        present = {
            "own_commentary": bool(commentary),
            "source_credit": any("إسناد" in f or "source" in f.lower() for f in feats),
            "own_brand": any("هوية" in f or "brand" in f.lower() for f in feats),
            "short_clip": bool(max_dur),
            "rights_package": True,
            "no_full_match": bool(max_dur),
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
        if max_dur:
            lines.append(f"- المدة المحدودة: {max_dur}")
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

        if commentary:
            lines.append(
                "أُضيف هذا المقطع ضمن عمل **تحويلي**: تعليق صوتي/تحليل أصلي أنتجه صاحب القناة "
                "(انظر القسم 3)، مع إسناد المصدر وهوية القناة. المقتطف **قصير ومُنتقى** ويُستخدم "
                "لغرض النقد/التحليل الرياضي، لا لإعادة بثّ المباراة. أطلب مراجعة المطالبة يدوياً "
                "وضمن سياق الاستخدام العادل.")
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
