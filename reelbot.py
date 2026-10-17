#!/usr/bin/env python3
"""reelbot.py — تحكّم بمصنع الريلز من تيليجرام (من هاتفك، من أي مكان).

    python reelbot.py                 # يشغّل اللوحة تلقائياً إن لزم ثم يستمع
    python reelbot.py --once          # دورة واحدة (للفحص)
    python reelbot.py --setup         # اربط البوت: احفظ التوكن وتحقق منه
    python reelbot.py --allow 12345   # أضف محادثة للقائمة البيضاء

يحتاج توكن بوت من @BotFather (الإعدادات → bot_token أو REEL_BOT_TOKEN).
اقرأ reelkit/control.py لفهم المعمارية (قلب واحد: اللوحة، واجهتان: الويب وتيليجرام).
"""
from __future__ import annotations

import argparse
import atexit
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reelkit import control as C
from reelkit.control import Dash, DashError, Tg, TgError, esc, fmt_job, fmt_jobs, kb_job, kb_jobs

ROOT = C.project_root()


def log(*a, **k):
    print(*a, flush=True, **k)


class ControlBot:
    """الراوتر: يحوّل رسائل/أزرار تيليجرام إلى نداءات على واجهة اللوحة."""

    def __init__(self, tg, dash, state, allowlist, cfg, notify=True, verbose=False,
                 allow_any=False):
        self.tg = tg
        self.dash = dash
        self.state = state
        self.allow = allowlist
        self.cfg = cfg
        self.notify = notify
        self.verbose = verbose
        self.allow_any = allow_any
        self._stop = threading.Event()

    # ------------------------------------------------------------ أدوات
    def _authorized(self, chat_id):
        if self.allow_any:
            return True
        return C.allowed(chat_id, self.allow)

    def _reply(self, chat_id, text, keyboard=None):
        try:
            self.tg.send_message(chat_id, text, keyboard=keyboard)
        except TgError as e:
            log(f"  ⚠️ تعذّر الإرسال: {e}")

    def _find(self, jid):
        try:
            j = self.dash.job(jid)
        except DashError as e:
            return None, str(e)
        if not j:
            return None, f"ما لقيت مهمة بالمعرّف {jid}"
        return j, None

    # ------------------------------------------------------------ الدورة
    def run(self, once=False, poll_timeout=25):
        me = self.tg.get_me()
        who = me.get("username") or me.get("first_name") or "?"
        log(f"🤖 البوت يعمل: @{who}")
        if not self.allow and not self.allow_any:
            log("🚫 لا قائمة بيضاء (bot_allowed_chats) — لن يستجيب البوت لأي محادثة.")
            log("   أرسل للبوت /id ثم: python reelbot.py --allow <المعرّف>")
        else:
            log(f"🔒 المحادثات المسموحة: {self.allow or 'الكل (وضع تجربة)'}")
        log(f"🔗 المحرّك: {self.dash.base}")

        watcher = threading.Thread(target=self._watch_jobs, daemon=True, name="reelbot-watch")
        watcher.start()

        while not self._stop.is_set():
            offset = self.state.data.get("offset") or None
            try:
                updates = self.tg.get_updates(offset=offset, timeout=poll_timeout)
            except TgError as e:
                if self.verbose:
                    log(f"  ⚠️ getUpdates: {e}")
                time.sleep(5)
                continue
            except Exception as e:
                log(f"  ⚠️ {type(e).__name__}: {e}")
                time.sleep(5)
                continue
            for u in updates:
                self.state.data["offset"] = int(u.get("update_id", 0)) + 1
                try:
                    self._handle(u)
                except Exception as e:
                    log(f"  ⚠️ معالجة تحديث: {type(e).__name__}: {e}")
            if updates:
                self.state.save()
            if once:
                break
        return 0

    def stop(self):
        self._stop.set()

    def _handle(self, u):
        if "message" in u:
            self._on_message(u["message"])
        elif "callback_query" in u:
            self._on_callback(u["callback_query"])

    # ------------------------------------------------------------ الرسائل
    def _on_message(self, m):
        chat_id = (m.get("chat") or {}).get("id")
        if chat_id is None:
            return
        if not self._authorized(chat_id):
            log(f"🚫 محادثة غير مسموحة: {chat_id} (أضفها بـ--allow {chat_id})")
            if os.environ.get("REEL_BOT_DENY_NOTICE") == "1":
                self._reply(chat_id, f"⛔ غير مصرّح. معرّفك: <code>{chat_id}</code>")
            return
        text = (m.get("text") or m.get("caption") or "").strip()
        if m.get("video") or m.get("document"):
            return self._on_upload(chat_id, m)
        if not text:
            return
        if text.startswith("/"):
            return self._on_command(chat_id, m, text)
        kind, value = C.resolve_target(text)
        if kind:
            return self._create_job(chat_id, value)
        self._reply(chat_id, "🤔 ما فهمت. أرسل رابط مقطع أو مسار ملف، أو <b>/help</b>.",
                    keyboard=C.MAIN_MENU)

    def _on_upload(self, chat_id, m):
        media = m.get("video") or m.get("document") or {}
        size = int(media.get("file_size") or 0)
        name = media.get("file_name") or "upload.mp4"
        if size > 20 * 1024 * 1024:
            return self._reply(
                chat_id, f"⚠️ الملف {size / 1e6:.0f}MB أكبر من حد تنزيل البوت (20MB).\n"
                         f"أرسل رابطاً عاماً (t.me/…) أو ارفعه من اللوحة.")
        self._reply(chat_id, f"⬇️ أستلم الملف ({size / 1e6:.1f}MB)…")
        try:
            data = self.tg.get_file_bytes(media["file_id"])
        except (TgError, Exception) as e:
            return self._reply(chat_id, f"⚠️ تعذّر التنزيل: {esc(e)}")
        incoming = os.path.join(ROOT, "incoming")
        os.makedirs(incoming, exist_ok=True)
        safe = "".join(c for c in name if c.isalnum() or c in "._-")[:40] or "upload.mp4"
        dest = os.path.join(incoming, f"bot_{int(time.time())}_{safe}")
        try:
            with open(dest, "wb") as fh:
                fh.write(data)
        except OSError as e:
            return self._reply(chat_id, f"⚠️ تعذّر الحفظ: {esc(e)}")
        self._create_job(chat_id, dest, source_label=name)

    # ------------------------------------------------------------ الأوامر
    def _on_command(self, chat_id, m, text):
        cmd, args = C.parse_command(text)
        handlers = {
            "start": self._cmd_help, "help": self._cmd_help, "menu": self._cmd_help,
            "jobs": self._cmd_jobs, "list": self._cmd_jobs,
            "job": self._cmd_job,
            "cancel": self._cmd_cancel, "stop": self._cmd_cancel,
            "cancelall": self._cmd_cancelall,
            "delete": self._cmd_delete, "del": self._cmd_delete,
            "retry": self._cmd_retry,
            "clear": self._cmd_clear, "clean": self._cmd_clear,
            "new": self._cmd_new, "add": self._cmd_new,
            "scout": self._cmd_scout,
            "goals": self._cmd_goals,
            "quick": self._cmd_quick,
            "publish": self._cmd_publish,
            "montage": self._cmd_montage,
            "status": self._cmd_status, "stats": self._cmd_status,
            "queue": self._cmd_queue,
            "space": self._cmd_space,
            "settings": self._cmd_settings,
            "set": self._cmd_set,
            "doctor": self._cmd_doctor,
            "id": self._cmd_id,
            "cleanup": self._cmd_cleanup,
        }
        fn = handlers.get(cmd)
        if not fn:
            return self._reply(chat_id, f"❓ أمر غير معروف: /{esc(cmd)}\n\n" + C.HELP)
        try:
            fn(chat_id, args)
        except DashError as e:
            self._reply(chat_id, f"⚠️ المحرّك: {esc(e)}")
        except Exception as e:
            self._reply(chat_id, f"⚠️ {type(e).__name__}: {esc(e)}")

    def _cmd_help(self, chat_id, args):
        self._reply(chat_id, C.HELP, keyboard=C.MAIN_MENU)

    def _cmd_id(self, chat_id, args):
        self._reply(chat_id, f"🆔 معرّف محادثتك: <code>{chat_id}</code>\n"
                             f"لإضافته: <code>python reelbot.py --allow {chat_id}</code>")

    def _cmd_jobs(self, chat_id, args):
        jobs = self.dash.jobs()
        try:
            limit = max(1, min(20, int(args[0]))) if args else 8
        except ValueError:
            limit = 8
        self._reply(chat_id, fmt_jobs(jobs, limit=limit), keyboard=kb_jobs(jobs, limit=limit))

    def _cmd_job(self, chat_id, args):
        if not args:
            return self._reply(chat_id, "الصيغة: /job &lt;id&gt;")
        j, err = self._find(args[0])
        if err:
            return self._reply(chat_id, f"⚠️ {esc(err)}")
        body = fmt_job(j)
        logs = (j.get("log") or [])[-8:]
        if logs:
            body += "\n\n<b>آخر السجل</b>\n<pre>" + esc("\n".join(logs))[:1500] + "</pre>"
        self._reply(chat_id, body, keyboard=kb_job(j.get("id"), j.get("status")))

    def _cmd_cancel(self, chat_id, args):
        if not args:
            return self._reply(chat_id, "الصيغة: /cancel &lt;id&gt;")
        r = self.dash.cancel(args[0])
        self._reply(chat_id, f"⏹ {esc(r)}" if not r.get("ok") else "⏹ أُرسل طلب الإيقاف.")
        self.state.forget(args[0])

    def _cmd_cancelall(self, chat_id, args):
        n = 0
        for j in self.dash.jobs():
            if j.get("status") in ("running", "queued"):
                try:
                    self.dash.cancel(j["id"])
                    n += 1
                except DashError:
                    pass
        self._reply(chat_id, f"⏹ أوقفت {n} مهمة.")

    def _cmd_delete(self, chat_id, args):
        if not args:
            return self._reply(chat_id, "الصيغة: /delete &lt;id&gt;")
        self.dash.delete(args[0])
        self.state.forget(args[0])
        self._reply(chat_id, f"🗑 حُذفت المهمة {esc(args[0])}.")

    def _cmd_retry(self, chat_id, args):
        r = self.dash.retry_failed()
        self._reply(chat_id, f"🔁 أعدت تشغيل {r.get('count', 0)} مهمة فاشلة.")

    def _cmd_clear(self, chat_id, args):
        r = self.dash.clear_finished()
        self._reply(chat_id, f"🧹 حذفت {r.get('count', 0)} مهمة منتهية.")

    def _cmd_new(self, chat_id, args):
        text = " ".join(args) if args else ""
        kind, value = C.resolve_target(text)
        if not kind:
            return self._reply(chat_id, "أرسل رابط مقطع أو مسار ملف:\n"
                                         "<code>/new https://t.me/…</code>\n"
                                         "<code>/new /path/to/clip.mp4</code>")
        self._create_job(chat_id, value)

    def _create_job(self, chat_id, target, overrides=None, source_label=None):
        local = target if os.path.exists(target) and not target.startswith("http") else None
        payload, err = C.build_create_payload(target, self.cfg, overrides, local_path=local)
        if err:
            return self._reply(chat_id, f"⚠️ {esc(err)}")
        self._reply(chat_id, f"🚀 أضفت المهمة للطابور…\n<code>{esc(source_label or target)}</code>")
        try:
            jid = self.dash.create(payload)
        except DashError as e:
            return self._reply(chat_id, f"⚠️ تعذّر الإنشاء: {esc(e)}")
        self.state.track(jid, chat_id)
        j = None
        try:
            j = self.dash.job(jid)
        except DashError:
            pass
        self._reply(chat_id, f"✅ المهمة <code>{jid}</code> في الطابور.\nسأبلغك عند الانتهاء.",
                    keyboard=kb_job(jid, (j or {}).get("status", "queued")))

    def _cmd_scout(self, chat_id, args):
        target = C.extract_target(" ".join(args))
        if not target:
            return self._reply(chat_id, "الصيغة: /scout &lt;رابط&gt;")
        self._reply(chat_id, "🔭 أشغّل الكشّاف… (يحتاج دقيقة أو أكثر بلا كرت رسومات)")
        try:
            r = self.dash.quickcheck({"input": target, "seconds": 8})
        except DashError as e:
            return self._reply(chat_id, f"⚠️ {esc(e)}")
        logtxt = (r.get("log") or "")[-2000:]
        self._reply(chat_id, f"🔭 <b>نتيجة المعاينة</b>\n<pre>{esc(logtxt)}</pre>")

    def _cmd_goals(self, chat_id, args):
        if len(args) < 2 or not args[0].isdigit():
            return self._reply(chat_id, "الصيغة: /goals &lt;العدد&gt; &lt;رابط&gt; [montage]")
        n = max(1, min(10, int(args[0])))
        montage = any(a.lower() in ("montage", "مونتاج") for a in args[2:])
        target = C.extract_target(" ".join(args[1:]))
        if not target:
            return self._reply(chat_id, "ما لقيت رابطاً.")
        self._create_job(chat_id, target,
                         overrides={"goals": n, "goals_montage": montage},
                         source_label=target)

    def _cmd_quick(self, chat_id, args):
        target = C.extract_target(" ".join(args))
        if not target:
            return self._reply(chat_id, "الصيغة: /quick &lt;رابط&gt; [ثوانٍ]")
        secs = 6
        for a in args:
            if a.isdigit():
                secs = max(3, min(20, int(a)))
        self._reply(chat_id, f"🎬 رندر سريع ({secs}s)… انتظر قليلاً")
        try:
            r = self.dash.quickcheck({"input": target, "seconds": secs})
        except DashError as e:
            return self._reply(chat_id, f"⚠️ {esc(e)}")
        path = os.path.join(C.outputs_dir(), os.path.basename(r.get("url") or ""))
        if os.path.exists(path):
            try:
                self.tg.send_video(chat_id, path, caption="🎬 معاينة سريعة")
                return
            except TgError as e:
                self._reply(chat_id, f"⚠️ تعذّر الإرسال: {esc(e)}")
        self._reply(chat_id, "✅ تمت المعاينة، لكن تعذّر إرسال الملف. "
                             f"<pre>{esc((r.get('log') or '')[-800:])}</pre>")

    def _cmd_publish(self, chat_id, args):
        if not args:
            return self._reply(chat_id, "الصيغة: /publish &lt;id&gt; [yt|tg|both]")
        jid = args[0]
        which = args[1].lower() if len(args) > 1 else "both"
        targets = {"yt": ["youtube"], "youtube": ["youtube"],
                   "tg": ["telegram"], "telegram": ["telegram"],
                   "both": ["youtube", "telegram"]}.get(which)
        if not targets:
            return self._reply(chat_id, "حدّد: yt | tg | both")
        self._reply(chat_id, f"📤 أنشر ({which})…")
        try:
            r = self.dash.publish(jid, targets)
        except DashError as e:
            return self._reply(chat_id, f"⚠️ {esc(e)}")
        self._reply(chat_id, f"📤 <pre>{esc(str(r)[:1200])}</pre>")

    def _cmd_montage(self, chat_id, args):
        ids = [x.strip() for x in " ".join(args).replace("،", ",").split(",") if x.strip()]
        if len(ids) < 2:
            return self._reply(chat_id, "الصيغة: /montage &lt;id1,id2,…&gt; (مهمتان فأكثر)")
        self._reply(chat_id, "🎞️ أبني المونتاج…")
        try:
            r = self.dash.montage(ids)
        except DashError as e:
            return self._reply(chat_id, f"⚠️ {esc(e)}")
        self._reply(chat_id, f"🎞️ {esc(r.get('title') or '')}\n<code>{esc(r.get('path') or '')}</code>")

    def _cmd_status(self, chat_id, args):
        st = self.dash.stats()
        q = self.dash.queue()
        msg = (f"📊 <b>الحالة</b>\n"
               f"⚙️ يشتغل: {q.get('running', 0)} · ⏳ ينتظر: {q.get('waiting', 0)} "
               f"(الحد {q.get('limit', 1)})\n"
               f"✅ منتهية: {st.get('done', 0)} · ❌ فاشلة: {st.get('failed', 0)} "
               f"· 📦 المجموع: {st.get('total', 0)}\n"
               f"⏱️ زمن المعالجة: {st.get('seconds', 0):.0f}s · "
               f"💾 {st.get('bytes', 0) / 1e9:.2f}GB")
        self._reply(chat_id, msg, keyboard=C.MAIN_MENU)

    def _cmd_queue(self, chat_id, args):
        q = self.dash.queue()
        self._reply(chat_id, f"🚦 يشتغل: {q.get('running', 0)} · ينتظر: {q.get('waiting', 0)} "
                             f"· الحد: {q.get('limit', 1)}")

    def _cmd_space(self, chat_id, args):
        sp = self.dash.space()
        self._reply(chat_id, f"💾 <pre>{esc(json_dumps(sp))[:1200]}</pre>")

    def _cmd_cleanup(self, chat_id, args):
        try:
            r = self.dash.cleanup()
        except DashError as e:
            return self._reply(chat_id, f"⚠️ {esc(e)}")
        self._reply(chat_id, f"🧹 <pre>{esc(json_dumps(r))[:800]}</pre>")

    def _cmd_settings(self, chat_id, args):
        try:
            cfg = self.dash.settings()
        except DashError as e:
            return self._reply(chat_id, f"⚠️ {esc(e)}")
        self._reply(chat_id, C.settings_summary(cfg))

    def _cmd_set(self, chat_id, args):
        key, val, err = C.parse_set(args)
        if err:
            return self._reply(chat_id, f"⚠️ {esc(err)}")
        try:
            self.dash.settings_set({key: val})
        except DashError as e:
            return self._reply(chat_id, f"⚠️ {esc(e)}")
        self._reply(chat_id, f"⚙️ <code>{esc(key)}</code> = {esc(val)} ✅")

    def _cmd_doctor(self, chat_id, args):
        self._reply(chat_id, "🩺 أفحص النظام…")
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "doctor.py")],
                               cwd=ROOT, capture_output=True, text=True, timeout=300,
                               env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            tail = (r.stdout or "")[-2500:]
        except Exception as e:
            tail = f"{type(e).__name__}: {e}"
        self._reply(chat_id, f"🩺 <pre>{esc(tail)}</pre>")

    # ------------------------------------------------------------ الأزرار
    def _on_callback(self, cb):
        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
        msg_id = (cb.get("message") or {}).get("message_id")
        data = cb.get("data") or ""
        if chat_id is None or not self._authorized(chat_id):
            return self.tg.answer_callback(cb.get("id", ""), "غير مصرّح", alert=True)
        try:
            action, _, jid = data.partition(":")
            if action == "l":
                self.tg.answer_callback(cb.get("id", ""), "تحديث")
                jobs = self.dash.jobs()
                return self._edit(chat_id, msg_id, fmt_jobs(jobs), kb_jobs(jobs))
            if action == "j":
                self.tg.answer_callback(cb.get("id", ""))
                j = self.dash.job(jid)
                if not j:
                    return self._edit(chat_id, msg_id, "⚠️ المهمة لم تعد موجودة.")
                logs = (j.get("log") or [])[-6:]
                body = fmt_job(j) + ("\n\n<pre>" + esc("\n".join(logs))[:1200] + "</pre>" if logs else "")
                return self._edit(chat_id, msg_id, body, kb_job(jid, j.get("status")))
            if action == "c":
                r = self.dash.cancel(jid)
                self.tg.answer_callback(cb.get("id", ""), "أُرسل الإيقاف")
                return self._edit(chat_id, msg_id, f"⏹ طلب إيقاف <code>{esc(jid)}</code>.")
            if action == "d":
                self.dash.delete(jid)
                self.state.forget(jid)
                self.tg.answer_callback(cb.get("id", ""), "تم الحذف")
                return self._edit(chat_id, msg_id, f"🗑 حُذفت <code>{esc(jid)}</code>.")
            if action == "r":
                rr = self.dash.rerun(jid)
                self.tg.answer_callback(cb.get("id", ""), "أُعيد التشغيل")
                if rr.get("id"):
                    self.state.track(rr["id"], chat_id)
                return self._edit(chat_id, msg_id, f"🔁 أعيد <code>{esc(jid)}</code> كـ"
                                                   f"<code>{esc(rr.get('id'))}</code>.")
            if action in ("py", "pt", "pb"):
                which = {"py": "yt", "pt": "tg", "pb": "both"}[action]
                self.tg.answer_callback(cb.get("id", ""), "أنشر…")
                targets = {"yt": ["youtube"], "tg": ["telegram"], "both": ["youtube", "telegram"]}[which]
                r = self.dash.publish(jid, targets)
                return self._edit(chat_id, msg_id, f"📤 <pre>{esc(str(r)[:900])}</pre>")
            if action == "v":
                self.tg.answer_callback(cb.get("id", ""), "أرسل الملف…")
                return self._send_job_video(chat_id, jid)
            if action == "p":
                return self._edit(chat_id, msg_id, "📤 اختر الوجهة:", kb_job(jid, "done"))
            if action == "s":
                self.tg.answer_callback(cb.get("id", ""))
                return self._cmd_status(chat_id, [])
            if action == "q":
                self.tg.answer_callback(cb.get("id", ""))
                return self._cmd_queue(chat_id, [])
            if action == "sp":
                self.tg.answer_callback(cb.get("id", ""))
                return self._cmd_space(chat_id, [])
            if action == "rf":
                r = self.dash.retry_failed()
                self.tg.answer_callback(cb.get("id", ""), f"أعدت {r.get('count', 0)}")
                return self._edit(chat_id, msg_id, f"🔁 أعدت {r.get('count', 0)} مهمة فاشلة.")
            if action == "cl":
                r = self.dash.clear_finished()
                self.tg.answer_callback(cb.get("id", ""), f"نظّفت {r.get('count', 0)}")
                return self._edit(chat_id, msg_id, f"🧹 حذفت {r.get('count', 0)} مهمة منتهية.")
            if action == "id":
                self.tg.answer_callback(cb.get("id", ""), str(chat_id), alert=False)
                return self._edit(chat_id, msg_id, f"🆔 <code>{chat_id}</code>")
            self.tg.answer_callback(cb.get("id", ""), "غير معروف", alert=True)
        except DashError as e:
            self.tg.answer_callback(cb.get("id", ""), f"خطأ: {str(e)[:120]}", alert=True)
        except TgError:
            pass

    def _edit(self, chat_id, msg_id, text, keyboard=None):
        if msg_id is None:
            return self._reply(chat_id, text, keyboard)
        try:
            return self.tg.edit_message(chat_id, msg_id, text, keyboard)
        except TgError:
            try:
                return self._reply(chat_id, text, keyboard)
            except TgError:
                return None

    # ------------------------------------------------------------ المراقب
    def _watch_once(self):
        """دورة مراقبة واحدة — تُفصل عن الحلقة لتُختبر وحدياً."""
        watched = self.state.watched()
        if not watched:
            return
        current = {str(j.get("id")): j for j in self.dash.jobs()}
        for jid, rec in watched.items():
            j = current.get(jid)
            if j is None:
                continue
            st = j.get("status")
            # لا نعتمد على «أول دورة»: الأعلام محفوظة على القرص فتمنع التكرار،
            # وتمسك مهمة انتهت بينما البوت كان متوقفاً.
            if st == "running" and not rec.get("notified_run"):
                for cid in rec.get("chats", []):
                    self._reply(cid, f"⚙️ بدأ التنفيذ: <code>{esc(jid)}</code>")
                self.state.update(jid, notified_run=True, last=st)
            elif st == "done" and not rec.get("notified_done"):
                for cid in rec.get("chats", []):
                    self._notify_done(cid, j)
                self.state.update(jid, notified_done=True, last=st)
            elif st == "failed" and not rec.get("notified_fail"):
                for cid in rec.get("chats", []):
                    logs = (j.get("log") or [])[-4:]
                    self._reply(cid, "❌ فشلت المهمة "
                                     f"<code>{esc(jid)}</code>\n"
                                     f"<pre>{esc(chr(10).join(logs))[:900]}</pre>",
                                keyboard=kb_job(jid, "failed"))
                self.state.update(jid, notified_fail=True, last=st)
            elif st != rec.get("last"):
                self.state.update(jid, last=st)

    def _watch_jobs(self, interval=5.0):
        """يراقب المهام المتتبَّعة ويبلّغ المحادثة عند الانتهاء/الفشل."""
        while not self._stop.is_set():
            try:
                self._watch_once()
            except DashError:
                pass
            except Exception as e:
                if self.verbose:
                    log(f"  ⚠️ watcher: {type(e).__name__}: {e}")
            self.state.trim()
            self._stop.wait(interval)

    def _notify_done(self, chat_id, j):
        jid = j.get("id")
        title = j.get("title") or j.get("label") or ""
        cap = f"✅ ريل جاهز\n🏷️ {title}\n⏱️ {float(j.get('duration') or 0):.1f}s"
        sent = self._send_job_video(chat_id, jid, caption=cap, quiet=True)
        if not sent:
            self._reply(chat_id, f"✅ ريل جاهز: <code>{esc(jid)}</code>\n{esc(title)}",
                        keyboard=kb_job(jid, "done"))

    def _send_job_video(self, chat_id, jid, caption="", quiet=False):
        try:
            j = self.dash.job(jid)
        except DashError as e:
            if not quiet:
                self._reply(chat_id, f"⚠️ {esc(e)}")
            return False
        if not j or j.get("status") != "done":
            if not quiet:
                self._reply(chat_id, "⚠️ المهمة ليست جاهزة بعد.")
            return False
        path = j.get("output")
        if not path or not os.path.exists(path):
            if not quiet:
                self._reply(chat_id, "⚠️ ملف الريل غير موجود على هذا الجهاز "
                                     "(محرّك بعيد؟). استخدم اللوحة للمعاينة.")
            return False
        if os.path.getsize(path) > 49e6:
            try:
                self.tg.send_document(chat_id, path, caption=caption or "✅ ريل جاهز")
                return True
            except TgError as e:
                if not quiet:
                    self._reply(chat_id, f"⚠️ {esc(e)}")
                return False
        try:
            self.tg.send_video(chat_id, path, caption=caption or "✅ ريل جاهز",
                               keyboard=kb_job(jid, "done"))
            return True
        except TgError as e:
            if not quiet:
                self._reply(chat_id, f"⚠️ {esc(e)}")
            return False


