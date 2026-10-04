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
    for r in roots:
        for pat in ("client_secret*.json", "*client_secret*.json"):
            hits = sorted(glob.glob(os.path.join(r, pat)))
            if hits:
                return hits[0]
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
            flow.code_verifier = json.load(open(pending)).get("code_verifier")
        except Exception:
            pass
    flow.fetch_token(code=code)
    tp = token_path if os.path.isabs(token_path) else os.path.join(here, token_path)
    with open(tp, "w") as f:
        f.write(flow.credentials.to_json())
    return tp

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
                    "التوكن الحالي ما فيه صلاحية قراءة القناة (youtube.readonly).\n"
                    "الرفع يشتغل عادي، بس للتحقق من القناة أعد الربط: python link_youtube.py") from e
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

    def set_thumbnail(self, video_id, image_path):
        """يرفع الصورة المصغّرة (يحتاج نفس صلاحية الرفع). اختياري — لا يكسر الرفع."""
        yt = self._service()
        from googleapiclient.http import MediaFileUpload   # بعد _service حتى تظهر رسالته الواضحة لو المكتبة ناقصة
        media = MediaFileUpload(image_path, mimetype="image/jpeg")
        return yt.thumbnails().set(videoId=video_id, media_body=media).execute()

    def upload(self, path, title, description="", tags=(), privacy="public",
               category_id=CATEGORY_SPORTS, made_for_kids=False, publish_at=None,
               expected_channel_id=None, thumbnail=None):
        yt = self._service()
        from googleapiclient.http import MediaFileUpload   # بعد _service حتى تظهر رسالته الواضحة لو المكتبة ناقصة
        if expected_channel_id:
            try:
                self.verify_channel(expected_channel_id)
            except Exception as e:
                # الفحص اختياري: لا نمنع الرفع بسببه (مثلاً توكن بصلاحية الرفع فقط)
                print(f"⚠️  تعذّر التحقق من القناة قبل الرفع ({str(e)[:90]})\n"
                      f"    سأكمل الرفع على أي حال…")
        body = {
            "snippet": {"title": title[:100], "description": description[:5000],
                        "tags": list(tags)[:30], "categoryId": category_id},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids},
        }
        if publish_at:
            body["status"]["publishAt"] = publish_at     # ISO8601, implies privacyStatus=private
        media = MediaFileUpload(path, chunksize=8*1024*1024, resumable=True, mimetype="video/mp4")
        req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        resp = None
        while resp is None:
            status, resp = req.next_chunk()
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
    ap.add_argument("--tags", default=""); ap.add_argument("--privacy", default="private")
    ap.add_argument("--whoami", action="store_true", help="اعرض القناة المرتبطة بالتوكن")
    ap.add_argument("--expect-channel", help="تحقق من معرّف القناة المتوقع (UC…)")
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
    if a.upload:
        up = YouTubeUploader(a.client_secret)
        r = up.upload(a.upload, a.title or os.path.basename(a.upload), a.description,
                      [t.strip() for t in a.tags.split(",") if t.strip()], privacy=a.privacy,
                      expected_channel_id=a.expect_channel)
        print("https://youtu.be/" + str(r.get("id"))); return
    print(__doc__)


if __name__ == "__main__":
    _cli()
