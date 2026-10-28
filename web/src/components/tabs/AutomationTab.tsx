import React, { useState } from 'react';
import { Bot, Play, Square, RefreshCw, Cpu, Activity, ShieldCheck, AlertCircle } from 'lucide-react';
import { AutomationSettings } from '../../types';

interface AutomationTabProps {
  automation: AutomationSettings;
  onSaveAutomation: (updated: AutomationSettings, startNow: boolean) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

export const AutomationTab: React.FC<AutomationTabProps> = ({
  automation,
  onSaveAutomation,
  onToast,
}) => {
  const [local, setLocal] = useState<AutomationSettings>(automation);

  const handleSavePreferences = () => {
    const updated = {
      ...local,
      enabled: false,
      upload: 'none' as const,
      metrics: {
        ...local.metrics,
        statusText: 'غير متصل — تفضيلات الأتمتة نموذجية فقط',
        lastRun: 'غير متاح في النموذج',
        jobsProcessed: 0,
        runsTotal: 0,
        errors: 0,
      },
    };
    setLocal(updated);
    onSaveAutomation(updated, false);
    onToast('حُفظت التفضيلات محلياً فقط؛ لم يبدأ مراقب ولم يُرسل أي فيديو.', 'ok');
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-6 items-start">
      {/* Automation Configuration */}
      <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl">
        <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-3">
          <Bot className="w-5 h-5 text-[#36d1dc]" />
          <span>المصنع التلقائي (Autopilot & Autonomous Watcher)</span>
        </h2>

        <div className={`p-3 rounded-xl border text-xs mb-4 flex items-center gap-2.5 ${
          local.enabled ? 'bg-[#15312f] border-[#235e58] text-[#9fe8c4]' : 'bg-[#182231] border-[#2c3a4d] text-[#aab8ca]'
        }`}>
          <span className={`w-2.5 h-2.5 rounded-full ${local.enabled ? 'bg-[#25d07a] shadow-[0_0_8px_#25d07a]' : 'bg-[#8ea0b5]'}`} />
          <span>{local.metrics.statusText}</span>
        </div>

        <p className="text-xs text-[#8ea0b5] mb-4 leading-relaxed">
          هذه الشاشة تحفظ تفضيلات العرض فقط. لا تراقب قناة أو مجلداً، ولا تنزّل مقاطع أو تشغّل الرندر أو النشر.
        </p>

        {/* Inputs */}
        <div className="space-y-3 text-xs">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">مصدر المقاطع</label>
            <select
              value={local.source}
              onChange={e => setLocal({ ...local, source: e.target.value as any })}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="telegram">قناة تيليجرام</option>
              <option value="folder">مجلد محلي (watch/)</option>
              <option value="both">تيليجرام + مجلد محلي</option>
            </select>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">قناة تيليجرام العامة</label>
              <input
                type="text"
                value={local.channel}
                onChange={e => setLocal({ ...local, channel: e.target.value })}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
              />
            </div>
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">المجلد المحلي</label>
              <input
                type="text"
                value={local.folder}
                onChange={e => setLocal({ ...local, folder: e.target.value })}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
              />
            </div>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">
              ملف مراجعة الحقوق للنشر التلقائي (Rights Manifest)
            </label>
            <input
              type="text"
              value={local.rightsManifest}
              onChange={e => setLocal({ ...local, rightsManifest: e.target.value })}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            />
            <p className="text-[10px] text-[#8ea0b5] mt-1 leading-normal">
              🔒 حماية الحقوق: يجب أن يطابق كل سجل رابط المصدر بدقة. في حال غياب السجل لن يُرسل المقطع تلقائياً للوجهة العامة.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">الفحص كل (ثانية)</label>
              <input
                type="number"
                min={30}
                value={local.interval}
                onChange={e => setLocal({ ...local, interval: Number(e.target.value) })}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
              />
            </div>
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">عدد المقاطع لكل دورة</label>
              <input
                type="number"
                min={1}
                max={50}
                value={local.limit}
                onChange={e => setLocal({ ...local, limit: Number(e.target.value) })}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">الجودة</label>
              <select
                value={local.quality}
                onChange={e => setLocal({ ...local, quality: e.target.value })}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
              >
                <option value="auto">auto</option>
                <option value="high">high</option>
                <option value="balanced">balanced</option>
                <option value="fast">fast</option>
                <option value="ultra">ultra</option>
              </select>
            </div>
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">التخطيط</label>
              <select
                value={local.layout}
                onChange={e => setLocal({ ...local, layout: e.target.value })}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
              >
                <option value="single">ريل عادي (9:16)</option>
                <option value="split">شاشة مقسومة</option>
              </select>
            </div>
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">الكاميرا</label>
              <select
                value={local.subject}
                onChange={e => setLocal({ ...local, subject: e.target.value })}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
              >
                <option value="action">مساحة اللعب</option>
                <option value="ball">الكرة</option>
                <option value="player">اللاعب</option>
              </select>
            </div>
          </div>

          <div className="rounded-lg border border-[#664c30] bg-[#282114] p-3 text-[11px] leading-relaxed text-[#e5c99a]">
            النشر غير متاح في النموذج؛ لن يُرسل أي فيديو إلى YouTube أو Telegram.
          </div>
        </div>

        <div className="mt-5">
          <button
            onClick={handleSavePreferences}
            className="flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>حفظ التفضيلات المحلية فقط</span>
          </button>
        </div>
      </div>

      {/* Operating Metrics & Hardware Status */}
      <div className="space-y-6">
        <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl">
          <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-3">
            <Activity className="w-4 h-4 text-[#36d1dc]" />
            <span>معلومات نموذجية — لا توجد إحصاءات تشغيل فعلية</span>
          </h2>

          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="p-3 rounded-xl bg-[#080d13]/60 border border-[#222e3d]">
              <span className="text-[#8ea0b5] block mb-1">آخر فحص</span>
              <b className="text-white text-sm">غير متاح في النموذج</b>
            </div>

            <div className="p-3 rounded-xl bg-[#080d13]/60 border border-[#222e3d]">
              <span className="text-[#8ea0b5] block mb-1">المهام المعالجة</span>
              <b className="text-[#25d07a] text-sm">غير متاح</b>
            </div>

            <div className="p-3 rounded-xl bg-[#080d13]/60 border border-[#222e3d]">
              <span className="text-[#8ea0b5] block mb-1">الدورات المكتملة</span>
              <b className="text-[#3b82f6] text-sm">غير متاح</b>
            </div>

            <div className="p-3 rounded-xl bg-[#080d13]/60 border border-[#222e3d]">
              <span className="text-[#8ea0b5] block mb-1">أخطاء التنزيل/الحقوق</span>
              <b className="text-[#ff9aa2] text-sm">غير متاح</b>
            </div>
          </div>
        </div>

        {/* Hardware Status */}
        <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl">
          <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-3">
            <Cpu className="w-4 h-4 text-[#25d07a]" />
            <span>حالة العتاد والتسريع (Hardware Acceleration)</span>
          </h2>

          <div className="space-y-2.5 text-xs">
            <div className="flex justify-between items-center p-2.5 rounded-lg bg-[#0c1219] border border-[#222e3d]">
              <span className="text-[#8ea0b5]">محرّك الفيديو/التتبّع:</span>
              <span className="text-[#e5c99a] font-bold">غير متصل بالنموذج</span>
            </div>

            <div className="flex justify-between items-center p-2.5 rounded-lg bg-[#0c1219] border border-[#222e3d]">
              <span className="text-[#8ea0b5]">ترميز الفيديو:</span>
              <span className="text-[#e5c99a] font-bold">غير متاح في النموذج</span>
            </div>

            <div className="flex justify-between items-center p-2.5 rounded-lg bg-[#0c1219] border border-[#222e3d]">
              <span className="text-[#8ea0b5]">العتاد:</span>
              <span className="text-white font-mono">غير مفحوص من المتصفح</span>
            </div>

            <div className="flex justify-between items-center p-2.5 rounded-lg bg-[#0c1219] border border-[#222e3d]">
              <span className="text-[#8ea0b5]">التعافي من أخطاء الرندر:</span>
              <span className="text-[#e5c99a] font-bold">غير متصل بالنموذج</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
