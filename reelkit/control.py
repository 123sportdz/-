"""control — جسر التحكّم عن بعد: بوت تيليجرام يقود مصنع الريلز من هاتفك.

الفكرة (خارج الصندوق)
---------------------
المشروع كان يُدار من جهاز واحد عبر اللوحة المحلية. هذا الجسر يفتح عليه نافذة
من أي مكان: هاتفك ← تيليجرام ← بوت ← المشروع على جهازك. يعمل بـ**Long Polling**
أي أن الجهاز يسأل تيليجرام بنفسه ⇒ **لا حاجة لفتح منافذ ولا IP ثابت ولا
port-forwarding**، ويعمل خلف أي NAT — نفس فكرة التنزيل التي يستخدمها المشروع أصلاً.

المعمارية (قلب واحد، واجهتان)
-----------------------------
    reelbot.py  ──►  reelkit/control.py  ──►  لوحة FastAPI (dashboard.py)  ──►  reel.py
      (تيليجرام)         (هذا الملف)              (المحرّك والطابور الوحيد)

البوت **ليس محرّكاً ثانياً**: هو واجهة رقيقة تستدعي واجهة اللوحة البرمجية
(نفس JOBS وPROCS وجobs.json) ⇒ لا انفصال حالة ولا تزاحم على الكرت.
إن لم تكن اللوحة مشغّلة، يشغّلها البوت تلقائياً كعملية ابنة ويتصل بها
(انظر reelbot.py --spawn).

الأمان
------
لا يستجيب البوت إلا لمحادثات القائمة البيضاء (`bot_allowed_chats` في config.json
أو `REEL_BOT_ALLOWED_CHATS`). وبدون قائمة بيضاء يرفض العمل إلا مع
`REEL_BOT_ALLOW_ANY=1` (للتجربة فقط). سبب ذلك: من يصل للبوت يقدر يشغّل مهام
على كرتك وينشر على قناتك.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org"


# ------------------------------------------------------------------ أدوات عامة
def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def outputs_dir(root=None):
    return os.path.join(root or project_root(), "outputs")


def esc(s):
    """تهريب HTML لرسائل تيليجرام (تitles/سجلات المستخدم تحوي < و & كثيراً)."""
    return _html.escape(str(s if s is not None else ""), quote=False)


def clip_text(s, limit=3900):
    s = str(s or "")
    return s if len(s) <= limit else s[: limit - 20] + "\n… (اقتُطع)"


def load_cfg(path=None):
    path = path or os.path.join(project_root(), "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def save_cfg_keys(mapping, path=None):
    """حفظ مفاتيح في config.json كتابةً ذرّية (قراءة+تعديل+كتابة تحت قفل)."""
    path = path or os.path.join(project_root(), "config.json")
    with _CFG_LOCK:
        try:
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh) or {}
        except Exception:
            cfg = {}
        cfg.update({k: v for k, v in mapping.items() if v is not None})
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return True
        except Exception:
            return False


_CFG_LOCK = threading.Lock()


def parse_allowed(raw):
    """قائمة بيضاء من نص/قائمة: '1,2 3' أو [1,2] أو '@mygroup'."""
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = re.split(r"[\s,؛;]+", str(raw or ""))
    out = []
    for it in items:
        it = str(it).strip()
        if not it:
            continue
        try:
            out.append(int(it))
        except ValueError:
            out.append(it.lower().lstrip("@"))
    return out


def allowed(chat_id, allowlist):
    """هل هذه المحادثة مسموح لها؟ يقبل معرّفات رقمية أو أسماء @قنوات (بلا حساسية لحالة الأحرف — تيليجرام نفسه كذلك)."""
    if not allowlist:
        return False
    cid = str(chat_id).strip()
    cid_n = cid.lstrip("@").lower()
    for a in allowlist:
        a_s = str(a).strip()
        if a_s == cid or a_s.lstrip("@").lower() == cid_n:
            return True
    return False


URL_RE = re.compile(r"https?://[^\s]+|(?:t|telegram)\.me/[^\s]+|@[A-Za-z0-9_]{4,}", re.I)


def extract_target(text):
    """أول رابط/معرّف قناة من نص المستخدم (أو None)."""
    m = URL_RE.search(str(text or ""))
    return m.group(0) if m else None


def is_url(text):
    return extract_target(text) is not None


def resolve_target(text, exists=None):
    """يحدّد هدف المعالجة: رابط، أو مسار ملف محلي على الجهاز، أو @قناة.

    يرجّع (kind, value): kind أحد "url"|"path"|None. وجود الملف قابل للحقن
    (لاختبار الوحدة بلا لمس القرص الحقيقي)."""
    text = str(text or "").strip().strip('"').strip("'")
    if not text:
        return None, None
    target = extract_target(text)
    if target:
        return "url", target
    exists = exists or os.path.exists
    if text and exists(text):
        return "path", text
    return None, None


def parse_command(text):
    """'/goals 3 <link>' → ('goals', ['3', '<link>']). يوحّد الصيغة العربية/الإنجليزية."""
    t = str(text or "").strip()
    if not t.startswith("/"):
        return None, []
    head, _, rest = t.partition(" ")
    cmd = head[1:].split("@", 1)[0].strip().lower()
    args = [a for a in rest.split() if a]
    return cmd, args


# ------------------------------------------------------------------ عميل اللوحة
class DashError(RuntimeError):
    pass


class Dash:
    """عميل رقيق لواجهة لوحة elhadath-reels (المحرّك الوحيد).

    لا يعيد تنفيذ أي منطق مشروع — يستدعي HTTP API نفسه الذي تستدعيه الواجهة
    العربية، فيبقى هناك مصدر حقيقة واحد (JOBS/jobs.json)."""

    def __init__(self, base_url="http://127.0.0.1:8000", token="", timeout=30):
        self.base = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = timeout

    # ---------- نقل ----------
    def _req(self, method, path, payload=None, timeout=None, raw=False, expect_json=True):
        url = self.base + path
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = (json.loads(e.read()) or {}).get("detail") or ""
            except Exception:
                pass
            raise DashError(f"HTTP {e.code}: {detail or e.reason}") from None
        except urllib.error.URLError as e:
            raise DashError(f"تعذّر الاتصال باللوحة ({e.reason}) — شغّل dashboard.py أو أضف --spawn") from None
        except Exception as e:
            raise DashError(f"{type(e).__name__}: {e}") from None
        if raw:
            return body
        if not expect_json:
            return body.decode("utf-8", "replace")
        try:
            return json.loads(body or b"{}")
        except Exception:
            raise DashError("ردّ غير متوقّع من اللوحة") from None

    def ping(self, timeout=4):
        try:
            self._req("GET", "/api/stats", timeout=timeout)
            return True
        except Exception:
            return False

    # ---------- قراءة ----------
    def jobs(self):
        return self._req("GET", "/api/jobs") or []

    def job(self, jid):
        for j in self.jobs():
            if str(j.get("id")) == str(jid):
                return j
        return None

    def stats(self):
        return self._req("GET", "/api/stats") or {}

    def queue(self):
        return self._req("GET", "/api/queue") or {}

    def space(self):
        return self._req("GET", "/api/space") or {}

    def config(self):
        return self._req("GET", "/api/config") or {}

    def settings(self):
        return self._req("GET", "/api/settings") or {}

    # ---------- كتابة ----------
    def create(self, payload):
        out = self._req("POST", "/api/jobs", payload) or {}
        if not out.get("id"):
            raise DashError("لم تُنشأ مهمة")
        return out["id"]

    def create_batch(self, items):
        return self._req("POST", "/api/jobs/batch", {"items": list(items)}) or {}

    def cancel(self, jid):
        return self._req("POST", f"/api/jobs/{urllib.parse.quote(str(jid))}/cancel", {})

    def delete(self, jid):
        return self._req("DELETE", f"/api/jobs/{urllib.parse.quote(str(jid))}")

    def rerun(self, jid):
        return self._req("POST", f"/api/jobs/{urllib.parse.quote(str(jid))}/rerun", {})

    def retry_failed(self):
        return self._req("POST", "/api/jobs/retry_failed", {})

    def clear_finished(self, keep_records=False):
        return self._req("POST", "/api/jobs/clear_finished", {"keep_records": bool(keep_records)})

    def publish(self, jid, targets, privacy=None, title=None, description="", tags=None,
                schedule=None):
        payload = {"targets": list(targets)}
        if privacy:
            payload["privacy"] = privacy
        if title:
            payload["title"] = title
        if description:
            payload["description"] = description
        if tags:
            payload["tags"] = list(tags)
        if schedule:
            payload["schedule"] = schedule
        return self._req("POST", f"/api/jobs/{urllib.parse.quote(str(jid))}/publish",
                         payload, timeout=600)

    def montage(self, ids, title="", per=12.0):
        return self._req("POST", "/api/montage",
                         {"ids": list(ids), "title": title, "per": float(per)}, timeout=900)

    def quickcheck(self, payload, timeout=1200):
        return self._req("POST", "/api/quickcheck", payload, timeout=timeout)

    def settings_set(self, mapping):
        return self._req("POST", "/api/settings", dict(mapping))

    def cleanup(self):
        return self._req("POST", "/api/cleanup", {})

    def next_slot(self):
        return self._req("GET", "/api/next_slot") or {}

    def probe_channel(self, channel):
        return self._req("GET", "/api/channel/probe?" + urllib.parse.urlencode({"channel": channel}))


# ------------------------------------------------------------------ نقل تيليجرام
class TgError(RuntimeError):
    pass


class Tg:
    """عميل Bot API خام عبر urllib — **بلا مكتبات إضافية** (مثل باقي المشروع)."""

    def __init__(self, token, api_base=API, timeout=40):
        if not token:
            raise TgError("ما فيه توكن بوت")
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _url(self, method):
        return f"{self.api_base}/bot{self.token}/{method}"

    def call(self, method, params=None, timeout=None, files=None):
        """نداء JSON. files: {field: (filename, path)} → multipart متدفق."""
        if files:
            from .publish.telegram import _post_multipart
            field, (fname, fpath) = next(iter(files.items()))
            try:
                out = _post_multipart(self._url(method), params or {}, field, fpath,
                                      timeout=timeout or 300)
            except Exception as e:
                raise TgError(str(e)) from None
            if not out.get("ok"):
                raise TgError(out.get("description") or str(out))
            return out.get("result")
        req = urllib.request.Request(
            self._url(method),
            data=json.dumps(params or {}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                out = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            desc = ""
            try:
                desc = (json.loads(e.read()) or {}).get("description") or ""
            except Exception:
                pass
            raise TgError(f"HTTP {e.code}: {desc or e.reason}") from None
        except Exception as e:
            raise TgError(f"{type(e).__name__}: {e}") from None
        if not out.get("ok"):
            raise TgError(out.get("description") or str(out))
        return out.get("result")

    # ---------- أوامر شائعة ----------
    def get_me(self):
        return self.call("getMe")

    def get_updates(self, offset=None, timeout=25, allowed=None):
        p = {"timeout": int(timeout),
             "allowed_updates": json.dumps(allowed or ["message", "callback_query"])}
        if offset is not None:
            p["offset"] = int(offset)
        return self.call("getUpdates", p, timeout=int(timeout) + 15) or []

    def send_message(self, chat_id, text, keyboard=None, preview=False):
        p = {"chat_id": chat_id, "text": clip_text(text),
             "parse_mode": "HTML", "disable_web_page_preview": (not preview)}
        if keyboard:
            p["reply_markup"] = json.dumps(keyboard, ensure_ascii=False)
        return self.call("sendMessage", p)

    def edit_message(self, chat_id, message_id, text, keyboard=None):
        p = {"chat_id": chat_id, "message_id": message_id, "text": clip_text(text),
             "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard:
            p["reply_markup"] = json.dumps(keyboard, ensure_ascii=False)
        try:
            return self.call("editMessageText", p)
        except TgError as e:
            if "not modified" in str(e).lower():
                return None
            raise

    def answer_callback(self, cid, text="", alert=False):
        try:
            return self.call("answerCallbackQuery",
                             {"callback_query_id": cid, "text": clip_text(text, 180),
                              "show_alert": bool(alert)})
        except TgError:
            return None

    def send_video(self, chat_id, path, caption="", keyboard=None, thumb=None):
        size_mb = os.path.getsize(path) / 1e6
        if size_mb > 49:
            raise TgError(f"الفيديو {size_mb:.0f}MB أكبر من حد البوت (50MB) — "
                          f"استخدم النشر بحساب المستخدم أو روابط اللوحة")
        fields = {"chat_id": chat_id, "caption": clip_text(caption, 1000),
                  "supports_streaming": "true"}
        if keyboard:
            fields["reply_markup"] = json.dumps(keyboard, ensure_ascii=False)
        return self.call("sendVideo", fields, files={"video": (os.path.basename(path), path)},
                         timeout=600)

    def send_document(self, chat_id, path, caption=""):
        fields = {"chat_id": chat_id, "caption": clip_text(caption, 1000)}
        return self.call("sendDocument", fields,
                         files={"document": (os.path.basename(path), path)}, timeout=600)

    def get_file_bytes(self, file_id, max_bytes=20 * 1024 * 1024):
        info = self.call("getFile", {"file_id": file_id}) or {}
        fpath = info.get("file_path")
        if not fpath:
            raise TgError("تعذّر الحصول على مسار الملف")
        url = f"{self.api_base}/file/bot{self.token}/{fpath}"
        with urllib.request.urlopen(url, timeout=300) as r:
            data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise TgError("الملف أكبر من 20MB — أرسل رابطاً عاماً بدلاً من الملف")
        return data


# ------------------------------------------------------------------ تنسيق الرسائل
_STATUS_AR = {"queued": "⏳ في الانتظار", "running": "⚙️ يشتغل", "done": "✅ جاهز",
              "failed": "❌ فشل", "cancelling": "⏹ يُوقَف"}
_STATUS_ICON = {"queued": "⏳", "running": "⚙️", "done": "✅", "failed": "❌",
                "cancelling": "⏹"}


def fmt_job(j, short=False):
    jid = j.get("id", "?")
    st = j.get("status", "?")
    icon = _STATUS_ICON.get(st, "•")
    label = esc(j.get("label") or j.get("input") or "")
    prog = ""
    if st == "running":
        try:
            prog = " %d%%" % int(j.get("progress") or 0)
        except (TypeError, ValueError):
            prog = ""
    line = f"{icon} <code>{esc(jid)}</code> — {_STATUS_AR.get(st, esc(st))}{prog}\n    {label}"
    if short:
        return line
    stage = j.get("stage")
    if stage:
        line += f"\n    {esc(stage)}"
    if j.get("duration"):
        line += f" · {float(j['duration']):.1f}s"
    if j.get("size"):
        line += f" · {float(j['size']) / 1e6:.1f}MB"
    if j.get("title"):
        line += f"\n    🏷️ {esc(j['title'])}"
    if j.get("quality_report") and not j["quality_report"].get("ok", True):
        line += f"\n    ⚠️ {'; '.join(esc(x) for x in j['quality_report'].get('issues', []))[:200]}"
    return line


def fmt_jobs(jobs, limit=8):
    if not jobs:
        return "📭 ما فيه مهام بعد."
    out = [f"📋 <b>المهام</b> ({len(jobs)})", ""]
    for j in jobs[:limit]:
        out.append(fmt_job(j, short=True))
    if len(jobs) > limit:
        out.append(f"\n… و{len(jobs) - limit} أخرى")
    return "\n".join(out)


def kb_jobs(jobs, limit=6):
    """أزرار صفّية لكل مهمة: تفاصيل/إيقاف/حذف."""
    rows = []
    for j in jobs[:limit]:
        jid = str(j.get("id"))
        st = j.get("status")
        row = [{"text": f"🔎 {jid}", "callback_data": f"j:{jid}"}]
        if st in ("running", "queued"):
            row.append({"text": "⏹", "callback_data": f"c:{jid}"})
        elif st == "done":
            row.append({"text": "📤", "callback_data": f"p:{jid}"})
        else:
            row.append({"text": "🔁", "callback_data": f"r:{jid}"})
        row.append({"text": "🗑", "callback_data": f"d:{jid}"})
        rows.append(row)
    rows.append([{"text": "🔄 تحديث", "callback_data": "l:"}])
    return {"inline_keyboard": rows}


def kb_job(jid, status):
    jid = str(jid)
    row = []
    if status in ("running", "queued"):
        row.append({"text": "⏹ إيقاف", "callback_data": f"c:{jid}"})
    if status == "done":
        row.append({"text": "📤 نشر يوتيوب", "callback_data": f"py:{jid}"})
        row.append({"text": "📨 نشر تيليجرام", "callback_data": f"pt:{jid}"})
        row.append({"text": "🎬 أرسل لي الريل", "callback_data": f"v:{jid}"})
    if status in ("failed", None):
        row.append({"text": "🔁 إعادة", "callback_data": f"r:{jid}"})
    kb = [row] if row else []
    kb.append([{"text": "🗑 حذف", "callback_data": f"d:{jid}"},
               {"text": "📋 المهام", "callback_data": "l:"}])
    return {"inline_keyboard": kb}


MAIN_MENU = {"inline_keyboard": [
    [{"text": "📋 المهام", "callback_data": "l:"},
     {"text": "📊 الحالة", "callback_data": "s:"}],
    [{"text": "🎯 حالة الطابور", "callback_data": "q:"},
     {"text": "💾 المساحة", "callback_data": "sp:"}],
    [{"text": "🔁 أعد الفاشلة", "callback_data": "rf:"},
     {"text": "🧹 نظّف المنتهية", "callback_data": "cl:"}],
    [{"text": "🆔 معرّفي", "callback_data": "id:"}],
]}


HELP = """🎬 <b>ريلكيت — تحكّم مصنع الريلز من هاتفك</b>

