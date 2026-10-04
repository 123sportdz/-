"""graphics — Arabic text (correct RTL shaping), brand lockup, ball trail.

⚠️ raqm (v1.44): حزم Pillow الحديثة تُبنى مع **libraqm** الذي يشكّل العربية تلقائياً.
تمرير نص مشكّل مسبقاً (arabic_reshaper + bidi) لـPillow-with-raqm يعيد تشكيله **مرة
ثانية** فيخرج النص بحروف معزولة ومكسورة (شوهد: «الجزائر الجديدة» → «ڤدىعدلا رئانزجلا»).
لذلك: لو raqm متاح ⇒ نرسم **النص الخام** مع direction='rtl'، وإلا نكمل بالمسار القديم
(نشكّل يدوياً). النتيجة صحيحة في كلتا البيئتين.
"""
import cv2, numpy as np, os, glob, sys, math
from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

_RAQM = None


def has_raqm():
    """True = Pillow مبني مع libraqm (يشكّل العربية بنفسه — لا نشكّل يدوياً)."""
    global _RAQM
    if _RAQM is None:
        try:
            from PIL import features
            _RAQM = bool(features.check("raqm"))
        except Exception:
            _RAQM = False
    return _RAQM

# خطوط مرشّحة بالترتيب: مرفوعة مع المشروع أولاً (تشتغل على أي نظام)، ثم خطوط النظام.
_CANDIDATES_BOLD = [
    os.environ.get("REEL_FONT_BOLD"),
    os.path.join(ASSETS, "NotoSansArabic-Bold.ttf"),      # عربي
    os.path.join(ASSETS, "NotoSansArabicUI-Bold.ttf"),    # عربي احتياطي 1
    os.path.join(ASSETS, "NotoKufiArabic-Black.ttf"),     # عربي احتياطي 2
    os.path.join(ASSETS, "DejaVuSans-Bold.ttf"),          # لاتيني (الخط العربي ما فيه لاتيني!)
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    os.path.expanduser("~/.fonts/NotoSansArabic-Bold.ttf"),
]
_CANDIDATES_REG = [
    os.environ.get("REEL_FONT_REG"),
    os.path.join(ASSETS, "NotoSansArabic-Regular.ttf"),
    os.path.join(ASSETS, "DejaVuSans.ttf"),
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    os.path.expanduser("~/.fonts/NotoSansArabic-Regular.ttf"),
]

ASSET_SIZES = {"NotoSansArabic-Bold.ttf": 252940, "NotoSansArabic-Regular.ttf": 244072,
               "NotoSansArabicUI-Bold.ttf": 279468, "NotoKufiArabic-Black.ttf": 193248,
               "DejaVuSans-Bold.ttf": 705684, "DejaVuSans.ttf": 757076}


_FT_OK = None

def _fonttools_available():
    global _FT_OK
    if _FT_OK is None:
        try:
            import fontTools.ttLib  # noqa
            _FT_OK = True
        except Exception:
            _FT_OK = False
    return _FT_OK


def arabic_coverage(path):
    """(حروف عربية, أشكال عرض) من cmap الخط.
    ترجّع (-2,-2) لو fontTools غير متاح، و(-1,-1) لو الملف تالف/غير مقروء."""
    if not _fonttools_available():
        return -2, -2
    try:
        from fontTools.ttLib import TTFont
        cm = TTFont(path, fontNumber=0, lazy=True).getBestCmap()
        ar = sum(1 for c in cm if 0x0600 <= c <= 0x06FF)
        fe = sum(1 for c in cm if 0xFE70 <= c <= 0xFEFF)
        return ar, fe
    except Exception:
        return -1, -1


def _tofu_test(path):
    """True = الخط يرسم عربي فعلاً."""
    ar, fe = arabic_coverage(path)
    if ar == -1:
        return False                        # الملف تالف/غير مقروء -> مرفوض
    if ar >= 0:
        # ✅ v1.45: مع raqm نحن نرسم النص **خاماً** وPillow يشكّله عبر GSUB،
        # فشرط "أشكال العرض FE70-FEFF" صار قديماً ويرفض خطوطاً سليمة (NotoKufi).
        if has_raqm():
            return ar >= 60
        return ar >= 60 and fe >= 40        # بلا raqm نستخدم arabic_reshaper
    name = os.path.basename(path).lower()   # fontTools غير متاح: احتياطي بالاسم
    return any(k in name for k in ("arab", "noto", "amiri", "cairo", "tahoma", "segoeui", "arial"))


