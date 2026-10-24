import React from 'react';
import { Download, Film, Sparkles, Tv, ShieldCheck, Cpu } from 'lucide-react';
import { AppSettings, Job } from '../types';

interface HeaderProps {
  settings: AppSettings;
  jobs: Job[];
  onExportDiagnostics: () => void;
}

export const Header: React.FC<HeaderProps> = ({ settings, jobs, onExportDiagnostics }) => {
  const activeJobs = jobs.filter(j => j.status === 'running').length;
  const readyJobs = jobs.filter(j => j.status === 'done').length;

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
              v1.66 Pro
            </span>
          </div>
          <div className="text-xs text-[#8ea0b5] font-medium">
            مصنع الريلز الرياضية العمودية
          </div>
        </div>
      </div>

      {/* Status Chips */}
      <div className="hidden md:flex items-center gap-2">
        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs bg-[#182231] border border-[#2c3a4d] text-[#9fe8c4]">
          <span className="w-2 h-2 rounded-full bg-[#25d07a] shadow-[0_0_8px_#25d07a]"></span>
          <Cpu className="w-3.5 h-3.5 inline mr-1 text-[#25d07a]" />
          <span>GPU: YOLO11n (q16)</span>
        </div>

        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs bg-[#182231] border border-[#2c3a4d] text-[#e8eef6]">
          <Tv className="w-3.5 h-3.5 text-[#3b82f6]" />
          <span>{settings.youtube_privacy === 'private' ? 'YouTube: خاص (آمن)' : `YouTube: ${settings.youtube_privacy}`}</span>
        </div>

        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs bg-[#182231] border border-[#2c3a4d] text-[#a9dce0]">
          <ShieldCheck className="w-3.5 h-3.5 text-[#36d1dc]" />
          <span>بوابة الحقوق نشطة</span>
        </div>
      </div>

      {/* Action */}
      <div className="flex items-center gap-2">
        <button
          onClick={onExportDiagnostics}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#182231] border border-[#2c3a4d] hover:bg-[#222e3d] text-[#e8eef6] transition"
          title="تحميل سجلات النظام والتشخيص"
        >
          <Download className="w-3.5 h-3.5 text-[#36d1dc]" />
          <span className="hidden sm:inline">تقرير التشخيص</span>
        </button>
      </div>
    </header>
  );
};
