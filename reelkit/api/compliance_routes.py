"""مسارات الامتثال والحقوق — مستخرجة من `dashboard.py` بلا تغيير سلوك.

تُسجَّل عبر `app.include_router(...)` في `dashboard.py`. الحالة المشتركة
(`JOBS`، `_lock`، `_persist`، `AUDIT`، `_edit_profile`) تبقى في اللوحة، وتُقرأ
هنا باستيراد متأخر (`import dashboard` داخل الطلب) لتفادي الاستيراد الدائري.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter()


def _state():
    """اللوحة كمصدر وحيد للحالة والقفل — لا نسخة ثانية هنا."""
    import dashboard

    return dashboard


@router.get("/api/compliance")
def api_compliance():
    """ملخص سجل المطالبات/الإنذارات وقفل النشر الحالي. قراءة فقط."""
    from reelkit import compliance as COMPLIANCE
    return COMPLIANCE.summary()


@router.post("/api/compliance/strike")
def api_compliance_strike(payload: dict):
    """تسجيل إنذار حقوق نشره YouTube في Studio (لا يظهر في Data API)."""
    dash = _state()
    video_id = str(payload.get("video_id") or "").strip()
    if video_id and not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise HTTPException(400, "معرّف فيديو YouTube غير صالح")
    from reelkit import compliance as COMPLIANCE
    lock = COMPLIANCE.record_strike(str(payload.get("job_id") or ""), video_id,
                                    reason=str(payload.get("reason") or "")[:200],
                                    note=str(payload.get("note") or "")[:500])
    dash.AUDIT.append_event("compliance_strike", str(payload.get("job_id") or ""),
                            video_id=video_id, restriction=lock.get("level"))
    return {"ok": True, "restriction": lock}


@router.get("/api/jobs/{jid}/dossier")
def api_job_dossier(jid: str):
    """ملف وقائع Markdown للاعتراض اليدوي. لا يُرسل شيئاً."""
    dash = _state()
    with dash._lock:
        job = dash.JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        snapshot = dict(job)
        review = job.get("rights_review") if isinstance(job.get("rights_review"), dict) else {}
        publish = job.get("publish") if isinstance(job.get("publish"), dict) else {}
        youtube = publish.get("youtube") if isinstance(publish.get("youtube"), dict) else {}
        video_id = str(youtube.get("id") or "")
    from reelkit import compliance as COMPLIANCE
    doc = COMPLIANCE.build_dossier(snapshot, review, video_id)
    return PlainTextResponse(doc["markdown"], media_type="text/markdown; charset=utf-8",
                             headers={"X-Dossier-SHA256": doc["sha256"]})


@router.get("/api/jobs/{jid}/reuse-check")
def api_job_reuse_check(jid: str):
    """تقدير إعادة الاستخدام قبل النشر: ما الذي يجعل المخرج «reused content»."""
    dash = _state()
    with dash._lock:
        job = dash.JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        profile = dash._edit_profile(job)
    from reelkit import compliance as COMPLIANCE
    return {"profile": profile,
            "camera": profile.get("camera") or {},
            "tracking": profile.get("tracking") or {},
            "reuse": COMPLIANCE.assess_reuse(profile),
            "plan": COMPLIANCE.improve_plan(profile)}


@router.get("/api/channel/report")
def api_channel_report(window: int = 30):
    """نمط القناة من المهام المحفوظة: نسبة الخام وتكرار المصدر وحكم واحد."""
    dash = _state()
    with dash._lock:
        jobs = list(dash.JOBS.values())
    from reelkit import compliance as COMPLIANCE
    return COMPLIANCE.channel_report(jobs, window=max(1, min(200, int(window))))


@router.get("/api/jobs/{jid}/timeline")
def api_job_timeline(jid: str, format: str = "svg"):
    """شهادة تحويل: SVG للعين، CSV للأرشفة، JSON للفحص."""
    dash = _state()
    fmt = str(format or "svg").strip().lower()
    if fmt not in {"svg", "csv", "json"}:
        raise HTTPException(400, "الصيغة يجب أن تكون svg أو csv أو json")
    with dash._lock:
        job = dash.JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        profile = dash._edit_profile(job)
    facts = profile.get("timeline") if isinstance(profile.get("timeline"), dict) else {}
    from reelkit import compliance as COMPLIANCE
    cert = COMPLIANCE.transformation_timeline(facts)
    if fmt == "csv":
        return PlainTextResponse(cert["csv"], media_type="text/csv; charset=utf-8")
    if fmt == "json":
        return {key: value for key, value in cert.items() if key not in ("svg", "csv")}
    if not cert.get("svg"):
        raise HTTPException(422, "لا خط زمني محفوظ لهذه المهمة — أعد الرندر بتقرير التحرير")
    return PlainTextResponse(cert["svg"], media_type="image/svg+xml")


@router.get("/api/rights/calendar")
def api_rights_calendar(days: int = 45):
    """أي ترخيص ينتهي قريباً أو انتهى — من سجلات المهام المحفوظة."""
    dash = _state()
    with dash._lock:
        jobs = list(dash.JOBS.values())
    assets = []
    for job in jobs:
        review = job.get("rights_review") if isinstance(job.get("rights_review"), dict) else {}
        for asset in review.get("assets") or []:
            if isinstance(asset, dict):
                assets.append({**asset, "job_id": job.get("id"),
                               "title": job.get("title")})
    from reelkit import compliance as COMPLIANCE
    return COMPLIANCE.rights_calendar(assets, days=max(1, min(365, int(days))))


@router.get("/api/jobs/{jid}/readiness")
def api_job_readiness(jid: str):
    """ملخص جاهزية النشر: حقائق مسجّلة فقط، بلا ادّعاء اكتمال قانوني."""
    dash = _state()
    with dash._lock:
        job = dash.JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        profile = dash._edit_profile(job)
        quality = dict(job.get("quality_report") or {})
        review = job.get("rights_review") if isinstance(job.get("rights_review"), dict) else {}
    from reelkit import compliance as COMPLIANCE
    reuse = COMPLIANCE.assess_reuse(profile)
    freeze = COMPLIANCE.publish_gate()
    timeline = profile.get("timeline") if isinstance(profile.get("timeline"), dict) else {}
    cert = COMPLIANCE.transformation_timeline(timeline)
    rights_cal = COMPLIANCE.rights_calendar(
        (review.get("assets") if isinstance(review.get("assets"), list) else []), days=30)
    tracking = profile.get("tracking") if isinstance(profile.get("tracking"), dict) else {}
    miss = tracking.get("frame_miss_pct")
    coverage = tracking.get("coverage")

    checks = {
        "quality": {
            "label": "جودة المخرج",
            "ok": quality.get("ok") is True,
            "detail": "; ".join(str(i) for i in (quality.get("issues") or [])) or "أبعاد/مدة/صوت",
        },
        "tracking": {
            "label": "جودة التتبّع",
            "ok": (None if not tracking else
                   (miss is None or float(miss) <= 25.0)
                   and (coverage is None or float(coverage) >= 60.0)),
            "detail": ("لا تقرير تتبّع (رندر قديم أو تعطّل الكاشف)" if not tracking else
                       f"تغطية {float(coverage or 0):.0f}% · خروج {float(miss or 0):.0f}% · "
                       f"أطول فجوة {float(tracking.get('longest_gap') or 0):.2f}s"),
        },
        "transformation": {
            "label": "تغطية التحويل",
            "ok": (None if not cert.get("ok") else
                   bool(cert["coverage_pct"] >= 40.0 and cert["longest_gap_s"] <= 20.0)),
            "detail": ("لا خط زمني محفوظ (رندر قديم)" if not cert.get("ok") else
                       f"{cert['coverage_pct']}% من الخط الزمني · أطول فجوة {cert['longest_gap_s']:g}s"),
        },
        "reuse": {
            "label": "القيمة المضافة",
            "ok": bool(reuse["public_ok"]),
            "detail": f"{reuse['score']}/100 — " + (reuse["blockers"][0] if reuse["blockers"] else "مقبولة للنشر العام"),
        },
        "compliance_freeze": {
            "label": "قفل الإنذارات",
            "ok": bool(freeze["ok"]),
            "detail": freeze.get("error") or "لا إنذار نشط",
        },
        "rights": {
            "label": "سجل الحقوق",
            "ok": None if not review else bool(
                ((review.get("target_reviews") or {}).get("youtube") or {}).get("ok")),
            "detail": "لم يُسجَّل بعد" if not review else "مسجّل لهذه المهمة",
        },
        "rights_window": {
            "label": "صلاحية الترخيص",
            "ok": (None if not (review.get("assets") or []) else
                   not (rights_cal["expired"] or rights_cal["expiring"])),
            "detail": ("لا سجل أصول لفحص المدة" if not (review.get("assets") or []) else
                       (f"{len(rights_cal['expiring'])} ترخيص ينتهي خلال 30 يوماً"
                        if rights_cal["expiring"] else "لا انتهاء قريب")),
        },
    }
    blocking = [key for key, item in checks.items()
                if item["ok"] is False and key in ("quality", "compliance_freeze")]
    review_needed = [key for key, item in checks.items() if item["ok"] is not True]
    verdict = "blocked" if blocking else ("review" if review_needed else "ready")
    return {"verdict": verdict, "checks": checks,
            "blocking": blocking, "review": review_needed,
            "reuse": reuse, "plan": COMPLIANCE.improve_plan(profile)}


@router.post("/api/rights/evidence-backup")
def api_rights_evidence_backup(keep: int = 10, force: bool = False):
    """لقطة فورية لأدلة الحقوق. لا تُنشئ نسخة إن لم يتغيّر ملف."""
    from reelkit import backup as BACKUP
    result = BACKUP.snapshot_evidence(keep=max(1, min(50, int(keep))), force=bool(force))
    if not result.get("ok") and result.get("reason") == "evidence_dir_missing":
        raise HTTPException(404, "مجلد rights_evidence غير موجود — لا أدلة لنسخها")
    return result
