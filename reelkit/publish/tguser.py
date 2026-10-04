"""tguser — تنزيل فيديوهات تيليجرام الكاملة بحساب المستخدم (MTProto / Telethon).

**المشكلة التي يحلّها:** تلغرام لا يعطي رابطاً عاماً للفيديوهات الكبيرة
(`tgme_widget_message_video_player not_supported` / «Media is too big») — فروابط
معاينة الويب تعطي فقط الفيديوهات الصغيرة. بحسابك (api_id/api_hash + كود مرّة واحدة)
نقدر ننزّل **أي** فيديو من **أي** قناة عامة، ونعرض كل المقاطع حتى المخفية.

الاستخدام (من اللوحة أو من بايثون):
    tguser.send_code(api_id, api_hash, "+213...")   # يرسل الكود لتطبيق تيليجرام
    tguser.sign_in("12345")                          # يحفظ الجلسة في config.json
    tguser.status()                                  # {installed, authorized, me}
    tguser.download_message("OffsideOffside1", 3019, "clip.mp4")
    tguser.latest_videos("OffsideOffside1", limit=20)

⚠️ لا يحتاج أي مفاتيح مالية: api_id/api_hash مجانيان من my.telegram.org (دقيقة واحدة).
"""
import asyncio
import concurrent.futures
import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG_PATH = os.path.join(ROOT, "config.json")

_pending = {}          # حالة تسجيل الدخول الجارية (client + phone + hash)
_lock = threading.Lock()


# ------------------------------------------------------------------ أدوات
def installed():
    try:
        import telethon  # noqa
        return True
    except Exception:
        return False


def _cfg():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_cfg(**kv):
    c = _cfg()
    c.update({k: v for k, v in kv.items() if v is not None})
    try:
        # 💾 كتابة ذرّية (tmp + os.replace) — كانت الكتابة المباشرة تتسابق مع
        # save_cfg في اللوحة فيضيع tg_session (نفس علّة v1.36 بصيغة أخرى)
        tmp = CFG_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CFG_PATH)
        return True
    except Exception:
        return False


def creds():
    c = _cfg()
    return (c.get("tg_api_id") or os.environ.get("TG_API_ID"),
            c.get("tg_api_hash") or os.environ.get("TG_API_HASH"),
            c.get("tg_phone") or os.environ.get("TG_PHONE"),
            c.get("tg_session") or os.environ.get("TG_SESSION"))


# أخطاء تلغرام → رسائل عربية واضحة مع الحل
def explain_error(e):
    n = type(e).__name__
    msg = str(e)
    table = {
        "ApiIdInvalidError": "api_id/api_hash غير صحيحين — انسخهما من my.telegram.org بلا مسافات",
        "PhoneNumberInvalidError": "رقم الهاتف غير صحيح — اكتبه بالصيغة الدولية مثل +213xxxxxxxxx",
        "PhoneNumberBannedError": "رقم الهاتف محجوب في تلغرام",
        "PhoneNumberUnoccupiedError": "هذا الرقم ما فيه حساب تيليجرام — أنشئ حساباً أولاً",
        "PhoneCodeInvalidError": "الكود غلط — تأكد من الأرقام (خمسة أرقام عادةً)",
        "PhoneCodeExpiredError": "انتهت صلاحية الكود — اضغط «أرسل الكود» من جديد",
        "SessionPasswordNeededError": "حسابك فيه تحقّق بخطوتين — اكتب كلمة مرور تيليجرام",
        "PasswordHashInvalidError": "كلمة مرور تيليجرام غلط",
        "AuthRestartError": "أعد العملية من البداية (أرسل الكود من جديد)",
        "SendCodeUnavailableError": "تلغرام رفض إرسال الكود حالياً — جرّب بعد قليل",
        "FloodWaitError": None,
        "ConnectionError": "تعذّر الاتصال بسيرفرات تلغرام (MTProto) — مزوّد الإنترنت قد يحجبه: "
                           "جرّب VPN أو بروكسي في نفس القسم",
        "TimeoutError": "انتهت مهلة الاتصال بتلغرام — جرّب VPN/بروكسي",
        "ProxyError": "البروكسي غير صالح — تحقّق من العنوان والمنفذ",
    }
    if n == "FloodWaitError":
        secs = getattr(e, "seconds", 0) or 0
        if secs > 3600:
            return (f"⏳ تلغرام حجب طلبات الكود مؤقتاً: انتظر ~{secs/3600:.1f} ساعة ثم أعد المحاولة.\n"
                    f"(سبب شائع: ضغط «أرسل الكود» عدة مرات متتالية — اطلبها مرة واحدة وانتظر)")
        return (f"⏳ تلغرام حجب طلبات الكود مؤقتاً: انتظر {secs} ثانية ثم أعد المحاولة "
                f"(لا تضغط الزر عدة مرات)")
    if n in table and table[n]:
        return table[n]
    return f"{n}: {msg[:140]}"


