"""title — auto title/description/tags for a clip: OCR the broadcast scoreboard.

The scoreboard sits top-left in the 7LLE-style reposts (normalized box below).
`--calibrate` prints the crop so you can adapt SCORE_BOX for another source.
"""
import re, sys
import numpy as np
from . import ffio

SCORE_BOX = (0.00, 0.00, 0.30, 0.115)     # normalized x1,y1,x2,y2 (top-left scoreboard)

TEAMS = {
    "ALG": "الجزائر", "BDI": "بوروندي", "MAR": "المغرب", "TUN": "تونس", "EGY": "مصر",
    "NGA": "نيجيريا", "SEN": "السنغال", "GHA": "غانا", "CMR": "الكاميرون",
    "CIV": "ساحل العاج", "MLI": "مالي", "BFA": "بوركينا فاسو", "GUI": "غينيا",
    "RSA": "جنوب إفريقيا", "COD": "الكونغو الديمقراطية", "TAN": "تنزانيا",
    "KEN": "كينيا", "UGA": "أوغندا", "ZAM": "زامبيا", "ANG": "أنغولا",
    "MOZ": "موزمبيق", "LBY": "ليبيا", "SDN": "السودان", "ETH": "إثيوبيا",
    "GAB": "الغابون", "CGO": "الكونغو", "NIG": "النيجر", "MTN": "موريتانيا",
    "FRA": "فرنسا", "BRA": "البرازيل", "ARG": "الأرجنتين", "ENG": "إنجلترا",
    "ESP": "إسبانيا", "GER": "ألمانيا", "POR": "البرتغال", "ITA": "إيطاليا",
    "NED": "هولندا", "BEL": "بلجيكا", "CRO": "كرواتيا", "SUI": "سويسرا",
    "USA": "أمريكا", "MEX": "المكسيك", "JPN": "اليابان", "KSA": "السعودية",
    "QAT": "قطر", "IRN": "إيران", "IRQ": "العراق", "JOR": "الأردن",
}

def _median_crop(path, box=SCORE_BOX, n=40):
    """path may be AV1/anything — it gets normalized to H.264 first."""
    import cv2
    tmp = None
    cap = None
    try:
        with ffio._quiet():
            if not ffio._can_open(path):
                tmp = ffio.mktempdir()
                path = ffio.ensure_readable(path, tmp)
        cap = cv2.VideoCapture(path)
        N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if N <= 0:
            return None
        idx = np.linspace(0, N-1, min(n, N)).astype(int)
        fr = []
        for i in idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, f = cap.read()
            if ok:
                fr.append(f)
        if not fr:
            return None
        med = np.median(np.stack(fr), 0).astype(np.uint8)
        H, W = med.shape[:2]
        x1, y1, x2, y2 = box
        return med[int(y1*H):int(y2*H), int(x1*W):int(x2*W)]
    finally:
        if cap is not None:
            cap.release()
        if tmp:
            ffio.cleanup(tmp)

def read_scoreboard(path, box=SCORE_BOX):
    """Returns (raw_text, {'teams': [...], 'score': (a,b), 'clock': 'mm:ss'})."""
    try:
        import cv2, pytesseract
    except Exception:                       # OCR اختياري؛ غياب الحزمة لا يكسر شيئاً
        return "", {}
    # OCR اختياري؛ غيابه لا يجب أن يمنع إنشاء الريل أو العنوان البديل.
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return "", {}
    try:
        crop = _median_crop(path, box)
    except Exception:                       # ملف غير مقروء/ffmpeg فشل ⇒ لا نُصعّد الخطأ
        return "", {}
    if crop is None or crop.size == 0:
        return "", {}
    try:
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (g.shape[1]*4, g.shape[0]*4), interpolation=cv2.INTER_CUBIC)
        g = cv2.GaussianBlur(g, (0, 0), 1.0)
        _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        txt = pytesseract.image_to_string(th, lang="eng", config="--psm 6")
    except Exception:
        return "", {}
    raw = " ".join(txt.split())
    info = {}
    codes = [c for c in re.findall(r"\b([A-Z]{2,4})\b", raw) if c in TEAMS]
    if codes:
        info["teams"] = codes[:2]
    m = re.search(r"(\d)\s*[-–—]\s*(\d)", raw)
    if m:
        info["score"] = (int(m.group(1)), int(m.group(2)))
    m = re.search(r"(\d{1,3}):(\d{2})", raw)
    if m:
        info["clock"] = f"{m.group(1)}:{m.group(2)}"
    return raw, info