أرسل <b>رابط مقطع</b> (تيليجرام/يوتيوب/رابط مباشر) وسأشغّل المعالجة وأرسل لك الريل.
أو أرسل <b>ملف فيديو صغير (≤20MB)</b> مباشرة.

<b>الأوامر</b>
/start — القائمة
/jobs — المهام
/job &lt;id&gt; — تفاصيل مهمة
/cancel &lt;id&gt; — إيقاف
/delete &lt;id&gt; — حذف
/retry — أعد تشغيل الفاشلة
/clear — احذف المنتهية
/scout &lt;رابط&gt; — تقرير الكشّاف (بلا إنتاج)
/goals &lt;n&gt; &lt;رابط&gt; [montage] — N ريل أهداف من تسجيل طويل
/quick &lt;رابط&gt; [ثوانٍ] — رندر سريع للمعاينة
/publish &lt;id&gt; [yt|tg|both] — النشر
/montage &lt;id1,id2,…&gt; — ريل ترتيب مجمّع
/status — الطابور والإحصاءات والمساحة
/settings — الإعدادات السريعة
/set &lt;مفتاح&gt; &lt;قيمة&gt; — تغيير إعداد (quality/layout/max_dur/encoder…)
/doctor — فحص النظام
/id — معرّفي (للإعداد)
"""


def settings_summary(cfg):
    keys = ["brand_name", "quality", "layout", "max_dur", "encoder", "tracker",
            "replay", "auto_youtube", "auto_telegram", "youtube_privacy", "captions",
            "goals", "device"]
    lines = ["⚙️ <b>الإعدادات الحالية</b>", ""]
    for k in keys:
        if k in cfg:
            lines.append(f"• <code>{esc(k)}</code> = {esc(cfg.get(k))}")
    lines.append("\nللتغيير: <code>/set quality high</code>")
    return "\n".join(lines)


def build_create_payload(text, cfg=None, overrides=None, local_path=None):
    """يبني payload /api/jobs من رسالة المستخدم + إعدادات POST (بلا تنفيذ I/O).

    local_path: ملف محلي (رفعه المستخدم للبوت) — يُستعمل كمدخل بدل استخراج رابط.
    يرجّع (payload, خطأ) — أحدهما None. قابل للاختبار وحدياً.
    """
    cfg = cfg or {}
    if local_path:
        target = local_path
    else:
        target = extract_target(text)
        if not target:
            return None, "ما لقيت رابطاً في الرسالة — أرسل رابط مقطع (t.me/… أو https://…)"
    payload = {
        "input": target,
        "caption": "",
        "quality": cfg.get("automation_quality") or "auto",
        "layout": cfg.get("automation_layout") or "single",
        "subject": cfg.get("automation_subject") or "ball",
        "thumb": True,
    }
    for k in ("quality", "layout", "subject", "tracker", "replay", "framing",
              "vcenter", "zoom", "captions", "accent", "goals", "goals_montage",
              "no_scout", "transformative", "start", "end", "max_dur", "device",
              "commentary", "burst", "hook", "batch", "rate", "imgsz", "crf",
              "preset", "auto_youtube", "auto_telegram"):
        if cfg.get(k) not in (None, "", False):
            payload.setdefault(k, cfg.get(k))
    if overrides:
        payload.update({k: v for k, v in overrides.items() if v is not None})
    return payload, None


SET_MAP = {
    "quality": ("quality", str),
    "layout": ("layout", str),
    "max_dur": ("max_dur", float),
    "maxdur": ("max_dur", float),
    "tracker": ("tracker", str),
    "encoder": ("encoder", str),
    "replay": ("replay", str),
    "framing": ("framing", str),
    "vcenter": ("vcenter", str),
    "zoom": ("zoom", str),
    "captions": ("captions", str),
    "accent": ("accent", str),
    "device": ("device", str),
    "goals": ("goals", int),
    "brand": ("brand_name", str),
    "brand_name": ("brand_name", str),
    "url": ("brand_url", str),
    "privacy": ("youtube_privacy", str),
    "autoyt": ("auto_youtube", "bool"),
    "autotg": ("auto_telegram", "bool"),
    "min_transformative": ("min_transformative", float),
    "batch": ("batch", int),
}


def parse_set(args):
    """'/set quality high' → ('quality','high'). يطبّع القيم المنطقية."""
    if len(args) < 2:
        return None, None, "الصيغة: /set <مفتاح> <قيمة>"
    key = args[0].strip().lower()
    val = " ".join(args[1:]).strip()
    if key not in SET_MAP:
        return None, None, (f"مفتاح غير معروف: {key}\nالمتاح: {', '.join(sorted(SET_MAP))}")
    real, typ = SET_MAP[key]
    if typ == "bool":
        val = str(val).lower() in ("1", "on", "true", "yes", "نعم", "شغّل", "تشغيل")
    else:
        try:
            val = typ(val)
        except (TypeError, ValueError):
            return None, None, f"قيمة غير صالحة لـ{key}: {args[1]!r}"
    return real, val, None


# ------------------------------------------------------------------ الحالة المحفوظة
class BotState:
    """حالة البوت على القرص: آخر update_id والمهام المتتبَّعة لكل محادثة."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.data = {"offset": 0, "jobs": {}}
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh) or {}
            if isinstance(d, dict):
                self.data.update({k: d[k] for k in ("offset", "jobs") if k in d})
        except Exception:
            pass

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh, ensure_ascii=False)
                os.replace(tmp, self.path)
            except Exception:
                pass

    def track(self, jid, chat_id):
        with self._lock:
            rec = self.data["jobs"].setdefault(str(jid), {})
            chats = rec.setdefault("chats", [])
            if chat_id not in chats:
                chats.append(chat_id)
            rec.setdefault("last", "queued")
            rec.setdefault("notified_done", False)
            rec.setdefault("notified_fail", False)
        self.save()

    def watched(self):
        with self._lock:
            return {k: dict(v) for k, v in self.data["jobs"].items()}

    def update(self, jid, **kv):
        with self._lock:
            rec = self.data["jobs"].get(str(jid))
            if rec is not None:
                rec.update(kv)
                return True
        return False

    def forget(self, jid):
        with self._lock:
            self.data["jobs"].pop(str(jid), None)
        self.save()

    def trim(self, keep=300):
        with self._lock:
            jobs = self.data.get("jobs") or {}
            if len(jobs) > keep:
                ordered = list(jobs.items())
                self.data["jobs"] = dict(ordered[-keep:])
        self.save()
