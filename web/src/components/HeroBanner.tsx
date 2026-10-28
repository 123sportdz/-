import React from 'react';
import { PlayCircle, Layers } from 'lucide-react';
import { Job } from '../types';

interface HeroBannerProps {
  jobs: Job[];
  onFocusNew: () => void;
  onFocusJobs: () => void;
}

export const HeroBanner: React.FC<HeroBannerProps> = ({ jobs, onFocusNew, onFocusJobs }) => {
  const total = jobs.length;
  const done = jobs.filter(j => j.status === 'done').length;
  const running = jobs.filter(j => j.status === 'running').length;
  const queued = jobs.filter(j => j.status === 'queued').length;

  return (
    <section className="relative overflow-hidden grid grid-cols-1 lg:grid-cols-[1.4fr_0.85fr] gap-6 items-center bg-gradient-to-br from-[#182231]/95 to-[#0e1721]/90 border border-[#36d1dc]/25 rounded-2xl p-6 md:p-7 mb-6 shadow-2xl">
      {/* Decorative Glow */}
      <div className="absolute -left-20 -bottom-36 w-64 h-64 rounded-full bg-[#36d1dc]/10 blur-3xl pointer-events-none" />

      <div className="relative z-10">
        <div className="text-[11px] font-extrabold tracking-widest text-[#36d1dc] uppercase mb-1">
          ELHADATH · REEL STUDIO
        </div>
        <h1 className="text-2xl sm:text-3xl lg:text-4xl font-extrabold text-white tracking-tight leading-tight mb-2">
          حوّل لحظات المباراة إلى ريل احترافي
        </h1>
        <p className="text-[#aab8ca] text-sm max-w-xl mb-4 leading-relaxed">
          استكشف نموذجاً تفاعلياً لواجهة الريلز. المهام والمؤشرات المعروضة أمثلة تجريبية، ولا تُنفّذ معالجة أو نشرًا حقيقياً.
        </p>

        <div className="flex items-center gap-2 text-xs text-[#9fe8c4] bg-[#080d13]/70 border border-[#1d5c3e] rounded-full px-3.5 py-1.5 w-fit mb-4">
          <span className="w-2 h-2 rounded-full bg-[#25d07a] shadow-[0_0_8px_#25d07a]"></span>
          <span>واجهة تجريبية · محرك Python وYOLO والنشر غير متصلين</span>
        </div>

        <div className="flex flex-wrap gap-2.5">
          <button
            onClick={onFocusNew}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#1c9ca8] to-[#146b82] hover:brightness-110 shadow-md shadow-[#1c9ca8]/20 transition"
          >
            <PlayCircle className="w-4 h-4" />
            <span>＋ مقطع جديد</span>
          </button>
          <button
            onClick={onFocusJobs}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-[#cfdcec] bg-[#26313f] border border-[#2c3a4d] hover:bg-[#324154] transition"
          >
            <Layers className="w-4 h-4" />
            <span>فتح مركز المهام</span>
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-2 gap-2.5 relative z-10">
        <div className="bg-[#080d13]/60 border border-[#2c3a4d] rounded-xl p-3.5 relative overflow-hidden">
          <div className="text-2xl font-black text-white">{total}</div>
          <span className="text-[11px] text-[#8ea0b5]">كل المهام</span>
        </div>

        <div className="bg-[#080d13]/60 border border-[#2c3a4d] rounded-xl p-3.5 relative overflow-hidden">
          <div className="text-2xl font-black text-[#25d07a]">{done}</div>
          <span className="text-[11px] text-[#8ea0b5]">مهام نموذجية مكتملة</span>
        </div>

        <div className="bg-[#080d13]/60 border border-[#2c3a4d] rounded-xl p-3.5 relative overflow-hidden">
          <div className="text-2xl font-black text-[#3b82f6]">{running}</div>
          <span className="text-[11px] text-[#8ea0b5]">قيد المعالجة</span>
        </div>

        <div className="bg-[#080d13]/60 border border-[#2c3a4d] rounded-xl p-3.5 relative overflow-hidden">
          <div className="text-2xl font-black text-[#f0b429]">{queued}</div>
          <span className="text-[11px] text-[#8ea0b5]">في الانتظار 🚦</span>
        </div>
      </div>
    </section>
  );
};
