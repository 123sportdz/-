import React, { useState } from 'react';
import { Image, Upload, Check, Trash2, Eye, ShieldAlert, Sparkles } from 'lucide-react';
import { LogoItem, LogoSettings } from '../../types';

interface BrandTabProps {
  logos: LogoItem[];
  settings: LogoSettings;
  onSaveSettings: (settings: LogoSettings) => void;
  onUploadLogo: (logo: LogoItem) => void;
  onDeleteLogo: (id: string) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

const POSITIONS = [
  { id: 'top-left', label: 'أعلى يسار' },
  { id: 'top-center', label: 'أعلى وسط' },
  { id: 'top-right', label: 'أعلى يمين (موصى به)' },
  { id: 'center-left', label: 'وسط يسار' },
  { id: 'center', label: 'الوسط' },
  { id: 'center-right', label: 'وسط يمين' },
  { id: 'bottom-left', label: 'أسفل يسار' },
  { id: 'bottom-center', label: 'أسفل وسط' },
  { id: 'bottom-right', label: 'أسفل يمين' },
] as const;

export const BrandTab: React.FC<BrandTabProps> = ({
  logos,
  settings,
  onSaveSettings,
  onUploadLogo,
  onDeleteLogo,
  onToast,
}) => {
  const [localSettings, setLocalSettings] = useState<LogoSettings>(settings);

  const selectedLogo = logos.find(l => l.id === localSettings.selectedLogoId) || logos[0];

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const reader = new FileReader();
      reader.onload = ev => {
        const url = ev.target?.result as string;
        const newLogo: LogoItem = {
          id: 'logo-' + Date.now(),
          name: file.name,
          url,
          size_kb: Math.round(file.size / 1024),
        };
        onUploadLogo(newLogo);
        setLocalSettings(prev => ({ ...prev, selectedLogoId: newLogo.id }));
        onToast(`تم رفع الشعار: ${file.name}`, 'ok');
      };
      reader.readAsDataURL(file);
    }
  };

  const handleSave = () => {
    onSaveSettings(localSettings);
    onToast('تم حفظ إعدادات الشعار والهوية بنجاح', 'ok');
  };

  // Convert 9 positions to CSS placement
  const getPositionClass = (pos: LogoSettings['position']) => {
    switch (pos) {
      case 'top-left': return 'top-6 left-6';
      case 'top-center': return 'top-6 left-1/2 -translate-x-1/2';
      case 'top-right': return 'top-6 right-6';
      case 'center-left': return 'top-1/2 -translate-y-1/2 left-6';
      case 'center': return 'top-1/2 -translate-y-1/2 left-1/2 -translate-x-1/2';
      case 'center-right': return 'top-1/2 -translate-y-1/2 right-6';
      case 'bottom-left': return 'bottom-8 left-6';
      case 'bottom-center': return 'bottom-8 left-1/2 -translate-x-1/2';
      case 'bottom-right': return 'bottom-8 right-6';
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_1fr] gap-6 items-start">
      {/* Logo Library and Upload */}
      <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl">
        <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-4">
          <span className="w-5 h-5 rounded-md bg-[#182231] border border-[#2c3a4d] grid place-items-center text-xs text-[#8ea0b5]">
            🖼️
          </span>
          <span>مكتبة الشعارات</span>
        </h2>

        {/* Dropzone */}
        <div
          onClick={() => document.getElementById('logo_upload_input')?.click()}
          className="border-2 border-dashed border-[#2c3a4d] hover:border-[#36d1dc] bg-[#0c1219] hover:bg-[#36d1dc]/5 rounded-xl p-5 text-center cursor-pointer transition"
        >
          <Upload className="w-8 h-8 text-[#8ea0b5] mx-auto mb-2" />
          <b className="block text-sm text-[#e8eef6]">اسحب صورة الشعار هنا أو اضغط للاختيار</b>
          <span className="text-xs text-[#8ea0b5]">PNG بخلفية شفافة هو الأفضل · حتى 12 ميغا · JPG / WEBP مدعومة</span>
          <input
            type="file"
            id="logo_upload_input"
            accept="image/*"
            onChange={handleFileUpload}
            className="hidden"
          />
        </div>

        {/* Existing Logos Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-4">
          {logos.map(logo => {
            const isSelected = localSettings.selectedLogoId === logo.id;
            return (
              <div
                key={logo.id}
                onClick={() => setLocalSettings(prev => ({ ...prev, selectedLogoId: logo.id }))}
                className={`relative p-3 rounded-xl border bg-[#182231] cursor-pointer transition flex flex-col items-center text-center ${
                  isSelected ? 'border-[#36d1dc] shadow-md shadow-[#36d1dc]/20' : 'border-[#222e3d] hover:border-[#2c3a4d]'
                }`}
              >
                <div className="w-16 h-16 rounded-lg bg-[#090e14] p-2 flex items-center justify-center mb-2 overflow-hidden">
                  <img src={logo.url} alt={logo.name} className="max-w-full max-h-full object-contain" />
                </div>
                <div className="text-[11px] font-bold text-white truncate w-full">{logo.name}</div>
                <div className="text-[10px] text-[#8ea0b5]">{logo.size_kb} KB</div>

                {isSelected && (
                  <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-[#36d1dc] text-black grid place-items-center text-[10px] font-black">
                    ✓
                  </div>
                )}

                {logos.length > 1 && (
                  <button
                    onClick={e => {
                      e.stopPropagation();
                      onDeleteLogo(logo.id);
                    }}
                    className="absolute top-2 left-2 p-1 text-[#8ea0b5] hover:text-[#ff9aa2] transition"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-4 p-3 rounded-xl bg-[#080d13]/60 border border-[#222e3d] text-xs text-[#8ea0b5] leading-relaxed">
          💡 <b>نصيحة احترافية:</b> الشعار الشفاف (PNG) يبدو كأنه جزء أصيل من البث. الزاوية العليا اليمين هي الأكثر استقراراً لتجنب لوحات النتيجة وأسماء الفرق.
        </div>
      </div>

      {/* Logo Settings & Live Preview */}
      <div>
        <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl mb-6">
          <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-3">
            <span className="w-5 h-5 rounded-md bg-[#182231] border border-[#2c3a4d] grid place-items-center text-xs text-[#8ea0b5]">
              ⚙️
            </span>
            <span>إعدادات الشعار على الفيديو</span>
          </h2>

          {/* Position Picker Grid (3x3) */}
          <label className="block text-xs font-semibold text-[#8ea0b5] mb-2">الموضع على الفيديو</label>
          <div className="grid grid-cols-3 gap-2 max-w-[280px] mb-4">
            {POSITIONS.map(pos => (
              <button
                key={pos.id}
                type="button"
                onClick={() => setLocalSettings(prev => ({ ...prev, position: pos.id as any }))}
                className={`py-2 px-1 text-[11px] font-semibold rounded-lg border transition ${
                  localSettings.position === pos.id
                    ? 'bg-[#36d1dc] text-black border-[#36d1dc] font-black'
                    : 'bg-[#0c1219] text-[#8ea0b5] border-[#2c3a4d] hover:text-white'
                }`}
              >
                {pos.label.split(' ')[0]}
              </button>
            ))}
          </div>

          {/* Size & Opacity sliders */}
          <div className="grid grid-cols-2 gap-4 text-xs mb-3">
            <div>
              <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold">
                <span>الحجم (نسبة العرض)</span>
                <span className="text-[#36d1dc] font-mono">{localSettings.scale}%</span>
              </div>
              <input
                type="range"
                min="4"
                max="45"
                value={localSettings.scale}
                onChange={e => setLocalSettings(prev => ({ ...prev, scale: Number(e.target.value) }))}
                className="w-full accent-[#36d1dc] h-1.5 bg-[#090e14] rounded cursor-pointer"
              />
            </div>

            <div>
              <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold">
                <span>الشفافية</span>
                <span className="text-[#36d1dc] font-mono">{localSettings.opacity}%</span>
              </div>
              <input
                type="range"
                min="20"
                max="100"
                value={localSettings.opacity}
                onChange={e => setLocalSettings(prev => ({ ...prev, opacity: Number(e.target.value) }))}
                className="w-full accent-[#36d1dc] h-1.5 bg-[#090e14] rounded cursor-pointer"
              />
            </div>
          </div>

          {/* Checkbox Options */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs mb-4">
            <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
              <input
                type="checkbox"
                checked={localSettings.darkPlate}
                onChange={e => setLocalSettings(prev => ({ ...prev, darkPlate: e.target.checked }))}
                className="rounded"
              />
              <span>خلفية داكنة خلف الشعار</span>
            </label>

            <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
              <input
                type="checkbox"
                checked={localSettings.enabled}
                onChange={e => setLocalSettings(prev => ({ ...prev, enabled: e.target.checked }))}
                className="rounded"
              />
              <span>🖼️ تفعيل الشعار على كل المقاطع</span>
            </label>
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleSave}
              className="flex-1 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 transition"
            >
              💾 احفظ الإعدادات
            </button>
            <button
              onClick={() => setLocalSettings(prev => ({ ...prev, enabled: false }))}
              className="px-3 py-2 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
            >
              🚫 بلا شعار
            </button>
          </div>
        </div>

        {/* Live Visual Preview Frame */}
        <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl">
          <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-3">
            <Eye className="w-4 h-4 text-[#36d1dc]" />
            <span>معاينة فورية على كادر الريل العمودي (9:16)</span>
          </h2>

          <div className="relative mx-auto aspect-[9/16] max-h-[360px] rounded-2xl overflow-hidden bg-[#090e14] border-2 border-[#2c3a4d] shadow-2xl">
            {/* Background football scene */}
            <img
              src="https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=720&auto=format&fit=crop&q=80"
              alt="معاينة الشعار"
              className="w-full h-full object-cover brightness-90"
            />

            {/* Positioned Logo Overlay */}
            {localSettings.enabled && selectedLogo && (
              <div
                className={`absolute transition-all duration-150 pointer-events-none ${getPositionClass(localSettings.position)}`}
                style={{
                  width: `${localSettings.scale * 2}%`,
                  opacity: localSettings.opacity / 100,
                }}
              >
                <div className={`p-1.5 rounded-lg ${localSettings.darkPlate ? 'bg-black/60 backdrop-blur-sm' : ''}`}>
                  <img
                    src={selectedLogo.url}
                    alt="الشعار"
                    className="w-full h-auto object-contain drop-shadow-[0_2px_8px_rgba(0,0,0,0.8)]"
                  />
                </div>
              </div>
            )}

            {/* Simulated reel scoreboard and badges */}
            <div className="absolute top-4 left-4 bg-black/70 backdrop-blur-md px-2.5 py-1 rounded text-[10px] font-mono text-white flex items-center gap-1.5 border border-white/10">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
              <span>88:42</span>
            </div>
            <div className="absolute bottom-4 inset-x-4 bg-black/65 backdrop-blur-md p-2 rounded-xl text-center text-xs text-white border border-white/10">
              ⚽ الحدث · ريل رياضي عمودي
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
