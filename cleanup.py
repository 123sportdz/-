#!/usr/bin/env python3
"""cleanup — تنظيف مساحة C: وبقايا التشغيل.

  python cleanup.py                 # تقرير + حذف بقايا مجلدات العمل (آمن تماماً)
  python cleanup.py --scan          # تقرير فقط، بلا حذف
  python cleanup.py --incoming-days 3   # + فيديوهات نزّلتها قبل 3 أيام
  python cleanup.py --outputs-days 14   # + ريلز أنتجتها قبل 14 يوماً
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.abspath(__file__))

try:
    from reelkit.ffio import setup_tempdir
    setup_tempdir(ROOT)
    from reelkit import space as SP
except Exception as e:
    print("تعذّر تحميل reelkit:", e)
    sys.exit(1)


def show(d):
    print("  الأقراص:")
    for x in d["drives"]:
        bar = ""
        if x["total"]:
            used = 100.0 * (x["total"] - x["free"]) / x["total"]
            bar = "  " + "█" * int(used / 5) + "░" * (20 - int(used / 5))
        print(f"    {x['drive']:4s} متاح {x['free_h']:>9s} من {x['total_h']:>9s}{bar}"
              + ("   ⚠️ مساحة ضعيفة!" if x["free"] < 3 * 1024 ** 3 else ""))
    print(f"  مجلد النظام المؤقت : {d['sys_temp']}")
    print(f"  مجلد عمل المشروع   : {d['work_temp']}  ({SP.human(d['work_temp_size'])})")
    print(f"  بقايا في TEMP      : {len(d['leftovers'])} مجلد — {SP.human(d['leftovers_size'])}")
    print(f"  التنزيلات (incoming): {SP.human(d['incoming_size'])}")
    print(f"  المخرجات (outputs) : {SP.human(d['outputs_size'])}")
    for x in d["leftovers"][:6]:
        print(f"      • {os.path.basename(x['path'])}  {x['size_h']}  (عمرها {x['age_h']} ساعة)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="تقرير فقط بلا حذف")
    ap.add_argument("--incoming-days", type=float, default=None,
                    help="احذف تنزيلات أقدم من N يوم (يحفظ cache_*.mp4)")
    ap.add_argument("--outputs-days", type=float, default=None, help="احذف مخرجات أقدم من N يوم")
    ap.add_argument("--all-incoming", action="store_true", help="احذف كل التنزيلات")
    a = ap.parse_args()

    inc = os.path.join(ROOT, "incoming")
    out = os.path.join(ROOT, "outputs")
    print("=" * 58)
    print("  elhadath-reels — المساحة والتنظيف")
    print("=" * 58)
    d = SP.scan(ROOT, inc, out)
    show(d)
    if a.scan:
        print("\n(تقرير فقط — لم يُحذف شيء)")
        return 0
    n, freed = SP.clean_temp(ROOT)
    print(f"\n🧹 بقايا مجلدات العمل: حُذف {n} مجلد — وفّرنا {SP.human(freed)}")
    if a.incoming_days is not None:
        n2, f2 = SP.clean_files(inc, days=a.incoming_days, only_prefix=None, keep_prefix="cache_")
        print(f"🎞️  تنزيلات أقدم من {a.incoming_days:g} يوم: حُذف {n2} — وفّرنا {SP.human(f2)}")
    if a.all_incoming:
        n2, f2 = SP.clean_files(inc, days=0, keep_prefix=None)
        print(f"🎞️  كل التنزيلات: حُذف {n2} — وفّرنا {SP.human(f2)}")
    if a.outputs_days is not None:
        n3, f3 = SP.clean_files(out, days=a.outputs_days)
        print(f"🎬 مخرجات أقدم من {a.outputs_days:g} يوم: حُذف {n3} — وفّرنا {SP.human(f3)}")
    d2 = SP.scan(ROOT, inc, out)
    print("\nبعد التنظيف:")
    for x in d2["drives"][:3]:
        print(f"    {x['drive']:4s} متاح {x['free_h']}")
    if freed < 1024 ** 2:
        print("\n💡 لو C: لسا ممتلئ: افتح مجلد TEMP واحذف يدوياً أي مجلدات كبيرة قديمة،")
        print(f"   أو نفّذ:  python cleanup.py --incoming-days 2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