def _arabic_pref(path):
    """هل هذا خط عربي مفضّل (لا خط لاتيني احتياطي مثل DejaVu)؟
    نستخدمه للقرار في مسار raqm ذي الخط الواحد: إن كان الخط المغطّي للنص كله
    هو DejaVu (لأن النص يخلط عربي+لاتيني) نرجع للرسم المُجزّأ حتى يرسم العربي
    بخطه العربي الصحيح بدل DejaVu."""
    return bool(path) and "dejavu" not in os.path.basename(path).lower()


def asset_files_ok():
    """هل الخطوط المرفقة سليمة (الحجم المتوقع)؟ يكشف تلفاً من فك ضغط ناقص."""
    out = {}
    for name, size in ASSET_SIZES.items():
        p = os.path.join(ASSETS, name)
        out[name] = {"exists": os.path.exists(p),
                     "size": os.path.getsize(p) if os.path.exists(p) else 0,
                     "expected": size,
                     "ok": os.path.exists(p) and abs(os.path.getsize(p) - size) < 2048}
    return out


def _find(cands, label, verify=True):
    """يرجّع أول خط موجود **ويرسم العربية فعلاً** (يمنع مربعات tofu)."""
    tried = []
    for c in cands:
        if not c:
            continue
        if os.path.exists(c):
            if not verify or _tofu_test(c):
                return c
            tried.append(os.path.basename(c))
    # بحث احتياطي في مجلدات الخطوط المعروفة
    pats = [os.path.join(ASSETS, "*.ttf"),
            "/usr/share/fonts/**/*Arabic*.ttf",
            "C:/Windows/Fonts/*.ttf",
            os.path.expanduser("~/Library/Fonts/*.ttf"),
            os.path.expanduser("~/.fonts/*.ttf")]
    for pat in pats:
        for f in sorted(glob.glob(pat, recursive=True)):
            n = os.path.basename(f).lower()
            if any(k in n for k in ("arab", "noto", "tahoma", "arial", "segoeui", "amiri", "cairo")):
                if _tofu_test(f):
                    return f
    if tried:
        raise RuntimeError(
            "كل الخطوط المجرّبة موجودة بس ما ترسم عربي (تطلع مربعات): " + ", ".join(tried) +
            "\nالحل: تأكد أن ملف reelkit/assets/NotoSansArabic-Bold.ttf سليم "
            "(أعد فك الضغط)، أو حدّد خطاً: set REEL_FONT_BOLD=C:\\Windows\\Fonts\\tahoma.ttf")
    raise RuntimeError(
        f"ما لقيت خط عربي ({label}).\n"
        f"الحل: تأكد أن مجلد reelkit/assets موجود فيه الخطوط، "
        f"أو حدّد خطاً بنفسك: set REEL_FONT_BOLD=C:\\Windows\\Fonts\\tahoma.ttf")


_FONT_CACHE = {}
_SAFE_CACHE = {}
_WARNED = set()

def _cache_put(cache, key, val, cap=1024):
    """حد أعلى للذاكرات — الواجهة طويلة العمر كانت تنمو بلا سقف لكل عنوان/كابشن."""
    if len(cache) >= cap:
        cache.clear()
    cache[key] = val


def _all_candidates(bold=True):
    """كل الخطوط المرشّحة بالترتيب + أي خط عربي يُكتشف في النظام."""
    out = list(_CANDIDATES_BOLD if bold else _CANDIDATES_REG)
    for pat in ("/usr/share/fonts/**/*Arab*.ttf", "C:/Windows/Fonts/*.ttf",
                "/System/Library/Fonts/**/*.ttf" if sys.platform == "darwin" else ""):
        if not pat:
            continue
        for f in sorted(glob.glob(pat, recursive=True)):
            out.append(f)
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c); uniq.append(c)
    return uniq


def missing_codepoints(path, text):
    """رموز النص غير الموجودة في الخط (تظهر مربعات). None = الفحص غير متاح."""
    if not _fonttools_available():
        return None
    try:
        from fontTools.ttLib import TTFont
        cm = TTFont(path, fontNumber=0, lazy=True).getBestCmap()
    except Exception:
        return ["<FontUnreadable>"]
    return [c for c in text if ord(c) > 0x20 and ord(c) not in cm]