def json_dumps(o):
    import json as _j
    return _j.dumps(o, ensure_ascii=False)


# ------------------------------------------------------------------ تشغيل اللوحة
class _Engine:
    """يشغّل اللوحة كعملية ابنة عند الحاجة (قلب واحد)."""

    def __init__(self, port, host="127.0.0.1", spawn=True, verbose=False):
        self.base = f"http://{host}:{port}"
        self.port, self.host = port, host
        self.spawn = spawn
        self.verbose = verbose
        self.proc = None

    def ensure(self, token="", wait=25):
        dash = Dash(self.base, token=token)
        if dash.ping():
            log(f"🔗 وجدت لوحة تعمل على {self.base} — أتصل بها.")
            return dash
        if not self.spawn:
            raise DashError(f"لا لوحة على {self.base} و--no-spawn مُمرَّر")
        log(f"🚀 أشغّل اللوحة على {self.base} …")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "dashboard.py"),
             "--host", self.host, "--port", str(self.port)],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        atexit.register(self.stop)
        deadline = time.time() + wait
        while time.time() < deadline:
            if dash.ping():
                log("✅ اللوحة جاهزة.")
                return dash
            if self.proc.poll() is not None:
                raise DashError("فشل تشغيل اللوحة — شغّلها يدوياً وشاهد الخطأ")
            time.sleep(1)
        raise DashError("انتهت مهلة انتظار اللوحة")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                from reelkit.ffio import kill_tree
                kill_tree(self.proc)
            except Exception:
                try:
                    self.proc.terminate()
                except Exception:
                    pass


