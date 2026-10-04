"""publish.telegram — ingest clips from a Telegram channel + post results back.

Two modes
---------
1) RECEIVE (ingest) — no credentials needed for PUBLIC channels:
       feed = ChannelFeed("offsideahdaff")
       for post in feed.latest(limit=5):
           feed.download(post["video"], "in.mp4")
   For PRIVATE channels: create a bot, add it as channel admin, then use
   TelegramBot(token).get_updates() / a webhook, or a user client (MTProto).

2) SEND — needs a bot token (from @BotFather) and the bot added to the target
   channel with "Post Messages" permission:
       TelegramBot(token, chat_id="@mychannel").send_video("reel.mp4", caption="...")
"""
import html as _html
import json, os, re, time, urllib.parse, urllib.request
from urllib.parse import unquote

API = "https://api.telegram.org"


def _get(url, timeout=30, retries=3):
    """GET مع إعادة محاولة (شبكات المشغّلين/الكاش الوسيط تتذبذب)."""
    last = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Cache-Control": "no-cache", "Pragma": "no-cache",
                "Accept-Language": "ar,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(1.2 * (2 ** i))
    raise last


def _post_multipart(url, fields, file_field, file_path, timeout=300):
    boundary = "----reelkit" + os.urandom(12).hex()
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    name = os.path.basename(file_path)
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
                 f"filename=\"{name}\"\r\nContent-Type: video/mp4\r\n\r\n".encode())
    head = b"".join(parts)
    tail = f"\r\n--{boundary}--\r\n".encode()
    data = head + open(file_path, "rb").read() + tail
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class TelegramBot:
    def __init__(self, token, chat_id=None):
        self.token = token
        self.chat_id = chat_id

    def send_video(self, path, caption="", chat_id=None, supports_streaming=True):
        chat_id = chat_id or self.chat_id
        if not chat_id:
            raise ValueError("chat_id is required")
        caption = (caption or "")[:1024]      # حد Bot API للكابشن 1024 حرف — الزيادة ترجع 400
        res = _post_multipart(f"{API}/bot{self.token}/sendVideo",
                              {"chat_id": chat_id, "caption": caption,
                               "supports_streaming": str(supports_streaming).lower()},
                              "video", path)
        if not res.get("ok"):
            raise RuntimeError(f"telegram error: {res}")
        return res["result"]

    def send_message(self, text, chat_id=None, disable_web_page_preview=True):
        chat_id = chat_id or self.chat_id
        text = (text or "")[:4096]            # حد Bot API للنص 4096 حرف
        q = urllib.parse.urlencode({"chat_id": chat_id, "text": text,
                                    "disable_web_page_preview": str(disable_web_page_preview).lower()})
        return json.loads(_get(f"{API}/bot{self.token}/sendMessage?{q}"))

    def get_updates(self, offset=None, limit=20):
        q = {"limit": limit}
        if offset is not None:
            q["offset"] = offset
        return json.loads(_get(f"{API}/bot{self.token}/getUpdates?"
                               + urllib.parse.urlencode(q)))["result"]