def _strip_symbols(text):
    """يُسقط الإيموجي ورموز الزخرفة غير المدعومة (tofu مضمون في كل الخطوط) —
    فيُرسم باقي النص بدل مربعات. كابشنات تيليجرام مليئة بها (⚽️ 🔥 🚨).
    ⚠️ لا نمسّ أشكال العرض العربية FE70-FEFF (خطوة arabic_reshaper تعتمد عليها)."""
    out = []
    for ch in text:
        o = ord(ch)
        if (0x1F000 <= o <= 0x1FAFF) or (0x2600 <= o <= 0x27BF) or \
           (0x2B00 <= o <= 0x2BFF) or o in (0xFE0F, 0x200D, 0x20E3, 0x23E9):
            continue
        out.append(ch)
    return "".join(out).strip()


def _normalize_text(text):
    """تطبيع النص قبل الرسم:
    1) NFKC — حروف تيليجرام الزخرفية (𝘔𝘦𝘥𝘪𝘢 / 𝐀𝐁𝐂، math-alphanumeric U+1D400+)
       تعود لاتينية عادية بدل tofu (شوهد في كابشنات القناة فعلياً).
    2) إسقاط الإيموجي/الرموز غير المدعومة (⚽️ 🔥) — يُرسم باقي النص بدل مربعات.
    ⚠️ لا نمسّ أشكال العرض العربية FE70-FEFF (خطوة arabic_reshaper تعتمد عليها)."""
    try:
        import unicodedata
        text = unicodedata.normalize("NFKC", text)
    except Exception:
        pass
    return _strip_symbols(text).strip()


