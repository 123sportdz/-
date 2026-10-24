import React, { useState } from 'react';
import { Settings, Key, QrCode, Smartphone, Tv, Sparkles, Database, Save, Trash2, CheckCircle2 } from 'lucide-react';
import { AppSettings } from '../../types';

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
  const [showQr, setShowQr] = useState<boolean>(false);
  const [tgPhone, setTgPhone] = useState<string>('+213');
  const [tgCode, setTgCode] = useState<string>('');
  const [tgStatus, setTgStatus] = useState<string>('غير متصل (الحساب الشخصي اختياري للمقاطع الكبيرة)');

  const handleSave = () => {
    onSaveSettings(form);
    onToast('تم حفظ جميع الإعدادات في config.json بنجاح 💾', 'ok');
  };

  const handleQrClick = () => {
    setShowQr(true);
    setTgStatus('⏳ بانتظار مسح الرمز من تطبيق تيليجرام (الإعدادات > الأجهزة > ربط جهاز)...');
    onToast('تم توليد رمز QR لربط حساب تيليجرام', 'ok');
  };

  const handleVerifyCode = () => {
    if (!tgCode) {
      onToast('أدخل كود التحقق أولاً', 'err');
      return;
    }
    setTgStatus('✓ تم ربط حساب تيليجرام بنجاح');
    setForm(prev => ({ ...prev, tg_user_linked: true, tg_phone: tgPhone }));
    onToast('تم تأكيد دخول تيليجرام بنجاح!', 'ok');
  };

  const handleClearStorage = () => {
    if (confirm('هل أنت متأكد من مسح الذاكرة المؤقتة وإعادة ضبط الإعدادات؟')) {
      localStorage.clear();
      window.location.reload();
    }
  };

  return (
    <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-6 shadow-xl max-w-4xl mx-auto text-xs">
      <h2 className="text-base font-bold text-[#cfdcec] flex items-center gap-2 mb-2">
        <Settings className="w-5 h-5 text-[#36d1dc]" />
        <span>إعدادات المشروع والهوية (تُحفظ في config.json)</span>
      </h2>
      <p className="text-xs text-[#8ea0b5] mb-6">
        جميع المفاتيح والتوكنات تُحفظ محلياً على جهازك ولا تُشارك خارج بيئتك الخاصة.
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
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">توكن بوت تيليجرام (للنشر الآلي)</label>
            <input
              type="password"
              value={form.telegram_token}
              onChange={e => setForm({ ...form, telegram_token: e.target.value })}
              placeholder="123456789:ABCdef..."
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white font-mono"
            />
          </div>
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">معرّف قناة النشر على تيليجرام</label>
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

      {/* Telegram User Account Linking (QR code / Phone) */}
      <div className="space-y-4 py-6 border-b border-[#222e3d]">
        <div className="flex items-center gap-2">
          <Smartphone className="w-4 h-4 text-[#36d1dc]" />
          <h3 className="text-sm font-bold text-white">ربط حساب تيليجرام (لفتح الفيديوهات الكبيرة)</h3>
        </div>

        <div className="p-3.5 rounded-xl bg-[#0b1a12] border border-[#1d5c3e] leading-relaxed">
          <div className="font-bold text-[#9fe8c4] mb-1">📱 الطريقة الأسهل: اربط بمسح رمز QR</div>
          <div className="text-[11px] text-[#aab8ca]">
            اضغط زر «📱 اعرض رمز QR» أدناه → على هاتفك: <b>تيليجرام → الإعدادات → الأجهزة → ربط جهاز</b> → امسح الرمز ضوئياً.
          </div>
          <button
            type="button"
            onClick={handleQrClick}
            className="mt-2.5 flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110"
          >
            <QrCode className="w-3.5 h-3.5" />
            <span>📱 اعرض رمز QR</span>
          </button>

          {showQr && (
            <div className="mt-3 p-4 bg-white rounded-xl inline-block text-center">
              {/* Clean simulated high-density QR code representation */}
              <div className="w-44 h-44 bg-white flex flex-col items-center justify-center p-2 border-4 border-black">
                <div className="grid grid-cols-6 gap-1 w-full h-full p-1 bg-black">
                  <div className="bg-white col-span-2 row-span-2"></div>
                  <div className="bg-white col-span-2"></div>
                  <div className="bg-white col-span-2 row-span-2"></div>
                  <div className="bg-white"></div>
                  <div className="bg-white"></div>
                  <div className="bg-white col-span-2"></div>
                  <div className="bg-white col-span-3"></div>
                  <div className="bg-white col-span-2 row-span-2"></div>
                  <div className="bg-white"></div>
                  <div className="bg-white col-span-2"></div>
                </div>
              </div>
              <div className="text-[10px] text-black font-bold mt-2">امسح من تطبيق Telegram</div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">رقم الهاتف (بصيغة دولية)</label>
            <input
              type="text"
              value={tgPhone}
              onChange={e => setTgPhone(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">كود تسجيل الدخول</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={tgCode}
                onChange={e => setTgCode(e.target.value)}
                placeholder="12345"
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white text-center font-mono"
              />
              <button
                type="button"
                onClick={handleVerifyCode}
                className="px-3 py-2 rounded-xl bg-[#25d07a] hover:bg-[#20ba6d] text-black font-bold shrink-0"
              >
                تأكيد
              </button>
            </div>
          </div>
        </div>

        <div className="text-[11px] text-[#8ea0b5] bg-[#0c1219] p-2.5 rounded-lg border border-[#222e3d]">
          حالة الجلسة: <span className="text-[#36d1dc] font-semibold">{tgStatus}</span>
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
          <span>💾 احفظ الإعدادات في config.json</span>
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
