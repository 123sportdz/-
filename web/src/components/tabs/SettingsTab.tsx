import React, { useState } from 'react';
import { Settings, Sparkles, Save, Trash2 } from 'lucide-react';
import { AppSettings } from '../../types';
import { storage } from '../../services/storage';

interface SettingsTabProps {
  settings: AppSettings;
  onSaveSettings: (settings: AppSettings) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

export const SettingsTab: React.FC<SettingsTabProps> = ({
  settings,
  onSaveSettings,
  onToast,
}) => {
  const [form, setForm] = useState<AppSettings>(settings);

  const handleSave = () => {
    onSaveSettings(form);
    onToast('حُفظت تفضيلات هذا النموذج في المتصفح؛ المفاتيح لا تُحفظ بشكل دائم.', 'ok');
  };

  const handleClearStorage = () => {
    if (confirm('سيُمسح محتوى elhadath-reels المحفوظ فقط في هذا المتصفح. هل تريد المتابعة؟')) {
      storage.clearAppData();
      window.location.reload();
    }
  };

  return (
    <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-6 shadow-xl max-w-4xl mx-auto text-xs">
      <h2 className="text-base font-bold text-[#cfdcec] flex items-center gap-2 mb-2">
        <Settings className="w-5 h-5 text-[#36d1dc]" />
        <span>تفضيلات واجهة النموذج</span>
      </h2>
      <p className="text-xs text-[#e5c99a] bg-[#282114] border border-[#664c30] rounded-lg p-3 mb-6 leading-relaxed">
        هذه واجهة تجريبية غير متصلة بالخادم. التفضيلات العادية تُحفظ في المتصفح؛ مفتاح Gemini — إن أُدخل — يبقى في جلسة التبويب فقط وغير مشفّر، ويُرسل نص الطلب إلى Google فقط بعد موافقة منفصلة لكل توليد. لا تُدخل توكن تيليجرام أو أسراراً أخرى هنا.
      </p>

      {/* Brand & Identity */}
      <div className="space-y-4 pb-6 border-b border-[#222e3d]">
        <h3 className="text-sm font-bold text-white">الهوية وشارة القناة</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">اسم الهوية (يُرسم على الريل)</label>
            <input
              type="text"
              value={form.brand_name}
              onChange={e => setForm({ ...form, brand_name: e.target.value })}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">الرابط / الهاندل الرسمي</label>
            <input
              type="text"
              value={form.brand_url}
              onChange={e => setForm({ ...form, brand_url: e.target.value })}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
        </div>

        <label className="flex items-center gap-2 text-[#cfdcec] font-semibold cursor-pointer">
          <input
            type="checkbox"
            checked={form.show_channel_name}
            onChange={e => setForm({ ...form, show_channel_name: e.target.checked })}
            className="rounded"
          />
          <span>إظهار اسم القناة افتراضياً في المقاطع الجديدة</span>
        </label>
      </div>

      {/* Telegram Bot & Channels */}
      <div className="space-y-4 py-6 border-b border-[#222e3d]">
        <h3 className="text-sm font-bold text-white">تيليجرام ويوتيوب</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">قناة تيليجرام الافتراضية (للسحب)</label>
            <input
              type="text"
              value={form.telegram_channel}
              onChange={e => setForm({ ...form, telegram_channel: e.target.value })}
              placeholder="@OffsideOffside1"
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">معرّف قناة يوتيوب (Channel ID)</label>
            <input
              type="text"
              value={form.youtube_channel_id}
              onChange={e => setForm({ ...form, youtube_channel_id: e.target.value })}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="rounded-xl border border-[#664c30] bg-[#282114] p-3 text-[11px] leading-relaxed text-[#e5c99a]">
            لا يوجد اتصال Telegram هنا. لا تُدخل أو تلصق أي توكن.
          </div>
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">معرّف القناة (تفضيل للعرض فقط)</label>
            <input
              type="text"
              value={form.telegram_chat}
              onChange={e => setForm({ ...form, telegram_chat: e.target.value })}
              placeholder="@mychannel"
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">خصوصية يوتيوب الافتراضية</label>
            <select
              value={form.youtube_privacy}
              onChange={e => setForm({ ...form, youtube_privacy: e.target.value as any })}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white font-medium"
            >
              <option value="private">private (خاص — موصى به للفحص)</option>
              <option value="unlisted">unlisted (غير مدرج)</option>
              <option value="public">public (عام للمشتركين)</option>
            </select>
          </div>
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">دُفعة الكشف على GPU (Batch Size)</label>
            <input
              type="number"
              min={0}
              max={32}
              value={form.batch_size}
              onChange={e => setForm({ ...form, batch_size: Number(e.target.value) })}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
        </div>
      </div>

      <div className="space-y-4 py-6 border-b border-[#222e3d]">
        <h3 className="text-sm font-bold text-white">حسابات النشر</h3>
        <div className="rounded-xl border border-[#664c30] bg-[#282114] p-3 text-[11px] leading-relaxed text-[#e5c99a]">
          ربط Telegram/YouTube، رمز QR، وجدولة النشر غير مطبّقة في هذا النموذج. لا تُدخل أرقام هاتف أو أكواد دخول أو توكنات هنا؛ استخدم لوحة الخادم الحقيقية عند الحاجة.
        </div>
      </div>

      {/* Gemini AI Settings */}
      <div className="space-y-4 py-6 border-b border-[#222e3d]">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[#f0b429]" />
          <h3 className="text-sm font-bold text-white">الذكاء الاصطناعي (Gemini)</h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">مفتاح Gemini API (اختياري)</label>
            <input
              type="password"
              value={form.gemini_api_key}
              onChange={e => setForm({ ...form, gemini_api_key: e.target.value })}
              placeholder="AQ.Ab8..."
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white font-mono"
            />
          </div>
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">موديل Gemini</label>
            <input
              type="text"
              value={form.gemini_model}
              onChange={e => setForm({ ...form, gemini_model: e.target.value })}
              placeholder="gemini-2.5-flash"
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={form.auto_ai_title}
              onChange={e => setForm({ ...form, auto_ai_title: e.target.checked })}
              className="rounded"
            />
            <span>✨ صياغة عنوان كروي جذاب تلقائياً</span>
          </label>

          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={form.schedule_peak}
              onChange={e => setForm({ ...form, schedule_peak: e.target.checked })}
              className="rounded"
            />
            <span>🕗 جدولة النشر في أوقات الذروة (19:00 / 21:30 بتوقيت الجزائر)</span>
          </label>

          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={form.auto_translate}
              onChange={e => setForm({ ...form, auto_translate: e.target.checked })}
              className="rounded"
            />
            <span>🌍 ترجمة العنوان (EN/FR) في الوصف والوسوم</span>
          </label>
        </div>
      </div>

      {/* Save and Reset Actions */}
      <div className="flex items-center justify-between gap-3 pt-6 flex-wrap">
        <button
          onClick={handleSave}
          className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#e63946] to-[#b3212c] hover:brightness-110 shadow-lg shadow-[#e63946]/30 transition"
        >
          <Save className="w-4 h-4" />
          <span>💾 احفظ التفضيلات في المتصفح</span>
        </button>

        <button
          onClick={handleClearStorage}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs text-[#ff9aa2] hover:bg-[#e63946]/10 transition"
        >
          <Trash2 className="w-3.5 h-3.5" />
          <span>إعادة ضبط المصنع المحلي</span>
        </button>
      </div>
    </div>
  );
};