def _proxy_from_cfg():
    c = _cfg()
    p = (c.get("tg_proxy") or os.environ.get("TG_PROXY") or "").strip()
    if not p:
        return None
    # صيغ: host:port | socks5://host:port | http://user:pass@host:port
    import re as _re
    kind = "socks5"
    if "://" in p:
        kind, p = p.split("://", 1)
        kind = "http" if kind.startswith("http") else "socks5"
    user = pw = None
    if "@" in p:
        cred, p = p.split("@", 1)
        if ":" in cred:
            user, pw = cred.split(":", 1)
    host, _, port = p.partition(":")
    if not host or not port:
        return None
    return dict(proxy_type=kind, addr=host, port=int(port), username=user, password=pw,
                rdns=True)


def _mk_client(session=None):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    api_id, api_hash, _, saved = creds()
    if not api_id or not api_hash:
        raise RuntimeError("ما فيه api_id/api_hash — جيبهم من my.telegram.org وحطّهم في الإعدادات")
    try:
        api_id = int(api_id)
    except Exception:
        raise RuntimeError("api_id لازم يكون رقماً")
    px = _proxy_from_cfg()
    kw = dict(device_model="elhadath-reels", system_version="Windows", app_version="1.32",
              connection_retries=3, retry_delay=2, timeout=30)
    if px:
        kw["proxy"] = px
    return TelegramClient(StringSession(session if session is not None else saved),
                          api_id, api_hash, **kw)


_loop = None
_loop_thread = None
_loop_lock = threading.Lock()


def _get_loop():
    """حلقة asyncio واحدة دائمة في خيط خلفي.

    ⚠️ ضرورية: لو فتحنا حلقة جديدة لكل طلب، ينكسر اتصال telethon بين
    «أرسل الكود» و«تأكيد الدخول» (Event loop is closed / attached to a different loop).
    🔒 v1.44: قفل إنشاء — نداءان متزامنان (حالة الربط + دورة الأتمتة) كانا ينشئان
    حلقتين فيتعلّق العميل بالحلقة الخاسرة (RuntimeError: different loop).
    """
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is None or _loop.is_closed() or not _loop.is_running():
            _loop = asyncio.new_event_loop()
            _loop_thread = threading.Thread(target=_loop.run_forever, name="tguser-loop", daemon=True)
            _loop_thread.start()
        return _loop


def _drop_client(cl):
    """افصل عميل telethon مُستبدَل بهدوء (كان يُترك متصلاً = تسريب اتصال ومهام قراءة)."""
    if cl is None:
        return
    try:
        _run(cl.disconnect(), timeout=15)
    except Exception:
        pass


def _run(coro, timeout=300):
    """يشغّل coroutine في الحلقة الدائمة (من كود متزامن).
    عند انتهاء المهلة نلغي الـfuture (كان يبقى عالقاً في الحلقة ويستهلك خيطاً)."""
    fut = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    try:
        return fut.result(timeout=timeout)
    except (concurrent.futures.TimeoutError, TimeoutError):
        fut.cancel()
        raise TimeoutError(f"انتهت مهلة العملية ({timeout}s)")


# ------------------------------------------------------------------ الحالة
def status():
    out = {"installed": installed(), "has_api": False, "authorized": False, "me": ""}
    api_id, api_hash, phone, session = creds()
    out["has_api"] = bool(api_id and api_hash)
    out["phone"] = phone or ""
    if not (out["installed"] and out["has_api"]):
        return out
    if not session:
        return out

    async def _chk():
        cl = _mk_client(session)
        await cl.connect()
        try:
            if await cl.is_user_authorized():
                me = await cl.get_me()
                return (getattr(me, "first_name", "") or "") + \
                       ((" @" + me.username) if getattr(me, "username", None) else "")
        finally:
            await cl.disconnect()
        return ""

    try:
        out["me"] = _run(_chk()) or ""
        out["authorized"] = bool(out["me"])
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


