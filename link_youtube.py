#!/usr/bin/env python3
"""link_youtube.py — ربط قناة يوتيوب بخطوة واحدة (يفتح المتصفح ويلصق الكود)."""
import os, sys, json, webbrowser
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def main():
    from reelkit.publish.youtube import auth_url, finish_auth, YouTubeUploader, find_client_secret, client_secret_help
    cs = find_client_secret()
    if not cs:
        print("=" * 60)
        print("  ⚠️  ما لقيت ملف اعتماد يوتيوب (client_secret.json)")
        print("=" * 60)
        print(client_secret_help())
        print("\n📎 أسهل طريقة: لوحة التحكم → ⚙️ الإعدادات → «رفع ملف اعتماد يوتيوب»")
        print("   أو يدوياً: انسخ الملف إلى  reelkit\\publish\\client_secret.json")
        return
    print(f"✓ ملف الاعتماد: {cs}")
    print("=" * 60)
    print("  ربط قناة يوتيوب بـ elhadath-reels")
    print("=" * 60)
    print("\n➊ راح يفتح المتصفح — سجّل دخول بحساب قوقل المالك للقناة.")
    print("➋ اختر «الجزائر الجديدة TV» ثم اضغط «السماح / Allow».")
    print("➌ خلاص! راح يرجع تلقائياً للنافذة ويحفظ الربط.")
    print("   (لو ما رجع تلقائياً — راح ننتقل للطريقة اليدوية ونطلب منك لصق الرابط)\n")
    # ---- المسار الأوتوماتيكي: سيرفر محلي يلتقط الكود لحاله (الأفضل على جهاز فيه متصفح) ----
    if "--manual" not in sys.argv:
        try:
            os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
            from google_auth_oauthlib.flow import Flow
            from reelkit.publish.youtube import SCOPES, LOOPBACK
            print("\n⏳ فتحت صفحة الموافقة… وافق وبعدها راح يرجع تلقائياً (بلا نسخ ولا لصق).")
            flow = Flow.from_client_secrets_file(cs, SCOPES, redirect_uri=LOOPBACK)
            creds = flow.run_local_server(
                port=8765, open_browser=True, timeout_seconds=300,
                authorization_prompt_message="افتح هذا الرابط إن ما فتح تلقائياً:\n{url}",
                success_message="✅ تم! تقدر تسكّر هذه الصفحة وترجع للنافذة السوداء.")
            token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "reelkit", "publish", "token.json")
            with open(token_path, "w") as f:
                f.write(creds.to_json())
            print(f"\n✅ حُفظ التوكن في: {token_path}")
            _verify(YouTubeUploader())
            return
        except Exception as e:
            print(f"\n⚠️  الطريقة الأوتوماتيكية ما نجحت ({type(e).__name__}: {e})")
            print("   ننتقل للطريقة اليدوية…\n")

    url = auth_url()
    print("الرابط:\n" + url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    code = input("الصق الرابط (أو الكود) هنا ثم Enter:\n> ").strip()
    if not code:
        print("ما لصقت شي — أعد المحاولة."); return
    try:
        tp = finish_auth(code)
        print(f"\n✅ حُفظ التوكن في: {tp}")
    except Exception as e:
        print(f"\n❌ فشل الربط: {e}\n   تأكد أنك لصقت الرابط كامل (فيه code=…) وأنه جديد."); return
    _verify(YouTubeUploader())


def _verify(uploader):
    expected = ""
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        expected = cfg.get("youtube_channel_id", "")
    except Exception:
        pass
    try:
        info = uploader.verify_channel(expected) if expected else uploader.channel_info()
        print(f"✅ القناة المرتبطة: {info.get('title')}  ({info.get('id')})")
        print(f"   المشتركون: {info.get('subscribers')} | الفيديوهات: {info.get('videos')}")
        print("\n🎉 جاهز! من الآن الرفع لليوتيوب يشتغل تلقائياً.")
        print("   ملاحظة: لحد ما يجتاز مشروعك تدقيق YouTube، الرفع يطلع private.")
    except Exception as e:
        print(f"⚠️  الربط تم بس تعذر التحقق من القناة: {e}")

if __name__ == "__main__":
    main()