def suggest(path, brand="الحدث", keywords=()):
    """Build an Arabic title + description + tags from the scoreboard."""
    raw, info = read_scoreboard(path)
    teams = [TEAMS.get(c, c) for c in info.get("teams", [])]
    score = info.get("score")
    clock = info.get("clock")
    if len(teams) >= 2 and score:
        core = f"{teams[0]} {score[0]}-{score[1]} {teams[1]}"
    elif len(teams) >= 2:
        core = f"{teams[0]} × {teams[1]}"
    elif len(teams) == 1:
        core = f"مباراة {teams[0]}"
    else:
        core = "مقطع من المباراة"
    title = f"{core} — هدف رائع"
    if clock:
        title += f" | الدقيقة {clock.split(':')[0]}"
    desc_lines = [f"{core}", ""]
    if clock:
        desc_lines.append(f"⏱ الدقيقة {clock}")
    desc_lines += ["", "تابعونا لكل الأهداف واللقطات الحصرية.", f"#{brand}"]
    tags = list(dict.fromkeys([*teams, "كرة القدم", "أهداف", "الجزائر", *keywords]))
    return dict(title=title[:100], description="\n".join(desc_lines), tags=tags,
                raw_ocr=raw, info=info)

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--calibrate":
        import cv2
        c = _median_crop(sys.argv[2])
        cv2.imwrite("scoreboard_crop.png", c)
        print("saved scoreboard_crop.png", c.shape if c is not None else None)
    else:
        import json
        print(json.dumps(suggest(sys.argv[1]), ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- caption parsing
ORD = {"أول": "الأول", "اول": "الأول", "ثانٍ": "الثاني", "ثان": "الثاني", "ثاني": "الثاني",
       "ثالث": "الثالث", "رابع": "الرابع", "خامس": "الخامس"}
NOISE = re.compile(r"\(?\bOFFSIDE\b\)?|Media\s*Offside|تـ?سـ?جـ?يـ?ل\s*الـ?مـ?باریـ?ات", re.I)

def clean_caption(text):
    """يشيل ضجيج واجهة تيليجرام من الكابشن (عدّاد مشاهدات، تفاعلات، بقايا HTML…)."""
    t = html_unescape(text or "")
    t = NOISE.sub(" ", t)
    t = re.sub(r"This media is not supported[^\n]*", " ", t)
    t = re.sub(r"VIEW IN TELEGRAM|VIEW IN CHANNEL", " ", t)
    t = re.sub(r"Forwarded from[^|\n]*", " ", t)
    t = re.sub(r"\d+\s*views.*$", " ", t, flags=re.S)
    t = re.sub(r"[❤🔥👍😂🤬👏😮🤍🎯]{1,2}\s*\d+", " ", t)
    t = re.sub(r"<[^>]*$", " ", t)
    t = re.sub(r"\b\d{1,2}:\d{2}\b", " ", t)
    t = re.sub(r"^[\s>|]*", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .|،")
    return t


def from_caption(text, brand="الحدث"):
    """يحوّل كابشن رسالة تيليجرام إلى (عنوان، وصف، تاجات).
    مثال: "د82' | هدف ثانٍ لـ المغرب ضد ليسوتو. [2-0] ⚽️ عز الدين"
      -> "هدف المغرب الثاني ضد ليسوتو | الدقيقة 82 (2-0)"
    """
    t = html_unescape(text or "")
    t = NOISE.sub(" ", t)
    t = re.sub(r"Forwarded from[^|\n]*", " ", t)
    minute = re.search(r"[دD]\s*(\d{1,3})\s*['’]", t)
    score = re.search(r"\[\s*(\d)\s*[-–]\s*(\d)\s*\]", t)
    m = re.search(r"هدف\s*(أول|اول|ثانٍ|ثان|ثاني|ثالث|رابع|خامس)?\s*لـ?\s*([^\.\n\[]+?)\s*(?:ضد|vs\.?|أمام)\s*([^\.\n\[]+)", t)
    teams = None
    if m:
        teams = (m.group(2).strip(" .،,|\""), m.group(3).strip(" .،,|\""))
    core = ""
    if teams:
        core = f"هدف {teams[0]}"
        if m.group(1):
            core += f" {ORD.get(m.group(1), m.group(1))}"
        core += f" ضد {teams[1]}"
    elif "هدف" in t:
        core = "هدف"
    parts = [core] if core else []
    if minute: parts.append(f"الدقيقة {minute.group(1)}")
    if score:  parts.append(f"({score.group(1)}-{score.group(2)})")
    title = " | ".join([p for p in parts if p]) or (t.strip()[:90] or "مقطع من المباراة")
    # الهداف (سطر الإيموجي)
    scorer = ""
    sm = re.search(r"⚽️?\s*([^.\[\]\n]{3,40})", t)
    if sm: scorer = sm.group(1).strip(" .،,|'\"")
    desc = [title, ""]
    if scorer: desc.append(f"⚽️ {scorer}")
    clean = clean_caption(t)
    if clean: desc += ["", clean]
    desc += ["", "تابعونا لكل الأهداف واللقطات الحصرية.", f"#{brand}"]
    tags = [x for x in [*(teams or ()), "كرة القدم", "أهداف", "ملخص", "هداف", brand] if x]
    tags = list(dict.fromkeys(tags))[:12]
    return {"title": title[:100], "description": "\n".join(desc), "tags": tags,
            "minute": minute.group(1) if minute else None,
            "score": f"{score.group(1)}-{score.group(2)}" if score else None,
            "teams": teams}

def html_unescape(s):
    import html as _h
    return _h.unescape(s or "")