# ------------------------------------------------------------------ الدخول
def code_type_name(t):
    """نوع إرسال الكود (من telethon) بالعربي."""
    n = type(t).__name__
    return {"SentCodeTypeApp": "📱 داخل تطبيق تيليجرام (محادثة Telegram الرسمية)",
            "SentCodeTypeSms": "✉️ رسالة SMS",
            "SentCodeTypeCall": "📞 مكالمة آلية",
            "SentCodeTypeFlashCall": "📞 مكالمة خاطفة",
            "SentCodeTypeMissedCall": "📞 مكالمة فائتة",
            "SentCodeTypeEmailCode": "📧 بريد إلكتروني"}.get(n, n)


def send_code(api_id=None, api_hash=None, phone=None, force_sms=False):
    """يرسل كود تسجيل الدخول. مع force_sms=True يطلب SMS بدل رسالة التطبيق."""
    if not installed():
        raise RuntimeError("مكتبة telethon غير مثبّتة — نفّذ: pip install telethon")
    c = _cfg()
    api_id = api_id or c.get("tg_api_id")
    api_hash = api_hash or c.get("tg_api_hash")
    phone = phone or c.get("tg_phone")
    if not (api_id and api_hash and phone):
        raise RuntimeError("لازم api_id و api_hash ورقم الهاتف")
    if api_id and api_hash:
        _save_cfg(tg_api_id=str(api_id).strip(), tg_api_hash=str(api_hash).strip(),
                  tg_phone=str(phone).strip())

    async def _go():
        cl = _mk_client(None)
        await cl.connect()
        try:
            sent = await cl.send_code_request(str(phone).strip(), force_sms=bool(force_sms))
        except Exception:
            await cl.disconnect()          # لا تُسرّب اتصالاً حين يفشل إرسال الكود
            raise
        return cl, sent

    try:
        cl, sent = _run(_go())
    except Exception as e:
        raise RuntimeError(explain_error(e))
    with _lock:
        old = _pending.get("client")
        _pending.clear()
        _pending.update({"client": cl, "phone": str(phone).strip(),
                         "hash": sent.phone_code_hash})
    _drop_client(old)                                # افصل عميل المحاولة السابقة (لا تسرّب)
    ctype = code_type_name(getattr(sent, "type", None))
    return {"ok": True, "sent": True, "phone": str(phone).strip(), "type": ctype,
            "length": getattr(sent, "length", None),
            "timeout": getattr(sent, "timeout", None),
            "force_sms": bool(force_sms)}


def sign_in(code, password=None):
    """يكمل الدخول بالكود (وإن كان فيه تحقّق بخطوتين: password). يحفظ الجلسة."""
    with _lock:
        st = dict(_pending)
    if not st.get("client"):
        raise RuntimeError("ابدأ بإرسال الكود أولاً (زر «أرسل الكود»)")
    cl = st["client"]

    async def _go():
        from telethon.errors import SessionPasswordNeededError
        try:
            await cl.sign_in(phone=st["phone"], code=str(code).strip(),
                             phone_code_hash=st["hash"])
        except SessionPasswordNeededError:
            if not password:
                return {"need_password": True}
            await cl.sign_in(password=str(password))
        except Exception as e:
            raise RuntimeError(explain_error(e))
        me = await cl.get_me()
        s = cl.session.save()
        name = (getattr(me, "first_name", "") or "") + \
               ((" @" + me.username) if getattr(me, "username", None) else "")
        return {"ok": True, "session": s, "me": name}

    try:
        res = _run(_go())
    except Exception as e:
        raise RuntimeError(explain_error(e))
    if res.get("need_password"):
        return res
    if res.get("session"):
        _save_cfg(tg_session=res["session"])
        with _lock:
            _pending.clear()
    return {"ok": True, "me": res.get("me", ""), "authorized": True}


def logout():
    with _lock:
        _pending.clear()
    _save_cfg(tg_session="")
    return {"ok": True}


# ------------------------------------------------------------------ QR (بلا كود!)
_qr = {}


def qr_png_b64(url):
    """يحوّل رابط tg://login?token=... إلى صورة QR (base64) للعرض في اللوحة."""
    try:
        import qrcode
        from io import BytesIO
        import base64
        img = qrcode.make(url, box_size=7, border=2)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        return ""


