"""publish.youtube — upload a finished reel to YouTube (Data API v3, OAuth2).

SETUP (one time)
  1) console.cloud.google.com -> create project -> enable "YouTube Data API v3"
  2) OAuth consent screen -> add yourself as a test user
  3) Credentials -> OAuth client ID -> Desktop app -> download JSON -> client_secret.json
  4) put client_secret.json next to this file (or pass the path)
  5) first upload opens a browser once -> token.json is cached afterwards

IMPORTANT GATES (why your uploads may land as *private*)
  * Unaudited API projects: videos uploaded through the API are locked to private
    until your project passes YouTube's API compliance audit.
  * Quota: an upload costs ~1600 units of the default 10,000/day -> ~6 uploads/day.
    Request a quota increase in the Cloud console for more.
  * A YouTube channel + verified account is required.

If you cannot/do not want the API path, the dashboard's "publish" step can simply
save the reel + title + description to an export folder for manual upload.
"""
import json, os

import glob

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]   # readonly = للتحقق من القناة فقط

# قوقل ينزّل الملف باسم client_secrets.json (بحرف s) — نقبل كل الأسماء الشائعة
NAMES = ("client_secret.json", "client_secrets.json", "credentials.json",
         "client_secret_1.json", "oauth_client.json")

def find_client_secret(explicit=None):
    """يبحث عن ملف اعتماد يوتيوب في الأماكن المتوقعة ويرجّع مساره أو None."""
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [here, os.path.dirname(os.path.dirname(here)), os.getcwd(),
             os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")]
    cands = []
    if explicit:
        cands.append(explicit if os.path.isabs(explicit) else os.path.join(here, explicit))
    cands += [os.path.join(r, n) for r in roots for n in NAMES]
    for c in cands:
        if c and os.path.exists(c):
            return c
    # البحث بالأنماط في مجلدات المشروع فقط — تقليب ~/Downloads بنمط عريض كان
    # يلتقط عميل OAuth لمشروع آخر ⇒ توكنات لتطبيق خاطئ وأخطاء محيّرة.
    proj_roots = {here, os.path.dirname(os.path.dirname(here)), os.getcwd()}
    for r in sorted(proj_roots):
        for pat in ("client_secret*.json", "*client_secret*.json"):
            hits = sorted(glob.glob(os.path.join(r, pat)))
            if hits:
                return hits[0]
    for r in roots:                       # الاسماء الدقيقة فقط في المجلدات الشخصية
        for n in NAMES:
            c = os.path.join(r, n)
            if os.path.exists(c):
                return c
    return None

def client_secret_help():
    return ("ما لقيت ملف اعتماد يوتيوب (client_secret.json).\n"
            "الحل الأسهل: من لوحة التحكم → ⚙️ الإعدادات → «📎 رفع ملف اعتماد يوتيوب»\n"
            "أو يدوياً: انسخ الملف الذي نزّلته من Google Cloud إلى:\n"
            "   <مجلد المشروع>\\reelkit\\publish\\client_secret.json\n"
            "(الأسماء المقبولة: client_secret.json أو client_secrets.json)")
CATEGORY_SPORTS = "17"
LOOPBACK = "http://localhost:8765/"


def _resolve_secret(client_secret=None):
    """يرجّع مسار ملف الاعتماد (يقبل أي اسم/مكان) أو يرمي رسالة واضحة."""
    cs = find_client_secret(client_secret)
    if not cs:
        raise RuntimeError(client_secret_help())
    return cs


def _flow(client_secret, redirect_uri=LOOPBACK):
    import os as _os
    _os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")   # allow http://localhost
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        raise RuntimeError("pip install google-api-python-client google-auth-oauthlib") from None
    return Flow.from_client_secrets_file(client_secret, SCOPES, redirect_uri=redirect_uri)


def auth_url(client_secret=None, redirect_uri=LOOPBACK, pending="oauth_pending.json"):
    """Step 1 of the headless login: open this URL, approve, then copy the `code`
    from the address bar (http://localhost:8765/?code=...) and run --code.
    The PKCE verifier is saved so step 2 works from another process."""
    here = os.path.dirname(os.path.abspath(__file__))
    cs = _resolve_secret(client_secret)
    flow = _flow(cs, redirect_uri)
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    with open(os.path.join(here, pending), "w") as f:
        json.dump({"redirect_uri": redirect_uri, "code_verifier": flow.code_verifier,
                   "client_secret": cs}, f)
    return url


def finish_auth(code, client_secret=None, redirect_uri=LOOPBACK,
                token_path="token.json"):
    """Step 2: exchange the code for a refresh token and cache it."""
    import re as _re
    from urllib.parse import urlparse, parse_qs, unquote
    here = os.path.dirname(os.path.abspath(__file__))
    cs = _resolve_secret(client_secret)
    if "code=" in code:
        code = parse_qs(urlparse(code).query).get("code", [code])[0]
    code = unquote(code).strip()
    flow = _flow(cs, redirect_uri)
    pending = os.path.join(here, "oauth_pending.json")
    if os.path.exists(pending):
        try:
            with open(pending, encoding="utf-8") as fh:   # كان مقبضاً يُترك مفتوحاً
                flow.code_verifier = json.load(fh).get("code_verifier")
        except Exception:
            pass
    flow.fetch_token(code=code)
    tp = token_path if os.path.isabs(token_path) else os.path.join(here, token_path)
    with open(tp, "w") as f:
        f.write(flow.credentials.to_json())
    try:
        os.chmod(tp, 0o600)                    # توكن وصول للقناة — لا يُقرأ للجميع
    except OSError:
        pass
    try:
        os.unlink(pending)                     # انتهى التدفق: code_verifier لم يعد لازماً
    except OSError:
        pass
    return tp

# حدود YouTube الرسمية (Data API v3): رفض ما يتجاوزها برسالة عربية واضحة
# بدل القطع الصامت الذي كان يخفي جزءاً من العنوان أو الوصف دون علم المستخدم.
TITLE_MAX = 100
DESCRIPTION_MAX = 5000


def validate_upload_limits(title, description=""):
    """يتحقق من حدود العنوان والوصف ويرفع ValueError برسالة إصلاح عربية.

    ملاحظة: حدّ الوسوم (30 وسمًا) يبقى مُقصّاً تلقائياً كما في السلوك السابق،
    ومجموع أحرف الوسوم > 480 يُرفض في upload() برسالة قائمة.
    """
    title = str(title or "").strip()
    if len(title) > TITLE_MAX:
        raise ValueError(
            f"العنوان أطول من حد YouTube ({TITLE_MAX} حرفاً) بطوله {len(title)} "
            "— اختصر العنوان (اقتراح تلقائي متاح من زر «اقترح عنواناً» في اللوحة)")
    description = str(description or "")
    if len(description) > DESCRIPTION_MAX:
        raise ValueError(
            f"الوصف أطول من حد YouTube ({DESCRIPTION_MAX} حرفاً) بطوله {len(description)} "
            "— اختصر الوصف أو انقل التفاصيل إلى أول تعليق على الفيديو")
    return True


class YouTubeUploader:
    def __init__(self, client_secret="client_secret.json", token_path="token.json"):
        here = os.path.dirname(os.path.abspath(__file__))
        self.client_secret = find_client_secret(client_secret)
        self.token_path = token_path if os.path.isabs(token_path) else os.path.join(here, token_path)

    def _service(self):
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError as e:
            raise RuntimeError("pip install google-api-python-client google-auth-oauthlib") from e
        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path)   # بلا فحص صلاحيات
            except Exception:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        if creds and not creds.valid and not creds.refresh_token:
            raise RuntimeError("التوكن منتهي وما فيه refresh token — أعد الربط: python link_youtube.py")
        if creds and creds.scopes and "youtube.upload" not in " ".join(creds.scopes):
            raise RuntimeError("التوكن ما فيه صلاحية الرفع (youtube.upload) — أعد الربط: python link_youtube.py")
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.client_secret:
                    raise RuntimeError(client_secret_help())
                import sys as _sys
                if not _sys.stdin.isatty():
                    raise RuntimeError(
                        "no YouTube token yet. Run the headless login:\n"
                        "  python -m reelkit.publish.youtube --auth      # open the URL, approve\n"
                        "  python -m reelkit.publish.youtube --code <CODE>")
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secret, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())
            try:
                os.chmod(self.token_path, 0o600)
            except OSError:
                pass
        return build("youtube", "v3", credentials=creds)

    def channel_info(self):
        """القناة المرتبطة بالتوكن الحالي (نتأكد أنها قناتك قبل الرفع)."""
        yt = self._service()
        try:
            r = yt.channels().list(part="snippet,statistics", mine=True).execute()
        except Exception as e:
            msg = str(e)
            if "insufficient" in msg.lower() or "403" in msg:
                raise RuntimeError(
                    "يلزم إذن youtube.readonly للتحقق من معرّف القناة. أعد الربط عبر "
                    "python link_youtube.py قبل الرفع؛ لن نرفع إلى قناة غير متحقق منها.") from e
            raise
        it = (r.get("items") or [{}])[0]
        return {"id": it.get("id"), "title": it.get("snippet", {}).get("title"),
                "subscribers": it.get("statistics", {}).get("subscriberCount"),
                "videos": it.get("statistics", {}).get("videoCount")}

    def verify_channel(self, expected_id, expected_title=None):
        info = self.channel_info()
        ok = (info.get("id") == expected_id)
        if not ok:
            raise RuntimeError(
                f"التوكن مرتبط بقناة مختلفة!\n  المتوقع: {expected_title or ''} ({expected_id})\n"
                f"  الفعلي : {info.get('title')} ({info.get('id')})\n"
                "لازم توافق بنفس حساب قوقل المالك للقناة (أو تختار القناة الصحيحة في شاشة الموافقة).")
        return info

    def video_status(self, video_id):
        """Return owner-visible processing, rejection, privacy, and regional limits."""
        import re
        video_id = str(video_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError("معرّف فيديو YouTube غير صالح")
        yt = self._service()
        response = yt.videos().list(
            part="snippet,status,processingDetails,contentDetails", id=video_id
        ).execute()
        items = response.get("items") or []
        if not items:
            raise RuntimeError("لم يُعثر على الفيديو أو لا يمكن لهذا الحساب قراءته")
        item = items[0]
        status = item.get("status") or {}
        processing = item.get("processingDetails") or {}
        content = item.get("contentDetails") or {}
        restriction = content.get("regionRestriction") or {}
        return {
            "id": item.get("id", video_id),
            "title": (item.get("snippet") or {}).get("title"),
            "upload_status": status.get("uploadStatus"),
            "privacy_status": status.get("privacyStatus"),
            "failure_reason": status.get("failureReason"),
            "rejection_reason": status.get("rejectionReason"),
            "processing_status": processing.get("processingStatus"),
            "processing_failure_reason": processing.get("processingFailureReason"),
            "region_restriction": {
                "allowed": restriction.get("allowed"),
                "blocked": restriction.get("blocked"),
            },
        }

    def set_thumbnail(self, video_id, image_path):
        """يرفع الصورة المصغّرة (يحتاج نفس صلاحية الرفع). اختياري — لا يكسر الرفع."""
        yt = self._service()
        from googleapiclient.http import MediaFileUpload   # بعد _service حتى تظهر رسالته الواضحة لو المكتبة ناقصة
        media = MediaFileUpload(image_path, mimetype="image/jpeg")
        return yt.thumbnails().set(videoId=video_id, media_body=media).execute()

    def upload(self, path, title, description="", tags=(), privacy="private",
               category_id=CATEGORY_SPORTS, made_for_kids=False, publish_at=None,
               expected_channel_id=None, thumbnail=None, contains_synthetic_media=False,
               rights=None, progress_callback=None):
        path = os.fspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"ملف الفيديو غير موجود: {path}")
        title = str(title or "").strip()
        if not title:
            raise ValueError("عنوان فيديو YouTube مطلوب")
        validate_upload_limits(title, description)   # فشل سريع قبل أي بوابة أو مصادقة
        if privacy not in {"private", "unlisted", "public"}:
            raise ValueError("الخصوصية يجب أن تكون private أو unlisted أو public")
        if publish_at:
            from reelkit.schedule import validate_publish_at
            validate_publish_at(publish_at)
        from reelkit import rights as RIGHTS
        gate = RIGHTS.validate_youtube_publish(rights, privacy=privacy, scheduled=bool(publish_at))
        if not gate["ok"]:
            raise ValueError("رفض الرفع بسبب بوابة الحقوق: " + "؛ ".join(gate["errors"]))
        if not isinstance(rights, dict):
            rights = {}
        contains_synthetic_media = (contains_synthetic_media is True or
                                    rights.get("contains_synthetic_media") is True)
        description = str(description or "")
        tags = [str(tag).strip() for tag in (tags or ()) if str(tag).strip()]
        if sum(len(tag) for tag in tags) > 480:
            raise ValueError("مجموع أحرف الوسوم يتجاوز حد YouTube (500 حرف) — قلّل عدد الوسوم أو أطوالها")
        yt = self._service()
        from googleapiclient.http import MediaFileUpload   # بعد _service حتى تظهر رسالته الواضحة لو المكتبة ناقصة
        if expected_channel_id:
            self.verify_channel(expected_channel_id)
        body = {
            "snippet": {"title": title, "description": description,
                        "tags": list(tags)[:30], "categoryId": category_id},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids,
                        # YouTube requires this disclosure for realistic altered/synthetic
                        # content. Normal crops, subtitles and color grading do not imply it.
                        "containsSyntheticMedia": bool(contains_synthetic_media)},
        }
        if publish_at:
            # يوتيوب يرفض publishAt إلا مع خصوصية private ⇒ HTTP 400 مضمون لو public
            if privacy != "private":
                print("ℹ️  الجدولة تتطلب خصوصية private — ضُبطت تلقائياً "
                      "(سيتحول لعام في موعد النشر)")
                body["status"]["privacyStatus"] = "private"
            body["status"]["publishAt"] = publish_at     # ISO8601, implies privacyStatus=private
        media = MediaFileUpload(path, chunksize=8*1024*1024, resumable=True, mimetype="video/mp4")
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        # رفع قابل للاستئناف بإعادة محاولة أسّية: أي خطأ عابر كان يجهض الرفع كله
        # حتى لو قطع 99% (ResumableUploadError / انقطاع شبكة).
        import time as _time
        from googleapiclient.errors import HttpError, ResumableUploadError
        resp = None
        attempt = 0
        while resp is None:
            try:
                status, resp = req.next_chunk()
                if status is not None and callable(progress_callback):
                    try:
                        percent = int(round(float(status.progress()) * 100))
                        uploaded = getattr(status, "resumable_progress", None)
                        total = getattr(status, "total_size", None)
                        if uploaded is not None:
                            uploaded = int(uploaded)
                        if total is not None:
                            total = int(total)
                        progress_callback(max(0, min(100, percent)), uploaded, total)
                    except Exception:
                        pass
                attempt = 0
            except (ResumableUploadError, ConnectionError, TimeoutError, OSError) as e:
                # HttpError 5xx تأتي كـResumableUploadError؛ 4xx (غير 408) لا تُعاد
                if isinstance(e, HttpError) and e.resp is not None and \
                        400 <= e.resp.status < 500 and e.resp.status != 408:
                    raise
                attempt += 1
                if attempt > 5:
                    raise
                wait = min(60, 4 * (2 ** attempt))
                print(f"⚠️  انقطع الرفع ({type(e).__name__}) — إعادة {attempt}/5 بعد {wait}s "
                      f"(يستأنف من حيث توقف)")
                _time.sleep(wait)
        # 🖼️ الصورة المصغّرة: تُرفع تلقائياً لو موجودة بجانب الفيديو (نفس الاسم + _thumb.jpg)
        thumb = thumbnail
        if not thumb:
            base = os.path.splitext(path)[0]
            for ext in (".jpg", ".jpeg", ".png"):
                if os.path.exists(base + "_thumb" + ext):
                    thumb = base + "_thumb" + ext
                    break
        if thumb and os.path.exists(thumb):
            try:
                self.set_thumbnail(resp.get("id"), thumb)
                print(f"🖼️  رُفعت الصورة المصغّرة: {os.path.basename(thumb)}")
            except Exception as e:
                print(f"⚠️  تعذّر رفع الصورة المصغّرة ({str(e)[:110]})")
        return resp


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="YouTube upload / OAuth helper")
    ap.add_argument("--auth", action="store_true", help="print the consent URL")
    ap.add_argument("--code", help="code (or full redirect URL) copied after approving")
    ap.add_argument("--upload", help="video file to upload")
    ap.add_argument("--title", default=""); ap.add_argument("--description", default="")
    ap.add_argument("--tags", default=""); ap.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    ap.add_argument("--whoami", action="store_true", help="اعرض القناة المرتبطة بالتوكن")
    ap.add_argument("--video-status", metavar="VIDEO_ID", help="افحص حالة المعالجة والرفض والقيود الجغرافية")
    ap.add_argument("--expect-channel", help="تحقق من معرّف القناة المتوقع (UC…)")
    ap.add_argument("--rights-file", help="ملف JSON بنموذج الحقوق لهذا الفيديو؛ لا يثبت الملكية")
    ap.add_argument("--client-secret", default="client_secret.json")
    a = ap.parse_args()
    if a.auth:
        print(auth_url(a.client_secret)); return
    if a.code:
        print("token saved:", finish_auth(a.code, a.client_secret)); return
    if a.whoami:
        up = YouTubeUploader(a.client_secret)
        info = up.verify_channel(a.expect_channel) if a.expect_channel else up.channel_info()
        print(json.dumps(info, ensure_ascii=False, indent=1)); return
    if a.video_status:
        up = YouTubeUploader(a.client_secret)
        print(json.dumps(up.video_status(a.video_status), ensure_ascii=False, indent=2)); return
    if a.upload:
        from reelkit import rights as RIGHTS
        rights = RIGHTS.load_rights_file(a.rights_file)
        up = YouTubeUploader(a.client_secret)
        r = up.upload(a.upload, a.title or os.path.basename(a.upload), a.description,
                      [t.strip() for t in a.tags.split(",") if t.strip()], privacy=a.privacy,
                      expected_channel_id=a.expect_channel, rights=rights)
        print("https://youtu.be/" + str(r.get("id"))); return
    print(__doc__)


if __name__ == "__main__":
    _cli()
