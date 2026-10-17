#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from zo_companion import ROOT, _request, _safe_path, _settings_url

TOKEN_ENV = "ELHADATH_ZO_BRIDGE_ADMIN_TOKEN"


def _client():
    token = os.environ.get(TOKEN_ENV, "")
    if len(token) < 40:
        raise RuntimeError(f"أضف سرّ Zo باسم {TOKEN_ENV} في إعدادات Zo المتقدمة ثم أعد المحاولة.")
    url = _settings_url()
    if not url:
        raise RuntimeError("رابط الخدمة غير موجود في zo_bridge_settings.json.")
    return url, token


def _call(path, body=None):
    url, token = _client()
    return _request(url, path, token=token, body=body, timeout=45)


def _print_job(job):
    print(json.dumps(job, ensure_ascii=False, indent=2))


def _wait(job_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _call(f"/v1/admin/jobs/{job_id}").get("job")
        if not result:
            raise RuntimeError("المهمة غير موجودة؛ ربما أُلغي اقتران الجهاز.")
        if result.get("status") not in {"queued", "running"}:
            return result
        time.sleep(5)
    raise RuntimeError("انتهت مهلة الانتظار؛ قد يكون الحاسوب غير متصل أو الاختبار ما زال يعمل.")


def _save_snapshot(job):
    result = job.get("result") or {}
    files = result.get("files")
    if not isinstance(files, dict):
        raise RuntimeError("لا يحتوي ناتج المهمة على ملفات مصدر.")
    base = ROOT / ".zo-bridge-state" / "snapshots" / job["id"]
    base.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for rel, item in files.items():
        safe = _safe_path(rel)
        if safe is None or not isinstance(item, dict):
            continue
        try:
            raw = base64.b64decode(item.get("content_b64", ""), validate=True)
            text = raw.decode("utf-8")
        except Exception:
            continue
        target = base / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        manifest[rel] = {"source_sha256": item.get("sha256"),
                         "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
                         "bytes": len(raw)}
    manifest_path = base / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Snapshot: {len(manifest)} fichiers dans {base.resolve()}")
    print(f"Manifeste: {manifest_path.resolve()}")


def _show_result(job):
    result = job.get("result") or {}
    print(f"Tâche {job.get('id')} — {job.get('operation')} — {job.get('status')}")
    if job.get("operation") == "snapshot" and result.get("files"):
        _save_snapshot(job)
        return
    report = result.get("report")
    if report:
        print(report)
    if result.get("cancelled"):
        print("La tâche a été refusée sur l'ordinateur.")
    elif result.get("error"):
        print(f"Erreur: {result['error']}")
    elif job.get("operation") == "apply_file":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("exit_code") not in (None, 0):
        print(f"Code de sortie du test: {result['exit_code']}")


def main():
    parser = argparse.ArgumentParser(description="Outil d'administration du pont Zo elhadath-reels.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("revoke")
    sub.add_parser("reissue-pair")
    q = sub.add_parser("queue")
    q.add_argument("operation", choices=["doctor", "selftest", "snapshot"])
    q.add_argument("--wait", action="store_true")
    q.add_argument("--timeout", type=int, default=2400)
    r = sub.add_parser("result")
    r.add_argument("job_id")
    a = sub.add_parser("apply-file")
    a.add_argument("target_path", help="مسار نسبي داخل المشروع على الحاسوب المقترن")
    a.add_argument("content_file", help="ملف التحديث النصي الموجود في نسخة Zo")
    group = a.add_mutually_exclusive_group(required=True)
    group.add_argument("--expected-sha256", help="بصمة نسخة الحاسوب الحالية من snapshot")
    group.add_argument("--create-only", action="store_true", help="يسمح بإنشاء ملف جديد فقط إذا لم يكن موجوداً")
    a.add_argument("--wait", action="store_true")
    a.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()
    try:
        if args.command == "status":
            _print_job(_call("/v1/admin/status"))
            return 0
        if args.command == "revoke":
            _print_job(_call("/v1/admin/revoke", {}))
            return 0
        if args.command == "reissue-pair":
            response = _call("/v1/admin/pairing/reissue", {})
            print("رمز اقتران لمرة واحدة (صالح 24 ساعة):")
            print(response["pair_code"])
            return 0
        if args.command == "queue":
            queued = _call("/v1/admin/jobs", {"operation": args.operation})
            print(f"queued id={queued['id']} operation={queued['operation']}")
            if args.wait:
                _show_result(_wait(queued["id"], args.timeout))
            return 0
        if args.command == "result":
            job = _call(f"/v1/admin/jobs/{args.job_id}").get("job")
            if not job:
                raise RuntimeError("المهمة غير موجودة.")
            _show_result(job)
            return 0
        if args.command == "apply-file":
            rel = _safe_path(args.target_path)
            if rel is None or rel.suffix.lower() not in {".py", ".md", ".sh", ".bat"}:
                raise RuntimeError("الملف المستهدف غير مسموح. يسمح فقط بملفات المصدر النصية داخل المشروع.")
            source_input = Path(args.content_file)
            if not source_input.is_absolute():
                source_input = ROOT / source_input
            if source_input.is_symlink():
                raise RuntimeError("لا تقبل ملفات التحديث عبر رابط رمزي.")
            source = source_input.resolve(strict=True)
            if ROOT not in source.parents or not source.is_file():
                raise RuntimeError("ملف المحتوى يجب أن يكون ملفاً داخل نسخة المشروع في Zo.")
            source_rel = source.relative_to(ROOT).as_posix()
            if _safe_path(source_rel) is None or source.suffix.lower() not in {".py", ".md", ".sh", ".bat"}:
                raise RuntimeError("ملف المحتوى يجب أن يكون ملف مصدر نصياً مسموحاً داخل المشروع.")
            if source.stat().st_size > 512 * 1024:
                raise RuntimeError("ملف التحديث أكبر من الحد المسموح (512 KB).")
            content = source.read_text(encoding="utf-8")
            payload = {"path": rel.as_posix(), "content": content,
                       "create_only": bool(args.create_only),
                       "expected_sha256": None if args.create_only else args.expected_sha256}
            queued = _call("/v1/admin/jobs", {"operation": "apply_file", "payload": payload})
            print(f"queued id={queued['id']} target={rel.as_posix()}; سيعرض الموصل الفرق ويطلب موافقة محلية.")
            if args.wait:
                _show_result(_wait(queued["id"], args.timeout))
            return 0
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        print(f"خطأ: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