class ChannelFeed:
    """قارئ القنوات العامة عبر معاينة t.me/s — بدون تسجيل ولا مفاتيح."""

    def __init__(self, channel):
        ch = channel.strip()
        ch = re.sub(r"^https?://", "", ch)
        ch = re.sub(r"^(web\.)?telegram\.org/(k|a)/#?", "", ch)
        ch = re.sub(r"^t\.me/(s/)?", "", ch).strip("/@")
        self.channel = ch
        self._single_cache = {}

    def html(self, before=None, after=None, bust=True):
        """صفحة المعاينة. bust=True يضيف كسر كاش (بعض مزوّدي الإنترنت يخزّنون الصفحة
        ساعات فيبدو أن القناة «عالقة على القديم»)."""
        url = f"https://t.me/s/{self.channel}"
        q = []
        if before:
            q.append(f"before={before}")
        if after:
            q.append(f"after={after}")
        if bust:
            q.append(f"_={int(time.time())}")
        if q:
            url += "?" + "&".join(q)
        return _get(url).decode("utf-8", "ignore")

    VIDEO_HINT = re.compile(r'tgme_widget_message_video|video_thumb|video_player')
    BAD_TEXT = re.compile(r'js-message_text|class=|&#\d|">|<[a-z/]')
    DUR_HINT = re.compile(r">\s*\d{1,2}:\d{2}\s*<")

    def _post_html(self, mid):
        """صفحة الرسالة المفردة — تكشف رابط الفيديو حتى لو المعاينة تقول not_supported
        (هذا كان سبب «عالق على فيديوهات قديمة»: تلغرام يخفي روابط الفيديوهات الكبيرة
        من صفحة القناة، فتظهر فقط القديمة/الصغيرة التي ظهر رابطها)."""
        cache = self._single_cache
        key = int(mid)
        if key in cache:
            return cache[key]
        try:
            h = _get(f"https://t.me/s/{self.channel}/{key}")
            h = h.decode("utf-8", "ignore")
        except Exception:
            h = ""
        cache[key] = h
        if len(cache) > 60:
            cache.pop(next(iter(cache)))
        return h

    def _page_map(self, h):
        """🔑 يخرُط كل فيديو/مدة **للرسالة التي يقع داخل مقطعها** في الصفحة.

        ⚠️ صفحة الرسالة المفردة تحتوي كل الرسائل المجاورة (شاهدنا 8 فيديوهات في صفحة 3017،
        أولها فيديو #3006!). أخذ «أول فيديو» كان يعالج مقطعاً آخر تماماً — علّة حقيقية.
        الحل: نرتّب مواضع data-post و<video> وننسب كل فيديو لأقرب رسالة قبله.
        """
        out = {}
        if not h:
            return out
        posts = [(m.start(), int(m.group(1))) for m in re.finditer(r'data-post="[^/]+/(\d+)"', h)]
        if not posts:
            return out
        marks = [(m.start(), m.group(0)) for m in re.finditer(
            r'<video[^>]+src="[^"]+"|<source[^>]+src="[^"]+"[^>]*>|'
            r'<time[^>]*message_video_duration[^>]*>[^<]*<', h)]
        for pos, tag in marks:
            owner = None
            for ppos, pid in posts:
                if ppos < pos:
                    owner = pid
                else:
                    break
            if owner is None:
                owner = posts[0][1]
            d = out.setdefault(owner, {"videos": [], "duration": ""})
            m = re.search(r'src="([^"]+)"', tag)
            if m:
                u = _html.unescape(m.group(1).replace("&amp;", "&"))
                if u not in d["videos"]:
                    d["videos"].append(u)
            m2 = re.search(r'>([0-9]{1,2}:[0-9]{2})<', tag)
            if m2 and not d["duration"]:
                d["duration"] = m2.group(1)
        return out

    def post_videos(self, mid):
        """روابط فيديو **هذه الرسالة فقط** من صفحة الرسالة المفردة."""
        return list((self._page_map(self._post_html(mid)).get(int(mid)) or {}).get("videos") or [])

    def post_meta(self, mid):
        """(روابط الفيديو, نص الرسالة, المدة) من صفحة الرسالة المفردة — **لهذه الرسالة فقط**."""
        h = self._post_html(mid)
        if not h:
            return [], "", ""
        mp = self._page_map(h).get(int(mid)) or {}
        vids = list(mp.get("videos") or [])
        dur = mp.get("duration") or ""
        body = h.split('tgme_widget_message_text')[-1] if 'tgme_widget_message_text' in h else ""
        if body:
            body = re.sub(r"<br\s*/?>", "\n", body.split("</div>")[0])
            body = re.sub(r"<[^>]+>", "", body)
            body = unquote(body).replace("&nbsp;", " ")
            body = re.sub(r"Media is too big[^\n]*", " ", body)
            body = re.sub(r"This media is not supported[^\n]*", " ", body)
            body = re.sub(r"\s{2,}", " ", body).strip(" .|،>")
            if self.channel:
                body = re.sub(self.channel, " ", body, flags=re.I)
        return vids, body, dur

    def _parse(self, html):
        """يستخرج الرسائل من صفحة المعاينة -> {message_id: {...}}"""
        out = {}
        for mid in sorted(set(int(m) for m in re.findall(r'data-post="[^/]+/(\d+)"', html))):
            chunk = re.split(r'data-post="[^"]+/%d"' % mid, html, maxsplit=1)  # حالة الأحرف في القناة قد تختلف عن إدخال المستخدم
            if len(chunk) < 2:
                continue
            body = chunk[1].split("tgme_widget_message_wrap")[0]
            vids = re.findall(r'<video[^>]+src="([^"]+)"', body) or \
                   re.findall(r'<source[^>]+src="([^"]+)"', body)
            text = re.sub(r"<br\s*/?>", "\n", body)
            text = re.sub(r'data-view="[^"]*"', " ", text)
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"This media is not supported[^\n]*", " ", text)
            text = re.sub(r"Media is too big[^\n]*", " ", text)
            text = re.sub(r"VIEW IN TELEGRAM|VIEW IN CHANNEL", " ", text)
            text = re.sub(r"Forwarded from[^|\n]*", " ", text)
            text = re.sub(r"[\d.,]+\s*[KMkm]?\s*views.*$", " ", text, flags=re.S)
            text = re.sub(r"[⋆✩✦✧·•]+\s*", " ", text)
            text = re.sub(r"[❤🔥👍😂🤬👏😮🤍🎯]{1,2}\s*\d+", " ", text)
            text = unquote(text).replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
            if self.channel:
                text = re.sub(self.channel, " ", text, flags=re.I)
            text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
            text = re.sub(r"\s{2,}", " ", text).strip(" .|،>")
            is_vid = bool(vids) or bool(self.VIDEO_HINT.search(body)) or \
                     bool(self.DUR_HINT.search(body))
            dt = ""
            dm = re.search(r'<time[^>]+datetime="([^"]+)"', body)
            if dm:
                dt = dm.group(1)
            out[mid] = dict(message_id=mid, text=text, video=(vids[0] if vids else None),
                            videos=vids, is_video=is_vid, date=dt,
                            url=f"https://t.me/{self.channel}/{mid}")
        return out

    def posts(self, before=None):
        return self._parse(self.html(before))

    def latest(self, limit=10, pages=2, resolve=True, progress=None):
        """أحدث الفيديوهات.

        1) لو حساب المستخدم (اللوحة → ⚙️ → تنزيل تيليجرام) مسجَّل دخول ⇒ نقرأ **كل**
           الفيديوهات مباشرة (حتى الكبيرة المخفية من الويب) — أدقّ وأشمل.
        2) وإلا: معاينة الويب + استخراج رابط كل رسالة من صفحتها (الفيديوهات الكبيرة
           لا تعطي رابطاً عاماً — تُعلَّم بـ needs_user).
        """
        try:
            from . import tguser as _tu
            if _tu.installed():
                st = _tu.status()
                if st.get("authorized"):
                    posts = _tu.latest_videos(self.channel, limit=limit)
                    if posts:
                        if progress:
                            progress(f"🔑 من حسابك: {len(posts)} فيديو (يشمل المخفي)")
                        return posts
        except Exception:
            pass
        found, before = {}, None
        need = max(1, int(limit))
        for _ in range(max(1, pages)):
            page = self.posts(before)
            if not page:
                break
            found.update(page)
            before = min(page)
            have = sum(1 for p in found.values() if p.get("is_video"))
            if have >= need + 3:            # هامش صغير يكفي
                break
        # 🔎 تأكيد الحداثة: نطلب صراحةً ما بعد أحدث id (رابط مختلف ⇒ يتجاوز أي كاش)
        try:
            newest = max(found) if found else None
            if newest:
                extra = self._parse(self.html(after=newest))
                if extra:
                    found.update(extra)
        except Exception:
            pass
        cands = [p for p in found.values() if p.get("is_video")]
        cands.sort(key=lambda p: p["message_id"], reverse=True)
        if not resolve:
            return cands[:need]
        out = []
        unresolved = []
        for p in cands:
            if len(out) >= need:
                break
            if not p.get("video"):
                if progress:
                    progress(f"🔎 أستخرج فيديو الرسالة #{p['message_id']} …")
                try:
                    vids, text, dur = self.post_meta(p["message_id"])
                except Exception:
                    vids, text, dur = [], "", ""
                if vids:
                    p = dict(p, video=vids[0], videos=vids,
                             text=(p.get("text") or text), duration=dur)
                else:
                    unresolved.append(p["message_id"])
                    p = dict(p, video=None, videos=[], needs_resolve=True)
            out.append(p)
        if unresolved:
            p_un = ", ".join(f"#{m}" for m in unresolved[:6])
            (progress or (lambda *_: None))(f"⚠️ تعذّر استخراج: {p_un}")
        return out

    def post(self, message_id):
        """رسالة واحدة بالتحديد (للقنوات العامة)."""
        mid = int(message_id)
        # 1) النص الموثوق من معاينة القناة (الصفحة المفردة تخلط نصوص المجاورات)
        base = None
        try:
            base = self.posts().get(mid) or self.posts(before=mid + 1).get(mid)
        except Exception:
            base = None
        # 2) الفيديو من صفحة الرسالة المفردة (تعمل حتى مع not_supported = سبب «العالق على القديم»)
        vids, stext, dur = [], "", ""
        try:
            vids, stext, dur = self.post_meta(mid)
        except Exception:
            pass
        if vids or (base and base.get("video")):
            text = ((base or {}).get("text") or "").strip() or stext
            allv = list(vids) or list((base or {}).get("videos") or [])
            return dict(message_id=mid, text=text, video=allv[0], videos=allv,
                        is_video=True, duration=dur,
                        url=f"https://t.me/{self.channel}/{mid}")
        p = base
        if p and p.get("video"):
            if p.get("text"):
                return p
        # احتياطي: صفحة embed فيها الفيديو حتى لو ما ظهر في المعاينة
        try:
            url = f"https://t.me/{self.channel}/{mid}?embed=1&mode=tme"
            h = _get(url).decode("utf-8", "ignore")
            vids = re.findall(r'<video[^>]+src="([^"]+)"', h) or \
                   re.findall(r'<source[^>]+src="([^"]+)"', h)
            if vids:
                return dict(message_id=mid, text=(p or {}).get("text", ""),
                            video=vids[0], url=f"https://t.me/{self.channel}/{mid}")
        except Exception:
            pass
        if p:
            return p
        raise RuntimeError(
            f"الرسالة {mid} ما فيها فيديو متاح للتنزيل العام.\n"
            f"السبب: تلغرام يخفي الفيديو الكبير (not_supported / Media is too big).\n"
            f"الحل: افتح {self.channel} في تطبيق تيليجرام → نزّل الفيديو يدوياً → "
            f"اسحبه على صندوق «مقطع جديد» في اللوحة.")

    def download(self, url, dest, progress=None):
        """Stream a t.me video URL to dest. يقبل رابطاً أو قائمة روابط (يجرّبها بالترتيب)."""
        urls = url if isinstance(url, (list, tuple)) else [url]
        last = None
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    done = 0
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        f.write(chunk); done += len(chunk)
                        if progress and total:
                            progress(done / total)
                if os.path.exists(dest) and os.path.getsize(dest) > 20000:
                    return dest
            except Exception as e:
                last = e
                continue
        if last:
            raise last
        raise RuntimeError("تعذّر تنزيل الفيديو من كل الروابط المتاحة")