def resolve_text(text, bold=True):
    """يرجّع (مسار الخط, النص الجاهز للرسم) لأول تركيبة ترسم كل الرموز فعلاً.
    مع raqm نفضّل **النص الخام** (raqm يشكّله)؛ بلا raqm نجرّب المشكّل ثم الخام.
    يرجّع (None, "") لو ما فيه خط يقدر يرسم النص — أفضل من رسم مربعات."""
    if not text:
        return None, ""
    text = _normalize_text(text)
    if not text:
        return None, ""
    key = (text, bold)
    if key in _SAFE_CACHE:
        return _SAFE_CACHE[key]
    shaped = ar(text)
    if has_raqm():
        variants = [text] if shaped == text else [text, shaped]
    else:
        variants = [shaped] if shaped == text else [shaped, text]
    best = None
    for path in _all_candidates(bold):
        if not path or not os.path.exists(path):
            continue
        if not _tofu_test(path):
            continue
        for ready in variants:
            miss = missing_codepoints(path, ready)
            if miss is not None and not miss:
                _cache_put(_SAFE_CACHE, key, (path, ready))
                return path, ready
            if miss is None:                      # بلا fontTools: نثق بفحص cmap العام
                _cache_put(_SAFE_CACHE, key, (path, ready))
                return path, ready
            if best is None:
                best = (path, ready, len(miss))
    # 🧹 احتياط: أسقط الإيموجي/الرموز غير المدعومة وأعد المحاولة — يُرسم باقي النص
    # بدل تجاهل السطر كله أو رسم مربعات (شوهد: كابشن '[2-0] ⚽️' في المصغّرة).
    stripped = _strip_symbols(text)
    if stripped and stripped != text:
        return resolve_text(stripped, bold)
    _cache_put(_SAFE_CACHE, key, (None, ""))
    if text not in _WARNED:
        _WARNED.add(text)
        msg = (f"[تحذير] ما فيه خط يرسم هذا النص كاملاً: {text[:40]!r} "
               f"(أفضل محاولة: {os.path.basename(best[0]) if best else '-'} ناقص "
               f"{best[2] if best else '-'} رمزاً). شغّل: python font_check.py")
        print(msg, file=sys.stderr)
        try:
            with open("font_warnings.log", "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except Exception:
            pass
    return None, ""


def _split_runs(text):
    """يقسّم النص لأجزاء حسب الكتابة (عربي/غيره) — الرموز المحايدة تُلحق بما قبلها."""
    runs = []
    for ch in text:
        o = ord(ch)
        rtl = 0x0590 <= o <= 0x08FF or 0xFB1D <= o <= 0xFEFF
        neutral = (ch.isspace() or o in (0x2E, 0x40, 0x2F, 0x5F, 0x2D, 0x3A, 0x7C, 0x21,
                                         0x60C, 0x61B, 0x61F))   # . @ / _ - : | ! ، ؛ ؟
        if neutral and runs:
            runs[-1][0] += ch
        elif runs and runs[-1][1] == rtl:
            runs[-1][0] += ch
        else:
            runs.append([ch, rtl])
    return [(r[0], r[1]) for r in runs]


def resolve_run(text, bold=True, rtl=False):
    """(مسار خط, نص جاهز) لأول خط يغطي **كل** رموز هذا الجزء.
    يجرّب الخطوط العربية أولاً، ثم أي خط يغطي الرموز (للاتيني)، ثم خط PIL الافتراضي.
    مع raqm: الجزء العربي يُرسم **خاماً** (raqm يشكّله) — لا نمرّر الشكل المسبق أبداً."""
    if not text:
        return None, ""
    text = _normalize_text(text)
    if not text:
        return None, ""
    key = (text, bold, rtl)
    if key in _SAFE_CACHE:
        return _SAFE_CACHE[key]
    variants = [text] if (not rtl or has_raqm()) else [ar(text), text]
    cands = _all_candidates(bold)
    for pass_no in (1, 2):
        for path in cands:
            if not path or not os.path.exists(path):
                continue
            if pass_no == 1 and not _tofu_test(path):
                continue
            for ready in variants:
                miss = missing_codepoints(path, ready)
                if miss is not None and not miss:
                    _cache_put(_SAFE_CACHE, key, (path, ready))
                    return path, ready
                if miss is None:
                    _cache_put(_SAFE_CACHE, key, (path, ready))
                    return path, ready
    _cache_put(_SAFE_CACHE, key, (None, ""))
    return None, ""


def measure_mixed(d, text, size, bold=True):
    """عرض النص الكلي بالبكسل — يطابق منطق draw_mixed (مع raqm: خط واحد للسطر)."""
    if has_raqm():
        path, ready = resolve_text(text, bold)
        if path and ready == text and _arabic_pref(path):
            font = ImageFont.truetype(path, int(size))
            runs = _split_runs(text)
            kw = {"direction": "rtl"} if (runs and runs[0][1]) else {}
            try:
                return int(d.textlength(text, font=font, **kw))
            except TypeError:
                return int(d.textlength(text, font=font))
    return int(sum(p[2] for p in _prep_mixed(d, text, size, bold)))


def _prep_mixed(d, text, size, bold=True):
    """يجهّز مقاطع النص: [(نص جاهز, خط, عرض, rtl)] — كل مقطع بخط يغطيه.
    القياس بنفس direction الرسم وإلا يختلف العرض (الربطات تغيّر الطول مع raqm)."""
    out = []
    for rtext, rtl in _split_runs(text):
        path, ready = resolve_run(rtext, bold=bold, rtl=rtl)
        if not path:
            continue
        font = ImageFont.truetype(path, int(size))
        kw = {"direction": "rtl"} if (rtl and has_raqm()) else {}
        try:
            w = d.textlength(ready, font=font, **kw)
        except TypeError:
            w = d.textlength(ready, font=font)
        except Exception:
            w = font.getbbox(ready)[2]
        out.append((ready, font, w, rtl))
    return out


def _blit_mixed(d, prepared, runs_rtl, x_center, y_top, fill, align="center"):
    if not prepared:
        return 0
    total = sum(p[2] for p in prepared)
    x = (x_center - total / 2) if align == "center" else float(x_center)
    # الترتيب المنطقي في الحالتين: المؤشر (cur -= w) يضع أول مقطع في أقصى اليمين للـRTL
    seq = prepared
    cur = (x + total) if runs_rtl else x
    for item in seq:
        ready, font, w = item[0], item[1], item[2]
        rtl = item[3] if len(item) > 3 else False
        if runs_rtl:
            cur -= w
            px = cur
        else:
            px = cur
            cur += w
        kw = {"direction": "rtl"} if (rtl and has_raqm()) else {}
        try:
            d.text((px, y_top), ready, font=font, fill=fill, anchor="la", **kw)
        except TypeError:
            d.text((px, y_top), ready, font=font, fill=fill, anchor="la")
    return total


def draw_mixed(d, text, x_center, y_top, size=40, bold=True, fill=(255, 255, 255, 255),
               align="center"):
    """يرسم نصاً قد يخلط العربية باللاتينية: كل جزء بخطه، والترتيب البصري صحيح.
    يرجّع العرض الكلي (0 لو ما انرسم شيء)."""
    runs = _split_runs(text)
    if not runs:
        return 0
    # 🎯 مع raqm: لو خط واحد (عربي) يغطي النص كله نرسمه **دفعة واحدة** — FriBidi يضبط
    # ترتيب المقاطع (رقم لاتيني وسط عربي مثل «الدقيقة 82») بدل ترتيبنا اليدوي الذي يكسره.
    if has_raqm():
        path, ready = resolve_text(text, bold)
        if path and ready == text and _arabic_pref(path):
            font = ImageFont.truetype(path, int(size))
            kw = {"direction": "rtl"} if runs[0][1] else {}
            try:
                w = d.textlength(text, font=font, **kw)
            except TypeError:
                w = d.textlength(text, font=font)
            x = (x_center - w / 2) if align == "center" else float(x_center)
            try:
                d.text((x, y_top), text, font=font, fill=fill, anchor="la", **kw)
            except TypeError:
                d.text((x, y_top), text, font=font, fill=fill, anchor="la")
            return int(w)
    prepared = _prep_mixed(d, text, size, bold)
    if not prepared:
        if text.strip() and text not in _WARNED:
            _WARNED.add(text)
            msg = (f"[تحذير] تعذّر رسم نص: {text[:40]!r} — شغّل python font_check.py")
            print(msg, file=sys.stderr)
            try:
                open("font_warnings.log", "a", encoding="utf-8").write(msg + "\n")
            except Exception:
                pass
        return 0
    return _blit_mixed(d, prepared, runs[0][1], x_center, y_top, fill, align)


def draw_text(img, xy, text, size=40, bold=True, fill=(255, 255, 255, 255), anchor=None):
    """رسم نص عربي مضمون (يرفض المربعات). يرجّع bbox أو None."""
    path, ready = resolve_text(text, bold)
    if not path:
        return None
    f = ImageFont.truetype(path, int(size))
    d = ImageDraw.Draw(img)
    kw = {"anchor": anchor} if anchor else {}
    if has_raqm() and ready == text and _split_runs(text)[:1] and _split_runs(text)[0][1]:
        kw["direction"] = "rtl"
    try:
        d.text(xy, ready, font=f, fill=fill, **kw)
        return d.textbbox(xy, ready, font=f, **kw)
    except TypeError:
        kw.pop("direction", None)
        d.text(xy, ready, font=f, fill=fill, **kw)
        return d.textbbox(xy, ready, font=f, **kw)


def _font(size, bold=True):
    key = (size, bold)
    if key not in _FONT_CACHE:
        path = _find(_CANDIDATES_BOLD if bold else _CANDIDATES_REG, "bold" if bold else "regular")
        _FONT_CACHE[key] = ImageFont.truetype(path, size)
    return _FONT_CACHE[key]


def font_paths():
    """للفحص/التشخيص — يرجّع المسار الكامل + نتيجة اختبار العربية."""
    out = {}
    for label, cands in (("bold", _CANDIDATES_BOLD), ("regular", _CANDIDATES_REG)):
        try:
            p = _find(cands, label)
            out[label] = p
            out[label + "_arabic_ok"] = _tofu_test(p)
        except Exception as e:
            out["error"] = str(e)
    return out


def font_test(out_png="font_test.png", text="هدف رائع للجزائر الجديدة TV"):
    """ينشئ صورة للتحقق البصري من الخط (شغّلها لو شكيت بالمربعات).
    يرسم بالمحرّك المختلط نفسه المستخدم في الإنتاج (draw_mixed) — لا بخط واحد،
    حتى لا تظهر مربعات «TV» الزائفة (الخط العربي لا يحوي لاتينياً بالتصميم)."""
    img = Image.new("RGB", (900, 160), (12, 16, 22))
    d = ImageDraw.Draw(img)
    w = draw_mixed(d, text, 450, 20, size=52, bold=True)
    raqm = "raqm ✓" if has_raqm() else "raqm ✗ (نشكّل يدوياً)"
    draw_mixed(d, f"font: {os.path.basename(_find(_CANDIDATES_BOLD, 'bold'))} | {raqm} | w={w}",
               450, 108, size=26, bold=False, fill=(140, 200, 255))
    img.save(out_png)
    return out_png

def ar(text):
    """Arabic -> visually correct string for PIL (reshape + bidi)."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text

BRAND_Y = 0.76          # فوق منطقة أزرار يوتيوب شورتس (أسفل ~16% من الشاشة)


def draw_brand(img_bgr, name="", url="", accent=(60, 60, 230), y=None, scale=1.0):
    """شريط الهوية: لوحة + خط ملوّن + الاسم + الرابط.
    كل مقطع بخطه (العربية بخط عربي واللاتينية بخط لاتيني) — بلا مربعات."""
    H, W = img_bgr.shape[:2]
    if y is None:
        y = int(H * float(os.environ.get("REEL_BRAND_Y", BRAND_Y)))
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    lay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    nd = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    ns, us = int(64 * scale), int(34 * scale)
    nm = _prep_mixed(nd, name, ns, True) if name else []
    um = _prep_mixed(nd, url, us, False) if url else []
    w_name = sum(p[2] for p in nm)
    w_url = sum(p[2] for p in um)
    w = max(w_name, w_url, 160)
    y_url = y + 20 + int(ns * 1.35)
    cx = W // 2
    plate_h = int(max(y_url + us * 1.5, y + 150) - (y - 24))
    plate = Image.new("RGBA", (int(w) + 60, plate_h), (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        [0, 0, plate.size[0] - 1, plate.size[1] - 1], 26, fill=(0, 0, 0, 95))
    lay.alpha_composite(plate, (cx - plate.size[0] // 2, y - 24))
    d.rounded_rectangle([cx - w // 2 - 8, y - 16, cx + w // 2 + 8, y + 6], 6, fill=accent + (255,))
    if nm:
        _blit_mixed(d, nm, _split_runs(name)[0][1], cx, y + 20, (255, 255, 255, 255))
    if um:
        _blit_mixed(d, um, _split_runs(url)[0][1], cx, y_url, (232, 232, 232, 225))
    out = Image.alpha_composite(pil, lay).convert("RGB")
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)


def source_credit(img_bgr, text, accent=(60, 60, 230), y=None, size=30, dim=0.72):
    """🛡️ سطر إسناد المصدر (Attribution) — يُرسم فوق شريط الهوية.
    جوهره: إظهار أن المادة أصلية لطرف ثالث وأن هذا العمل **تحويلي** (نقد/تحليل/تعليق)،
    وهو ما يدعم اعتراضاً مشروعاً على مطالبة حقوق — لا يُلغي المطالبة بحد ذاته."""
    H, W = img_bgr.shape[:2]
    if not text:
        return img_bgr
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    lay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    nd = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sz = int(size)
    while sz > 16 and measure_mixed(nd, text, sz, False) > W * 0.86:
        sz -= 2
    w = measure_mixed(nd, text, sz, False)
    if y is None:
        y = int(H * 0.72)
    pad = 14
    bx = int(W * 0.5 - w / 2 - pad)
    d.rounded_rectangle([bx, int(y), bx + w + 2 * pad, int(y) + sz + 2 * pad],
                        12, fill=(0, 0, 0, 110))
    d.rounded_rectangle([bx, int(y) + 4, bx + 5, int(y) + sz + 2 * pad - 4], 2, fill=accent + (255,))
    _blit_mixed(d, _prep_mixed(nd, text, sz, False), _split_runs(text)[0][1],
                W / 2 + 3, int(y) + pad, (235, 235, 235, int(255 * dim)))
    out = Image.alpha_composite(pil, lay).convert("RGB")
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)


def tag(canvas, text, x, y, color=(0, 0, 0), alpha=0.55, size=0.62):
    """وسم صغير شبه شفاف (اسم اللوحة في الشاشة المقسومة)."""
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, size, 2)
    pad = 10
    sub = canvas[y:y+th+2*pad, x:x+tw+2*pad]
    if sub.size == 0:
        return canvas
    overlay = sub.copy()
    cv2.rectangle(overlay, (0, 0), (sub.shape[1], sub.shape[0]), color, -1)
    cv2.addWeighted(overlay, alpha, sub, 1-alpha, 0, sub)
    cv2.putText(sub, text, (pad, th+pad-2), cv2.FONT_HERSHEY_SIMPLEX, size,
                (255, 255, 255), 2, cv2.LINE_AA)
    return canvas


def lower_third(canvas, text, y=None, accent=(55, 57, 230), max_chars=46, size=40):
    """شريط نصي سفلي (تعليق/كابشن) بلوحة شبه شفافة + خط ملوّن."""
    H, W = canvas.shape[:2]
    if not text:
        return canvas
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    lines = lines[:3]
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)).convert("RGBA")
    lay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    # 🔧 صغّر الخط حتى يدخل أعرض سطر في اللوحة — التفاف بالأحرف وحدُه يفيض بالنص
    # خارج اللوحة (شوهد سطر 46 حرفاً يخرج عن الشاشة) — القياس بالبكسل الفعلي.
    inner = W * 0.84
    sz = int(size)
    while sz > 22 and lines:
        widest = max((measure_mixed(d, ln, sz, True) for ln in lines), default=0)
        if widest <= inner:
            break
        sz -= 2
    lh = int(sz * 1.5)
    box_h = lh * len(lines) + 26
    if y is None:
        y = H - box_h - int(H * 0.14)
    y = max(0, min(H - box_h, int(y)))
    d.rounded_rectangle([W * 0.06, y, W * 0.94, y + box_h], 16, fill=(6, 10, 14, 180))
    d.rounded_rectangle([W * 0.06, y, W * 0.06 + 7, y + box_h], 4, fill=accent + (255,))
    for i, ln in enumerate(lines):
        draw_mixed(d, ln, W / 2, y + 14 + i * lh, size=sz, bold=True)
    out = Image.alpha_composite(pil, lay).convert("RGB")
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)


_BURST_CACHE = {}


def goal_burst(canvas, t_rel, text="هدف!", accent=(40, 40, 240), y_frac=0.30):
    """انفجار احتفالي متحرّك للحظة الهدف (خط عربي كبير + وهج + تلاشٍ)."""
    H, W = canvas.shape[:2]
    if t_rel < -0.25 or t_rel > 1.75:
        return canvas
    p = min(1.0, max(0.0, (t_rel + 0.25) / 2.0))
    grow = min(1.0, p * 2.6)
    scale = 0.5 + 0.62 * grow + 0.06 * math.sin(min(1.0, p * 3.0) * math.pi)
    alpha = 1.0 if p < 0.72 else max(0.0, 1.0 - (p - 0.72) / 0.28)
    if alpha <= 0.02:
        return canvas
    size = max(24, int(150 * scale))
    step = max(2, size // 14)
    key = (text, size, step)
    if key not in _BURST_CACHE:
        nd = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        prep = _prep_mixed(nd, text, size, True)
        _BURST_CACHE[key] = prep
        if len(_BURST_CACHE) > 60:
            _BURST_CACHE.pop(next(iter(_BURST_CACHE)))
    prep = _BURST_CACHE[key]
    if not prep:
        return canvas
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)).convert("RGBA")
    lay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    cy = int(H * y_frac)
    cxa = int(W / 2)
    a = int(255 * alpha)
    # وهج خلفي
    w_tot = sum(p2[2] for p2 in prep)
    d.rounded_rectangle([cxa - w_tot / 2 - 40, cy - size * 0.72, cxa + w_tot / 2 + 40,
                         cy + size * 0.85], 26, fill=(0, 0, 0, int(120 * alpha)))
    # حدّ ملوّن (رسم النص مُزاحاً) ثم النص الأبيض
    for dx, dy in ((-step, 0), (step, 0), (0, -step), (0, step),
                   (-step, -step), (step, step), (-step, step), (step, -step)):
        _blit_mixed(d, prep, True, cxa + dx, cy + dy, accent + (a,))
    _blit_mixed(d, prep, True, cxa, cy, (255, 255, 255, a))
    out = Image.alpha_composite(pil, lay).convert("RGB")
    return cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)


def ball_marker(canvas, pt, color=(0, 235, 255), r=17):
    """حلقة حول الكرة الحالية — تجعلها واضحة فوراً للمشاهد."""
    ov = canvas.copy()
    cv2.circle(ov, (int(pt[0]), int(pt[1])), r, color, 3, cv2.LINE_AA)
    cv2.circle(ov, (int(pt[0]), int(pt[1])), r + 5, color, 1, cv2.LINE_AA)
    cv2.addWeighted(ov, 0.9, canvas, 0.1, 0, canvas)
    return canvas


def trail(canvas, hist, color=(0, 235, 255), alpha=0.55, max_th=9):
    """hist: deque of (frame_idx, x, y). Draws a fading neon trail on a copy."""
    if len(hist) < 2:
        return canvas
    ov = canvas.copy()
    n = len(hist)
    for i in range(1, n):
        _, x0, y0 = hist[i-1]
        _, x1, y1 = hist[i]
        th = max(2, int(max_th * (i/n)))
        cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), color, th, cv2.LINE_AA)
    cv2.addWeighted(ov, alpha, canvas, 1-alpha, 0, canvas)
    return canvas


# ================================================================ 🖼️ الشعار
LOGO_POSITIONS = ("top-left", "top-center", "top-right",
                  "mid-left", "center", "mid-right",
                  "bottom-left", "bottom-center", "bottom-right")

_POS_ANCHOR = {p: ((p.split("-")[1] if "-" in p else p), (p.split("-")[0] if "-" in p else p))
               for p in LOGO_POSITIONS}
_XA = {"left": 0.0, "center": 0.5, "right": 1.0, "mid": 0.0, "top": 0.0, "bottom": 1.0}
_YA = {"top": 0.0, "center": 0.5, "bottom": 1.0, "mid": 0.5, "left": 0.0, "right": 0.0}


class LogoLayer:
    """طبقة شعار تُركَّب على كل فريم: شفافية + تكبير محفوظ النسبة + خلفية/ظل اختياريان
    + احترام «المنطقة الآمنة» لأزرار يوتيوب شورتس. تُحضَّر مرّة واحدة لكل مقاس (سريعة)."""

    def __init__(self, path, scale=0.16, opacity=0.95, pos="top-right", plate=False,
                 radius=0, margin=0.035, safe=True, shadow=True):
        self.path = path
        self.scale = float(max(0.03, min(0.6, scale)))
        self.opacity = float(max(0.05, min(1.0, opacity)))
        self.pos = pos if pos in LOGO_POSITIONS else "top-right"
        self.plate = bool(plate)
        self.radius = int(radius)
        self.margin = float(max(0.0, min(0.12, margin)))
        self.safe = bool(safe)
        self.shadow = bool(shadow)
        self._cache = {}

    # ---------- تحضير ----------
    def _load(self):
        img = Image.open(self.path).convert("RGBA")
        return img

    def _prepare(self, out_w, out_h):
        key = (int(out_w), int(out_h))
        if key in self._cache:
            return self._cache[key]
        img = self._load()
        tw = max(24, int(round(out_w * self.scale)))
        th = max(12, int(round(img.height * tw / max(1, img.width))))
        img = img.resize((tw, th), Image.LANCZOS)
        if self.radius > 0:
            mask = Image.new("L", (tw, th), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1],
                                                   max(2, self.radius), fill=255)
            img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (tw, th), 0), mask))
        pad = 12 if (self.plate or self.shadow) else 0
        cw, ch = tw + 2 * pad, th + 2 * pad
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        d = ImageDraw.Draw(canvas)
        if self.shadow:
            d.rounded_rectangle([pad - 4, pad - 2, pad + tw + 3, pad + th + 5], 10,
                                fill=(0, 0, 0, 110))
        if self.plate:
            d.rounded_rectangle([pad - 8, pad - 8, pad + tw + 7, pad + th + 7], 14,
                                fill=(8, 10, 14, 140))
        canvas.alpha_composite(img, (pad, pad))
        arr = np.array(canvas)                       # HxWx4 RGBA
        xf, yf = _XA.get(self.pos.split("-")[1] if "-" in self.pos else self.pos, 1.0), \
                 _YA.get(self.pos.split("-")[0] if "-" in self.pos else self.pos, 0.0)
        if self.pos == "center":
            xf = yf = 0.5
        mx, my = int(out_w * self.margin), int(out_h * self.margin)
        x = int(round((out_w - cw) * xf)) if xf >= 0.5 else mx
        if xf == 0.5:
            x = (out_w - cw) // 2
        elif xf == 0.0:
            x = mx
        else:
            x = out_w - cw - mx
        y = my if yf == 0.0 else ((out_h - ch) // 2 if yf == 0.5 else out_h - ch - my)
        if self.safe and yf >= 0.5:
            lim = int(out_h * 0.83)                  # فوق أزرار شورتس
            y = min(y, lim - ch)
        x = max(0, min(out_w - cw, x)); y = max(0, min(out_h - ch, y))
        self._cache[key] = (arr, x, y)
        return self._cache[key]

    # ---------- التركيب ----------
    def apply(self, canvas):
        if not self.path or not os.path.exists(self.path):
            return canvas
        try:
            logo, x, y = self._prepare(canvas.shape[1], canvas.shape[0])
        except Exception:
            return canvas
        h, w = logo.shape[:2]
        if y + h > canvas.shape[0] or x + w > canvas.shape[1]:
            return canvas
        roi = canvas[y:y + h, x:x + w].astype(np.float32)
        a = (logo[:, :, 3:4].astype(np.float32) / 255.0) * self.opacity
        rgb = logo[:, :, 2::-1].astype(np.float32)          # RGBA -> BGR
        canvas[y:y + h, x:x + w] = (roi * (1.0 - a) + rgb * a).astype(np.uint8)
        return canvas


def logo_info(path):
    """معلومات الشعار للوحة التحكم: (عرض, ارتفاع, فيه شفافية)."""
    try:
        im = Image.open(path)
        im = im.convert("RGBA")
        a = np.array(im.getchannel("A"))
        return {"w": im.width, "h": im.height, "alpha": bool(a.min() < 250),
                "ratio": round(im.width / max(1, im.height), 2)}
    except Exception as e:
        return {"error": str(e)[:80]}
