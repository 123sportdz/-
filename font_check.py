#!/usr/bin/env python3
"""font_check.py — تشخيص خط الهوية العربية (يمنع ظهور مربعات ▯▯▯ بدل النص)."""
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def main():
    from reelkit import graphics as G
    print("=" * 62); print("  فحص خط الهوية العربية"); print("=" * 62)
    print("\n[1] سلامة الخطوط المرفقة مع المشروع:")
    for name, info in G.asset_files_ok().items():
        flag = "✅" if info["ok"] else "❌"
        extra = "" if info["ok"] else "  ← تالف/ناقص! أعد فك ضغط الحزمة كاملة"
        print(f"  {flag} {name}: {info['size']} بايت (المتوقع {info['expected']}){extra}")
    print("\n[2] الخط المختار فعلاً:")
    fp = G.font_paths()
    if fp.get("error"):
        print("  ❌", fp["error"])
    else:
        for label in ("bold", "regular"):
            if fp.get(label):
                ar, fe = G.arabic_coverage(fp[label])
                print(f"  {label}: {'✅' if fp.get(label+'_arabic_ok') else '❌'} "
                      f"{os.path.basename(fp[label])} | حروف عربية={ar} أشكال عرض={fe}")
                print(f"        المسار: {fp[label]}")
    print("\n[3] كل الخطوط المرشّحة (بالترتيب):")
    for label, cands in (("bold ", G._CANDIDATES_BOLD), ("regul", G._CANDIDATES_REG)):
        for c in cands:
            if not c:
                continue
            if os.path.exists(c):
                ar, fe = G.arabic_coverage(c)
                ok = "✅" if G._tofu_test(c) else "❌"
                print(f"  {ok} [{label}] {os.path.basename(c):32s} عربي={ar:4d} أشكال={fe:4d}")
            else:
                print(f"  ─  [{label}] غير موجود: {c[:64]}")
    p = G.font_test(str(ROOT / "font_test.png"))
    print(f"\n📄 صورة اختبار: {p}")
    print("   افتحها — لازم تشوف: «هدف رائع للجزائر الجديدة TV» بحروف عربية واضحة.")
    print("   لو شفت مربعات ▯▯▯ فابعث هذه الصورة + ناتج هذا الأمر.")

if __name__ == "__main__":
    main()