def parse_telegram_ref(text):
    """'@chan' | 't.me/chan' | 'https://t.me/chan/123' -> (channel, message_id|None)"""
    t = (text or "").strip()
    t = re.sub(r"^https?://", "", t)
    t = re.sub(r"^(web\.)?telegram\.org/(k|a)/#?", "", t)
    t = re.sub(r"^t\.me/(s/)?", "", t).strip("/@")
    parts = [p for p in t.split("/") if p]
    if not parts:
        return None, None
    chan = parts[0]
    mid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return chan, mid


def fetch_post(channel_or_url, message_id=None):
    """يرجع dict الرسالة (text/video/url) سواء أعطيته قناة أو رابط رسالة محددة."""
    chan, mid = parse_telegram_ref(channel_or_url)
    if message_id:
        mid = int(message_id)
    if not chan:
        raise ValueError("رابط/قناة تيليجرام غير صالح")
    feed = ChannelFeed(chan)
    if mid:
        p = feed.post(mid)
        if p.get("video"):
            return p
        for q in feed.latest(limit=10):      # fallback: ابحث في آخر الرسائل
            if q["message_id"] == mid:
                return q
        raise RuntimeError(f"ما لقيت فيديو في الرسالة {mid}")
    posts = feed.latest(limit=1)
    if not posts:
        raise RuntimeError("ما لقيت فيديو في القناة")
    return posts[0]


def cache_probe(channel):
    """🩺 يكشف تخزين مزوّد الإنترنت: يقارن صفحة عادية بأخرى مكسورة الكاش."""
    feed = ChannelFeed(channel)
    def ids(bust):
        try:
            h = feed.html(bust=bust)
            return sorted(set(int(m) for m in re.findall(r'data-post="[^/]+/(\d+)"', h)))
        except Exception:
            return []
    plain, fresh = ids(False), ids(True)
    if not plain and not fresh:
        return {"ok": False, "error": "تعذّر الوصول لصفحة القناة"}
    p_max, f_max = (plain[-1] if plain else 0), (fresh[-1] if fresh else 0)
    return {"ok": True, "plain_newest": p_max, "bust_newest": f_max,
            "cached": bool(p_max and f_max and p_max < f_max),
            "msg": ("⚠️ مزوّد الإنترنت يخزّن الصفحة — المحرّك الآن يتجاوزه بكسر الكاش"
                    if (p_max and f_max and p_max < f_max) else
                    "✅ لا يوجد تخزين وسيط")}
