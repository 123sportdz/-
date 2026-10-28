import React from 'react';
import { Download } from 'lucide-react';

interface HeaderProps {
  onExportDiagnostics: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onExportDiagnostics }) => {

  return (
    <header className="sticky top-0 z-40 flex items-center justify-between gap-4 px-6 py-3.5 bg-[#0b0f14]/80 backdrop-blur-xl border-b border-[#36d1dc]/15">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#e63946] to-[#7a1420] grid place-items-center shadow-lg shadow-[#e63946]/30 text-white font-black text-xl">
          ⚽
        </div>
        <div>
          <div className="font-extrabold text-lg tracking-tight text-white flex items-center gap-2">
            elhadath-reels
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#182231] border border-[#2c3a4d] text-[#36d1dc]">
              واجهة تجريبية
            </span>
          </div>
          <div className="text-xs text-[#8ea0b5] font-medium">
            مصنع الريلز الرياضية العمودية
          </div>
        </div>
      </div>

      <div className="hidden sm:flex items-center rounded-full border border-[#664c30] bg-[#282114] px-3 py-1 text-xs font-bold text-[#e5c99a]">
        لا يتصل بمحرك الرندر أو النشر
      </div>

      {/* Action */}
      <div className="flex items-center gap-2">
        <button
          onClick={onExportDiagnostics}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#182231] border border-[#2c3a4d] hover:bg-[#222e3d] text-[#e8eef6] transition"
          title="تصدير بيانات النموذج المحلي"
        >
          <Download className="w-3.5 h-3.5 text-[#36d1dc]" />
          <span className="hidden sm:inline">بيانات النموذج</span>
        </button>
      </div>
    </header>
  );
};