def qr_start(api_id=None, api_hash=None):
    """يبدأ تسجيل دخول بـQR: تعرض اللوحة رمزاً تمسحه بتطبيق تيليجرام (بلا كود!).

    على هاتفك: تيليجرام → الإعدادات → الأجهزة → «ربط جهاز» → امسح الرمز.
    """
    if not installed():
        raise RuntimeError("مكتبة telethon غير مثبّتة — نفّذ: pip install telethon")
    c = _cfg()
    api_id = api_id or c.get("tg_api_id")
    api_hash = api_hash or c.get("tg_api_hash")
    if not (api_id and api_hash):
        raise RuntimeError("لازم api_id و api_hash أولاً")
    _save_cfg(tg_api_id=str(api_id).strip(), tg_api_hash=str(api_hash).strip())

    async def _go():
        cl = _mk_client(None)
        await cl.connect()
        qr = await cl.qr_login()
        return cl, qr

    try:
        cl, qr = _run(_go())
    except Exception as e:
        raise RuntimeError(explain_error(e))
    with _lock:
        old_qr = _qr.get("client"); old_pend = _pending.get("client")
        _qr.clear()
        _qr.update({"client": cl, "qr": qr, "state": "waiting", "me": "", "error": "",
                    "url": qr.url})   # نخزّن الرابط فوراً وإلا بنت اللوحة QR فارغاً بعد 3 ثوانٍ
        _pending.update({"client": cl, "phone": "", "hash": "", "qr": qr})
    _drop_client(old_qr if old_qr is not cl else None)
    _drop_client(old_pend if (old_pend is not cl and old_pend is not old_qr) else None)

    def _wait():
        async def _w():
            while True:
                try:
                    await qr.wait(30)
                    me = await cl.get_me()
                    name = (getattr(me, "first_name", "") or "") + \
                           ((" @" + me.username) if getattr(me, "username", None) else "")
                    _save_cfg(tg_session=cl.session.save())
                    with _lock:
                        _qr.update({"state": "ok", "me": name})
                    return
                except Exception as e:
                    n = type(e).__name__
                    if n == "SessionPasswordNeededError":
                        with _lock:
                            _qr.update({"state": "need_password"})
                        return
                    if n in ("TimeoutError", "asyncio.TimeoutError"):
                        try:
                            await qr.recreate()          # جدّد الرمز قبل انتهائه
                        except Exception as e2:
                            with _lock:
                                _qr.update({"state": "error", "error": explain_error(e2)[:120]})
                            return
                        with _lock:
                            _qr["url"] = qr.url
                        continue
                    if n == "LoginTokenExpiredError":
                        with _lock:
                            _qr.update({"state": "expired"})
                        return
                    with _lock:
                        _qr.update({"state": "error", "error": explain_error(e)[:140]})
                    return
        try:
            _run(_w(), timeout=600)
        except Exception as e:
            with _lock:
                if _qr.get("state") == "waiting":
                    _qr.update({"state": "error", "error": str(e)[:120]})

    threading.Thread(target=_wait, daemon=True).start()
    return {"ok": True, "url": qr.url, "png": qr_png_b64(qr.url), "state": "waiting",
            "hint": "على هاتفك: تيليجرام → الإعدادات → الأجهزة → ربط جهاز → امسح الرمز"}


def qr_state():
    with _lock:
        d = dict(_qr)
    url = d.get("url") or ""
    return {"state": d.get("state", "none"), "me": d.get("me", ""),
            "error": d.get("error", ""), "url": url,
            "png": qr_png_b64(url) if (d.get("state") == "waiting" and url) else ""}


def qr_password(password):
    """يكمل دخول QR لو الحساب فيه تحقّق بخطوتين."""
    with _lock:
        cl = (_qr.get("client") or _pending.get("client"))
    if not cl:
        raise RuntimeError("ابدأ بـQR أولاً")

    async def _go():
        await cl.sign_in(password=str(password))
        me = await cl.get_me()
        s = cl.session.save()
        name = (getattr(me, "first_name", "") or "") + \
               ((" @" + me.username) if getattr(me, "username", None) else "")
        return s, name

    try:
        s, name = _run(_go())
    except Exception as e:
        raise RuntimeError(explain_error(e))
    _save_cfg(tg_session=s)
    with _lock:
        _qr.update({"state": "ok", "me": name})
    return {"ok": True, "me": name}


# ------------------------------------------------------------------ القراءة
def _peer(channel):
    return str(channel).strip().lstrip("@").replace("https://t.me/", "").split("/")[0]


