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

import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, time, timezone
from pathlib import Path, PurePosixPath

# عتبة "مقتطف قصير": 90 ثانية. فوقها لا نصف المقطع بأنه ليس بثّاً كاملاً.
SHORT_CLIP_MAX_S = 90.0

# أساس الاستخدام الذي يمكن للمستخدم توثيقه لنفسه. لا يعني اختيار أي قيمة أن
# البرنامج أصدر حكماً قانونياً؛ الغرض هو منع النشر العام بلا مراجعة واعية.
RIGHTS_BASES = {
    "own": "أملك حقوق هذا العنصر",
    "licensed": "لدي ترخيص/عقد يغطي وجهة النشر المختارة",
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


def load_rights_file(path) -> dict:
    """حمّل نموذج حقوق منفرداً لرفع CLI؛ الملف بيانات مراجعة وليس إثباتاً آلياً."""
    if not path:
        raise ValueError("أدخل ملف مراجعة الحقوق قبل رفع YouTube")
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("تعذّر قراءة ملف مراجعة الحقوق بصيغة JSON") from exc
    if not isinstance(data, dict) or "items" in data:
        raise ValueError("ملف الحقوق المنفرد يجب أن يحتوي حقول مراجعة واحدة، لا manifest")
    return data


def load_rights_manifest_entry(path, source_key) -> dict | None:
    """حمّل سجل حقوقاً مطابقاً حرفياً لمصدر واحد من manifest autopilot."""
    if not path:
        return None
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("تعذّر قراءة ملف manifest الحقوق بصيغة JSON") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        raise ValueError("ملف manifest الحقوق يحتاج كائناً باسم items")
    exact_source = str(source_key or "")
    if not exact_source or len(exact_source) > 4000:
        raise ValueError("مرجع مصدر manifest غير صالح")
    entry = items.get(exact_source)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ValueError("سجل الحقوق لهذا المصدر يجب أن يكون كائناً")
    if not isinstance(entry.get("source_reference"), str) or entry["source_reference"] != exact_source:
        raise ValueError("مرجع المصدر داخل سجل الحقوق لا يطابق مفتاح manifest")
    return dict(entry)


ASSET_MEDIA_TYPES = {"video", "audio", "music", "image", "graphic", "voiceover", "other"}
ASSET_PERMISSION_TYPES = {"own", "licensed", "permission", "public_domain"}
ASSET_REVIEW_STATUSES = {"pending_review", "reviewed", "rejected"}
ASSET_STATUSES = {
    "unverified", "pending_review", "allowed_within_declared_scope",
    "expired", "rejected", "out_of_scope", "not_yet_valid",
}
MAX_EVIDENCE_BYTES = 25 * 1024 * 1024


def _parse_utc_date(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("date must be an ISO date or timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.combine(date.fromisoformat(text), time.min, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _evidence_root(evidence_root=None):
    raw = evidence_root or os.environ.get("REEL_RIGHTS_EVIDENCE_DIR") or (
        Path(__file__).resolve().parents[1] / "rights_evidence")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[1] / root
    return root.resolve()


def _evidence_digest(relative_path, evidence_root=None):
    if not isinstance(relative_path, str) or not relative_path.strip() or len(relative_path) > 512:
        return None, "evidence_missing"
    value = relative_path.strip()
    if "\\\\" in value or "\x00" in value:
        return None, "evidence_path_invalid"
    rel = PurePosixPath(value)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        return None, "evidence_path_invalid"
    root = _evidence_root(evidence_root)
    candidate = root.joinpath(*rel.parts)
    try:
        current = root
        for part in rel.parts:
            current = current / part
            if current.is_symlink():
                return None, "evidence_path_invalid"
        resolved = candidate.resolve(strict=True)
        if root != resolved and root not in resolved.parents:
            return None, "evidence_path_invalid"
        if not resolved.is_file():
            return None, "evidence_missing"
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_EVIDENCE_BYTES:
            return None, "evidence_size_invalid"
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), ""
    except (OSError, RuntimeError):
        return None, "evidence_missing"


def evaluate_rights_assets(assets, target, *, evidence_root=None, now=None):
    """Assess operator-entered asset records and evidence files without legal conclusions."""
    try:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(timezone.utc)
    except (AttributeError, TypeError):
        moment = datetime.now(timezone.utc)
    if not isinstance(assets, list) or not assets or len(assets) > 100:
        return {"assets": [], "errors": ["أضف سجلاً منظماً للأصول مع دليل محلي لكل أصل"], "status": "unverified"}
    results = []
    errors = []
    seen_ids = set()
    for index, raw in enumerate(assets):
        if not isinstance(raw, dict):
            results.append({"asset_id": f"asset-{index + 1}", "status": "unverified", "errors": ["asset_record_invalid"]})
            errors.append(f"سجل الأصل رقم {index + 1} غير صالح")
            continue
        asset_id = raw.get("asset_id")
        if not isinstance(asset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", asset_id):
            asset_id = f"asset-{index + 1}"
            errors.append(f"معرّف الأصل رقم {index + 1} غير صالح")
        if asset_id in seen_ids:
            errors.append(f"معرّف الأصل {asset_id} مكرر")
        seen_ids.add(asset_id)
        source = raw.get("source_reference")
        media_type = raw.get("media_type")
        holder = raw.get("rights_holder")
        permission = raw.get("permission_type")
        platforms = raw.get("platforms_allowed")
        review_status = raw.get("review_status", "pending_review")
        reviewer = raw.get("reviewed_by", "")
        evidence_reference = raw.get("evidence_reference")
        reasons = []
        if not isinstance(source, str) or not source.strip() or len(source) > 4000:
            reasons.append("source_missing")
        if not isinstance(media_type, str) or media_type not in ASSET_MEDIA_TYPES:
            reasons.append("media_type_invalid")
        if not isinstance(holder, str) or not holder.strip() or len(holder) > 200:
            reasons.append("rights_holder_missing")
        if not isinstance(permission, str) or permission not in ASSET_PERMISSION_TYPES:
            reasons.append("permission_type_invalid")
        if (not isinstance(platforms, list) or not platforms
                or any(not isinstance(item, str) or item not in {"youtube", "telegram"} for item in platforms)):
            reasons.append("platform_scope_invalid")
        elif target not in platforms:
            reasons.append("platform_not_allowed")
        if not isinstance(review_status, str) or review_status not in ASSET_REVIEW_STATUSES:
            reasons.append("review_status_invalid")
        if not isinstance(evidence_reference, str) or not evidence_reference.strip() or len(evidence_reference) > 1000:
            reasons.append("evidence_reference_missing")
        digest, evidence_error = _evidence_digest(raw.get("evidence_path"), evidence_root)
        if evidence_error:
            reasons.append(evidence_error)
        supplied_digest = raw.get("evidence_sha256")
        if supplied_digest is not None:
            if not isinstance(supplied_digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", supplied_digest):
                reasons.append("evidence_hash_invalid")
            elif digest and not hmac.compare_digest(supplied_digest.lower(), digest):
                reasons.append("evidence_hash_mismatch")
        valid_from = expires_at = None
        try:
            valid_from = _parse_utc_date(raw.get("valid_from"))
            expires_at = _parse_utc_date(raw.get("expires_at"))
            if valid_from and expires_at and expires_at <= valid_from:
                reasons.append("validity_range_invalid")
        except (TypeError, ValueError):
            reasons.append("validity_date_invalid")
        reviewed_at = None
        if review_status == "reviewed":
            if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120:
                reasons.append("reviewer_missing")
            try:
                reviewed_at = _parse_utc_date(raw.get("reviewed_at"))
            except (TypeError, ValueError):
                reasons.append("reviewed_at_invalid")
            if reviewed_at is None and not reasons:
                reviewed_at = moment
        if review_status == "rejected":
            status = "rejected"
        elif expires_at and expires_at <= moment:
            status = "expired"
            reasons.append("permission_expired")
        elif valid_from and valid_from > moment:
            status = "not_yet_valid"
            reasons.append("permission_not_yet_valid")
        elif "platform_not_allowed" in reasons:
            status = "out_of_scope"
        elif reasons:
            status = "unverified"
        elif review_status != "reviewed":
            status = "pending_review"
            reasons.append("operator_review_pending")
        else:
            status = "allowed_within_declared_scope"
        if status != "allowed_within_declared_scope":
            errors.append(f"الأصل {asset_id}: {status}")
        results.append({
            "asset_id": asset_id,
            "source_reference": source.strip() if isinstance(source, str) else "",
            "media_type": media_type if isinstance(media_type, str) and media_type in ASSET_MEDIA_TYPES else "other",
            "rights_holder": holder.strip() if isinstance(holder, str) else "",
            "permission_type": permission if isinstance(permission, str) and permission in ASSET_PERMISSION_TYPES else "unknown",
            "platforms_allowed": list(dict.fromkeys(platforms)) if isinstance(platforms, list) else [],
            "valid_from": valid_from.isoformat().replace("+00:00", "Z") if valid_from else "",
            "expires_at": expires_at.isoformat().replace("+00:00", "Z") if expires_at else "",
            "evidence_reference": evidence_reference.strip() if isinstance(evidence_reference, str) else "",
            "evidence_path": raw.get("evidence_path", "") if isinstance(raw.get("evidence_path"), str) else "",
            "evidence_sha256": digest or "",
            "review_status": review_status if isinstance(review_status, str) and review_status in ASSET_REVIEW_STATUSES else "pending_review",
            "reviewed_by": reviewer.strip() if isinstance(reviewer, str) else "",
            "reviewed_at": reviewed_at.isoformat().replace("+00:00", "Z") if reviewed_at else "",
            "status": status,
            "reason_codes": reasons,
        })
    return {"assets": results, "errors": errors, "status": (
        "allowed_within_declared_scope" if results and all(item["status"] == "allowed_within_declared_scope" for item in results)
        else "rejected" if any(item["status"] == "rejected" for item in results)
        else "expired" if any(item["status"] == "expired" for item in results)
        else "pending_review" if any(item["status"] == "pending_review" for item in results)
        else "unverified")}


def _validate_publication(present=None, privacy="private", scheduled=False, target="youtube", evidence_root=None, expected_source=None) -> dict:
    p = present if isinstance(present, dict) else {}
    upload_privacy = str(privacy or "private").strip().lower()
    scheduled = scheduled is True
    privacy = "public" if scheduled else upload_privacy
    legacy_basis = p.get("rights_basis", "unknown")
    if legacy_basis is None or legacy_basis == "":
        legacy_basis = "unknown"
    legacy_evidence = p.get("evidence_reference", "")
    component_labels = {"visual": "المحتوى المرئي", "audio": "الصوت/الموسيقى"}
    components = {}
    errors = []
    for component, label in component_labels.items():
        basis_key = f"{component}_rights_basis"
        evidence_key = f"{component}_evidence_reference"
        raw_basis = p.get(basis_key) if basis_key in p else legacy_basis
        raw_evidence = p.get(evidence_key) if evidence_key in p else legacy_evidence
        if raw_basis is None or raw_basis == "":
            normalized_basis = "unknown"
        elif isinstance(raw_basis, str):
            normalized_basis = raw_basis.strip().lower() or "unknown"
        else:
            normalized_basis = ""
            errors.append(f"أساس حقوق {label} يجب أن يكون نصاً")
        if raw_evidence is None:
            raw_evidence = ""
        if not isinstance(raw_evidence, str):
            normalized_evidence = ""
            errors.append(f"مرجع دليل {label} يجب أن يكون نصاً")
        elif len(raw_evidence) > 1000:
            normalized_evidence = ""
            errors.append(f"مرجع دليل {label} يتجاوز الحد المسموح (1000 حرف)")
        else:
            normalized_evidence = _clean(raw_evidence, 1000)
        components[component] = {
            "basis": normalized_basis,
            "evidence": normalized_evidence,
        }
    visual_basis = components["visual"]["basis"]
    audio_basis = components["audio"]["basis"]
    basis = visual_basis if visual_basis == audio_basis else "mixed"
    source_value = p.get("source_reference")
    source = _clean(source_value, 1000) if isinstance(source_value, str) else ""
    evidence = _clean(legacy_evidence, 1000) if isinstance(legacy_evidence, str) else ""
    asset_mode = "assets" in p
    asset_review = evaluate_rights_assets(p.get("assets"), target, evidence_root=evidence_root) if asset_mode else {
        "assets": [], "errors": ["structured_asset_records_missing"], "status": "unverified"}
    if upload_privacy not in {"private", "unlisted", "public"}:
        errors.append("خصوصية YouTube غير صالحة" if target == "youtube" else "خصوصية الإرسال غير صالحة")
    if p.get("rights_acknowledged") is not True:
        errors.append("يجب تأكيد قراءة تنبيه حقوق النشر")
    if p.get("visual_rights_confirmed") is not True:
        errors.append("يجب مراجعة حقوق المحتوى المرئي")
    if p.get("audio_rights_confirmed") is not True:
        errors.append("يجب مراجعة حقوق الصوت/الموسيقى")
    if not source:
        errors.append("أدخل مصدر الصورة أو مرجعها للتتبّع")
    if expected_source is not None:
        expected = _clean(expected_source, 1000) if isinstance(expected_source, str) else ""
        if not expected or source != expected:
            errors.append("مرجع المصدر لا يطابق مدخلات المهمة")
    for component, label in component_labels.items():
        item = components[component]
        if item["basis"] not in RIGHTS_BASES:
            errors.append(f"اختر أساس استخدام واضحاً لـ{label}")
        if item["basis"] in {"licensed", "permission", "public_domain"} and not item["evidence"]:
            errors.append(f"أدخل مرجع الترخيص أو الإذن أو مصدر الملك العام لـ{label}")
        if privacy in {"public", "unlisted"} and item["basis"] == "unknown":
            errors.append(f"لا يمكن النشر العام أو غير المدرج دون أساس استخدام موثق لـ{label}")
    if privacy in {"public", "unlisted"}:
        if not asset_mode:
            errors.append("النشر العام يحتاج سجل أصول منظماً ودليلاً محلياً لكل أصل")
        elif asset_review["status"] != "allowed_within_declared_scope":
            errors.extend(asset_review["errors"] or ["سجل الحقوق ليس مسموحاً ضمن النطاق المُدخل"])
    elif asset_mode and asset_review["status"] == "rejected":
        errors.extend(asset_review["errors"] or ["سجل الحقوق مرفوض من المشغّل"])
    if privacy in {"public", "unlisted"}:
        if p.get("evidence_reviewed") is not True:
            errors.append("يجب مراجعة مرجع الحقوق قبل النشر")
        if p.get(f"{target}_scope_confirmed") is not True:
            label = "YouTube" if target == "youtube" else "Telegram"
            errors.append(f"أكّد أن أساس الحقوق يسمح بالنشر على {label}")
    return {
        "ok": not errors,
        "errors": errors,
        "basis": RIGHTS_BASES.get(basis, "أساسان منفصلان للصورة والصوت" if basis == "mixed" else basis),
        "visual_basis": RIGHTS_BASES.get(visual_basis, visual_basis),
        "audio_basis": RIGHTS_BASES.get(audio_basis, audio_basis),
        "visual_evidence_reference": components["visual"]["evidence"],
        "audio_evidence_reference": components["audio"]["evidence"],
        "assets": asset_review["assets"],
        "asset_status": asset_review["status"],
        "asset_errors": asset_review["errors"],
        "source_reference": source,
        "evidence_reference": evidence,
        "target": target,
        "target_scope_confirmed": p.get(f"{target}_scope_confirmed") is True,
        "privacy": privacy,
        "upload_privacy": upload_privacy,
        "scheduled": scheduled,
        "review_only": target == "youtube" and privacy == "private" and (
            asset_review["status"] != "allowed_within_declared_scope" if asset_mode
            else visual_basis == "unknown" or audio_basis == "unknown"),
        "warning": ("الرفع الخاص لا يمنع Content ID؛ راجع YouTube Studio قبل تغيير الخصوصية."
                    if target == "youtube" and privacy == "private"
                    else "اكتمال النموذج لا يثبت الملكية أو الترخيص ولا يضمن منع المطالبات."),
    }


def validate_youtube_publish(present=None, privacy="private", scheduled=False, *, evidence_root=None, expected_source=None) -> dict:
    """بوابة YouTube؛ لا تثبت الملكية أو الترخيص. الجدولة تعامل كنشر عام."""
    return _validate_publication(present, privacy=privacy, scheduled=scheduled, target="youtube",
                                 evidence_root=evidence_root, expected_source=expected_source)


def validate_public_distribution(present=None, *, evidence_root=None, expected_source=None) -> dict:
    """بوابة توزيع عام على Telegram؛ تتطلب سجلات أصول وأدلة ضمن النطاق المُدخل."""
    return _validate_publication(present, privacy="public", target="telegram",
                                 evidence_root=evidence_root, expected_source=expected_source)


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