# ------------------------------------------------------------------ البرنامج
def _mask(s, keep=6):
    s = str(s or "")
    return s[:keep] + "…" + s[-4:] if len(s) > keep + 4 else ("•" * len(s))


def main(argv=None):
    ap = argparse.ArgumentParser(description="بوت تيليجرام لتحكّم مصنع الريلز عن بعد")
    ap.add_argument("--token", help="توكن بوت تيليجرام (أو bot_token في config.json)")
    ap.add_argument("--allow", action="append", default=[],
                    help="معرّف محادثة مسموح (يمكن تكراره)")
    ap.add_argument("--port", type=int, default=8000, help="منفذ اللوحة (افتراضي 8000)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-spawn", action="store_true", help="لا تشغّل اللوحة تلقائياً")
    ap.add_argument("--once", action="store_true", help="دورة استقبال واحدة ثم خروج")
    ap.add_argument("--setup", action="store_true", help="احفظ التوكن وتحقق منه ثم اخرج")
    ap.add_argument("--api-base", default=C.API, help="قاعدة Bot API (للاختبار/سيرفر محلي)")
    ap.add_argument("--poll", type=int, default=25, help="مهلة long-poll بالثواني")
    ap.add_argument("--notify", dest="notify", action="store_true", default=True)
    ap.add_argument("--no-notify", dest="notify", action="store_false")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args(argv)

    # --allow لا يحتاج توكن (يُستخدم أثناء الإعداد)
    if a.allow:
        cfg0 = C.load_cfg()
        raw = C.parse_allowed(a.allow)
        cur = cfg0.get("bot_allowed_chats")
        merged = C.parse_allowed(cur) if cur else []
        for x in raw:
            if x not in merged:
                merged.append(x)
        if C.save_cfg_keys({"bot_allowed_chats": merged}):
            print(f"✅ القائمة البيضاء: {merged}")
        else:
            print("⚠️ تعذّر الحفظ", file=sys.stderr)
        return 0

    cfg = C.load_cfg()
    token = (a.token or os.environ.get("REEL_BOT_TOKEN")
             or cfg.get("bot_token") or "").strip()
    if not token:
        print("❌ ما فيه توكن بوت. جيبه من @BotFather ثم:\n"
              "   python reelbot.py --setup --token <TOKEN>", file=sys.stderr)
        return 2

    if a.setup:
        try:
            me = Tg(token, api_base=a.api_base).get_me()
        except TgError as e:
            print(f"❌ التوكن غير صالح: {e}", file=sys.stderr)
            return 1
        saved = C.save_cfg_keys({"bot_token": token})
        print(f"✅ البوت: @{me.get('username')} ({me.get('first_name')})"
              f"{' — حُفظ في config.json' if saved else ' — تعذّر الحفظ'}")
        print("الخطوة التالية: شغّل البوت، أرسل له /id، ثم:\n"
              f"   python reelbot.py --allow <المعرّف>")
        return 0

    allowlist = C.parse_allowed(a.allow) or C.parse_allowed(
        os.environ.get("REEL_BOT_ALLOWED_CHATS") or cfg.get("bot_allowed_chats"))
    allow_any = os.environ.get("REEL_BOT_ALLOW_ANY") == "1"

    engine = _Engine(a.port, a.host, spawn=not a.no_spawn, verbose=a.verbose)
    try:
        dash = engine.ensure(token=(os.environ.get("REEL_DASH_TOKEN") or ""))
    except DashError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    tg = Tg(token, api_base=a.api_base)
    state = C.BotState(os.path.join(C.outputs_dir(), "bot_state.json"))
    bot = ControlBot(tg, dash, state, allowlist, C.load_cfg(),
                     notify=a.notify, verbose=a.verbose, allow_any=allow_any)
    try:
        return bot.run(once=a.once, poll_timeout=a.poll)
    except KeyboardInterrupt:
        print("\n👋 إيقاف")
        return 0
    finally:
        bot.stop()
        engine.stop()


if __name__ == "__main__":
    sys.exit(main())