def latest_videos(channel, limit=20):
    """أحدث الفيديوهات (كلها — حتى المخفية من الويب) عبر حساب المستخدم."""
    if not installed():
        raise RuntimeError("telethon غير مثبّت")
    _, _, _, session = creds()
    if not session:
        raise RuntimeError("ما فيه جلسة — سجّل الدخول أولاً")

    async def _go():
        cl = _mk_client(session)
        await cl.connect()
        try:
            if not await cl.is_user_authorized():
                raise RuntimeError("الجلسة غير صالحة — أعد تسجيل الدخول")
            out = []
            async for m in cl.iter_messages(_peer(channel), limit=max(40, limit * 4)):
                v = getattr(m, "video", None) or getattr(m, "gif", None)
                if not v:
                    continue
                dur = int(getattr(v, "duration", 0) or 0)
                out.append({
                    "message_id": getattr(m, "id", 0),
                    "text": (getattr(m, "message", "") or "")[:400],
                    "date": m.date.isoformat() if getattr(m, "date", None) else "",
                    "duration": (f"{dur // 60}:{dur % 60:02d}" if dur else ""),
                    "size_mb": round(int(getattr(v, "size", 0) or 0) / 1e6, 1),
                    "video": None,          # يُنزّل عند الحاجة عبر MTProto
                    "videos": [],
                    "is_video": True,
                    "via": "user",
                    "url": f"https://t.me/{_peer(channel)}/{getattr(m, 'id', 0)}",
                })
                if len(out) >= limit:
                    break
            return out
        finally:
            await cl.disconnect()

    return _run(_go())


def download_message(channel, mid, dest, progress=None):
    """ينزّل فيديو رسالة محدّدة بحساب المستخدم. يرجّع مسار الملف."""
    if not installed():
        raise RuntimeError("telethon غير مثبّت")
    _, _, _, session = creds()
    if not session:
        raise RuntimeError("ما فيه جلسة — سجّل الدخول أولاً")

    async def _go():
        cl = _mk_client(session)
        await cl.connect()
        try:
            if not await cl.is_user_authorized():
                raise RuntimeError("الجلسة غير صالحة — أعد تسجيل الدخول")
            msg = await cl.get_messages(_peer(channel), ids=int(mid))
            if not msg:
                raise RuntimeError(f"ما لقيت الرسالة {mid}")
            media = getattr(msg, "video", None) or getattr(msg, "document", None) \
                or getattr(msg, "gif", None)
            if not media:
                raise RuntimeError("هذه الرسالة ما فيها فيديو")
            os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)

            def _cb(done, total):
                if progress and total:
                    try:
                        progress(done / total)
                    except Exception:
                        pass

            path = await cl.download_media(msg, file=dest, progress_callback=_cb)
            return path or dest
        finally:
            await cl.disconnect()

    return _run(_go(), timeout=int(os.environ.get("TG_DOWNLOAD_TIMEOUT", "3600")))


def diag():
    """🩺 تشخيص كامل: telethon؟ بيانات؟ اتصال بالسيرفرات؟ آخر خطأ؟"""
    import socket
    out = {"installed": installed(), "has_api": False, "authorized": False, "dc": {},
           "notes": []}
    api_id, api_hash, phone, session = creds()
    out["has_api"] = bool(api_id and api_hash)
    out["phone"] = phone or ""
    out["proxy"] = bool(_proxy_from_cfg())
    for host in ("149.154.167.51", "149.154.175.50", "91.108.56.130"):
        try:
            t0 = __import__("time").time()
            sck = socket.create_connection((host, 443), timeout=8)
            sck.close()
            out["dc"][host] = f"✅ {__import__('time').time() - t0:.2f}s"
        except Exception as e:
            out["dc"][host] = f"❌ {type(e).__name__}"
    reachable = any(v.startswith("✅") for v in out["dc"].values())
    if not reachable:
        out["notes"].append("ما فيه اتصال بسيرفرات تلغرام — جرّب VPN أو بروكسي "
                            "(حقل البروكسي تحت api_hash)")
    if not out["installed"]:
        out["notes"].append("ثبّت المكتبة: pip install telethon")
    if not out["has_api"]:
        out["notes"].append("أدخل api_id و api_hash ورقم هاتفك")
    if out["has_api"] and session:
        st = status()
        out["authorized"] = bool(st.get("authorized"))
        out["me"] = st.get("me", "")
    if api_id and str(api_id).strip() and not str(api_id).strip().isdigit():
        out["notes"].append("api_id لازم يكون أرقاماً فقط")
    if phone and not str(phone).strip().startswith("+"):
        out["notes"].append("رقم الهاتف لازم يبدأ بـ + والرمز الدولي (مثال +213…)")
    return out
