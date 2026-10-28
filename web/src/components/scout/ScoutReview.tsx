import React, { useState } from 'react';
import { Telescope, Play, CheckSquare, Clock, Zap, AlertCircle } from 'lucide-react';
import { ScoutCandidate, ScoutSession } from '../../types';
import { videoProcessor } from '../../services/videoProcessor';

interface ScoutReviewProps {
  maxDuration: number;
  sourceFile?: File | null;
  sourceUrl?: string;
  onUseCandidate: (candidate: ScoutCandidate, trimStart: number, trimEnd: number) => void;
  onPreviewCandidate: (candidate: ScoutCandidate, trimStart: number, trimEnd: number) => void;
  onBatchProcess: (items: Array<{ candidate: ScoutCandidate; start: number; end: number }>) => void;
  sourceLabel?: string;
}

export const ScoutReview: React.FC<ScoutReviewProps> = ({
  maxDuration,
  sourceFile,
  sourceUrl,
  onUseCandidate,
  onPreviewCandidate,
  onBatchProcess,
  sourceLabel,
}) => {
  const [candidateCount, setCandidateCount] = useState<number>(5);
  const [analyzing, setAnalyzing] = useState<boolean>(false);
  const [session, setSession] = useState<ScoutSession | null>(null);
  const [selectedIndices, setSelectedIndices] = useState<number[]>([]);
  const [activeUsedIndex, setActiveUsedIndex] = useState<number | null>(null);

  // Local trim window state per candidate: { [index]: { start: number, end: number } }
  const [trimWindows, setTrimWindows] = useState<Record<number, { start: number; end: number }>>({});
  const [trimErrors, setTrimErrors] = useState<Record<number, string>>({});

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = (secs % 60).toFixed(1);
    return `${m.toString().padStart(2, '0')}:${s.padStart(4, '0')}`;
  };

  const startAnalysis = async () => {
    const fileOrUrl = sourceFile || sourceUrl;
    if (!fileOrUrl) {
      setSession({
        id: 'scout-' + Date.now(),
        status: 'failed',
        stage: 'اختر فيديو أولاً لاستخراج إطارات معاينة محلية.',
        progress: 0,
        duration: 0,
        candidates: [],
      });
      return;
    }

    setAnalyzing(true);
    setSession({
      id: 'scout-' + Date.now(),
      status: 'analyzing',
      stage: 'استخراج إطارات معاينة محلية؛ لا يوجد تحليل صوت أو كشف رياضي.',
      progress: 10,
      duration: 0,
      candidates: [],
    });

    try {
      const candidates = await videoProcessor.analyzeScoutFrames(
        fileOrUrl,
        candidateCount,
        (progress, stage) => {
          setSession(prev => prev ? { ...prev, progress, stage } : null);
        }
      );

      const initialWindows: Record<number, { start: number; end: number }> = {};
      candidates.forEach((candidate, idx) => {
        initialWindows[idx] = { start: candidate.start, end: candidate.end };
      });

      setTrimWindows(initialWindows);
      setSelectedIndices([]);
      setSession({
        id: 'scout-' + Date.now(),
        status: 'ready',
        stage: 'اكتمل استخراج الإطارات المحلية؛ لم تُرتّب اللقطات حسب الحدث.',
        progress: 100,
        duration: candidates[0]?.source_duration || 0,
        candidates,
      });
    } catch (err) {
      setSession(prev => prev ? {
        ...prev,
        status: 'failed',
        stage: 'تعذّر استخراج إطارات المعاينة.',
        progress: 0,
        error: err instanceof Error ? err.message : 'تحقق من الفيديو وحاول مجدداً.',
      } : null);
    } finally {
      setAnalyzing(false);
    }
  };


  const handleTrimChange = (index: number, candidate: ScoutCandidate, type: 'start' | 'end', val: string) => {
    const num = parseFloat(val);
    if (isNaN(num)) return;

    const current = trimWindows[index] || { start: candidate.start, end: candidate.end };
    const next = {
      ...current,
      [type]: num,
    };

    let err = '';
    if (next.start < 0) {
      err = 'بداية القص لا يمكن أن تكون قبل الصفر.';
    } else if (next.end <= next.start) {
      err = 'النهاية يجب أن تكون بعد البداية.';
    } else if (next.end > candidate.source_duration) {
      err = `النهاية تتجاوز مدة المصدر (${formatTime(candidate.source_duration)}).`;
    } else if (next.end - next.start < 3) {
      err = 'يجب ألا تقل نافذة القص عن 3 ثوانٍ.';
    } else if (next.end - next.start > maxDuration) {
      err = `مدة القص تتجاوز الحد الأقصى (${maxDuration} ث).`;
    } else if (candidate.sample_t < next.start || candidate.sample_t > next.end) {
      err = `يجب أن تشمل نافذة القص عينة الإطار (${formatTime(candidate.sample_t)}).`;
    }

    setTrimWindows(prev => ({ ...prev, [index]: next }));
    setTrimErrors(prev => ({ ...prev, [index]: err }));
  };

  const handleToggleCheck = (index: number) => {
    setSelectedIndices(prev =>
      prev.includes(index) ? prev.filter(i => i !== index) : [...prev, index]
    );
  };

  const handleSelectAll = () => {
    if (!session) return;
    if (selectedIndices.length === session.candidates.length) {
      setSelectedIndices([]);
    } else {
      setSelectedIndices(session.candidates.map((_, i) => i));
    }
  };

  const handleUseCandidate = (candidate: ScoutCandidate, idx: number) => {
    const window = trimWindows[idx] || { start: candidate.start, end: candidate.end };
    setActiveUsedIndex(idx);
    onUseCandidate(candidate, window.start, window.end);
  };

  const handleBatch = () => {
    if (!session || selectedIndices.some(idx => Boolean(trimErrors[idx]))) return;
    const items = selectedIndices.map(idx => {
      const candidate = session.candidates[idx];
      const window = trimWindows[idx] || { start: candidate.start, end: candidate.end };
      return { candidate, start: window.start, end: window.end };
    });
    onBatchProcess(items);
  };

  return (
    <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl mt-6">
      <div className="flex items-start justify-between gap-4 flex-wrap pb-3 border-b border-[#222e3d]">
        <div>
          <h2 className="text-base font-bold text-[#cfdcec] flex items-center gap-2">
            <Telescope className="w-5 h-5 text-[#36d1dc]" />
            <span>عينات الإطارات المحلية</span>
          </h2>
          <p className="text-xs text-[#8ea0b5] mt-1">
            يستخرج صوراً ثابتة ونوافذ زمنية من الفيديو داخل المتصفح فقط؛ لا يكشف الكرة أو الأهداف ولا يحلل الصوت أو يقيس الخطورة.
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <label className="text-xs text-[#8ea0b5] flex items-center gap-1.5 font-semibold">
            عدد اللقطات:
            <select
              value={candidateCount}
              onChange={e => setCandidateCount(Number(e.target.value))}
              disabled={analyzing}
              className="bg-[#0c1219] border border-[#2c3a4d] rounded-lg px-2.5 py-1 text-xs text-[#e8eef6]"
            >
              <option value={3}>3 لقطات</option>
              <option value={5}>5 لقطات</option>
              <option value={8}>8 لقطات</option>
              <option value={10}>10 لقطات</option>
            </select>
          </label>

          <button
            onClick={startAnalysis}
            disabled={analyzing}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 disabled:opacity-50 transition"
          >
            <Telescope className="w-3.5 h-3.5" />
            <span>{analyzing ? 'جارٍ استخراج الإطارات...' : 'استخراج عينات الإطارات'}</span>
          </button>

          {session && (
            <button
              onClick={() => { setSession(null); setSelectedIndices([]); }}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#26313f] border border-[#2c3a4d] text-[#8ea0b5] hover:text-white transition"
            >
              مسح
            </button>
          )}
        </div>
      </div>

      {/* Progress or status */}
      {session && session.status === 'analyzing' && (
        <div className="mt-4">
          <div className="flex justify-between text-xs text-[#aab8ca] mb-1.5">
            <span>{session.stage}</span>
            <span>{session.progress}%</span>
          </div>
          <div className="w-full h-2 rounded-full bg-[#0a0e13] overflow-hidden border border-[#222e3d]">
            <div
              className="h-full bg-gradient-to-r from-[#27b9b3] to-[#58e0b6] transition-all duration-300"
              style={{ width: `${session.progress}%` }}
            />
          </div>
        </div>
      )}

      {session?.status === 'failed' && (
        <div role="alert" className="mt-4 rounded-xl border border-[#5c2428] bg-[#2c1a1b] p-3 text-xs leading-relaxed text-[#ffb3ba">
          {session.stage} {session.error || ''}
        </div>
      )}

      {!session && (
        <div className="text-center py-10 px-4 text-[#8ea0b5] text-xs border border-dashed border-[#222e3d] rounded-xl mt-4">
          اختر فيديو أولاً؛ سيُستخرج منه عدد محدود من الإطارات للمعاينة المحلية فقط.
        </div>
      )}

      {/* Candidates Grid */}
      {session && session.status === 'ready' && (
        <div className="mt-4">
          <div className="mb-3 rounded-xl border border-[#664c30] bg-[#282114] p-3 text-[11px] leading-relaxed text-[#e5c99a]">
            صور المعاينة ومواضعها مأخوذة من الملف؛ لا توجد نتائج ذكاء اصطناعي أو مؤشرات تتبّع.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {session.candidates.map((cand, idx) => {
              const currentWindow = trimWindows[idx] || { start: cand.start, end: cand.end };
              const err = trimErrors[idx];
              const isSelected = selectedIndices.includes(idx);
              const isUsed = activeUsedIndex === idx;

              return (
                <article
                  key={cand.id}
                  className={`bg-[#182231] border rounded-xl overflow-hidden transition ${
                    isUsed ? 'border-[#27b9b3] shadow-lg shadow-[#27b9b3]/15' : 'border-[#222e3d] hover:border-[#2c3a4d]'
                  }`}
                >
                  {/* Thumbnail & Score Tag */}
                  <div className="relative aspect-video bg-[#090e14]">
                    {cand.thumb ? (
                      <img
                        src={cand.thumb}
                        alt={`إطار المعاينة ${idx + 1}`}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="grid h-full place-items-center text-xs text-[#8ea0b5]">
                        تعذّر إنشاء صورة معاينة
                      </div>
                    )}
                    <div className="absolute top-2 right-2 bg-[#0d151d]/90 border border-[#664c30] rounded-md px-2 py-0.5 text-[10px] font-bold text-[#e5c99a]">
                      إطار معاينة
                    </div>

                    <label className="absolute top-2 left-2 bg-[#0d151d]/90 border border-[#2c3a4d] rounded-md px-2 py-0.5 text-[11px] font-bold text-white flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => handleToggleCheck(idx)}
                        className="rounded"
                      />
                      <span>دفعة</span>
                    </label>

                    <div className="absolute bottom-2 right-2 bg-black/75 px-2 py-0.5 rounded text-[10px] text-white">
                      عينة: {formatTime(cand.sample_t)}
                    </div>
                  </div>

                  {/* Body */}
                  <div className="p-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-bold text-white">
                        اللقطة {idx + 1} · {cand.dur} ثانية
                      </h3>
                      <span className="text-[11px] text-[#8ea0b5]">
                        {formatTime(cand.start)} - {formatTime(cand.end)}
                      </span>
                    </div>



                    {/* Trim Adjustment Controls */}
                    <div className="grid grid-cols-2 gap-2 mt-2 text-[11px]">
                      <div>
                        <label className="text-[#8ea0b5] block text-[10px] mb-0.5">البداية (ث):</label>
                        <input
                          type="number"
                          step="0.5"
                          value={currentWindow.start}
                          onChange={e => handleTrimChange(idx, cand, 'start', e.target.value)}
                          className="w-full bg-[#0c131a] border border-[#2c3a4d] rounded px-2 py-1 text-center font-mono text-xs text-white"
                        />
                      </div>
                      <div>
                        <label className="text-[#8ea0b5] block text-[10px] mb-0.5">النهاية (ث):</label>
                        <input
                          type="number"
                          step="0.5"
                          value={currentWindow.end}
                          onChange={e => handleTrimChange(idx, cand, 'end', e.target.value)}
                          className="w-full bg-[#0c131a] border border-[#2c3a4d] rounded px-2 py-1 text-center font-mono text-xs text-white"
                        />
                      </div>
                    </div>

                    {err && (
                      <div className="text-[10px] text-[#ff9aa2] mt-1.5 flex items-center gap-1">
                        <AlertCircle className="w-3 h-3 inline shrink-0" />
                        <span>{err}</span>
                      </div>
                    )}

                    {/* Action Buttons */}
                    <div className="grid grid-cols-2 gap-2 mt-3">
                      <button
                        onClick={() => handleUseCandidate(cand, idx)}
                        disabled={!!err}
                        className={`px-2.5 py-1.5 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1 ${
                          isUsed
                            ? 'bg-[#15312f] border border-[#26756c] text-[#b6f2df]'
                            : 'bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d]'
                        }`}
                      >
                        {isUsed ? '✓ نافذة محددة' : 'استخدم نافذة القص'}
                      </button>

                      <button
                        onClick={() => onPreviewCandidate(cand, currentWindow.start, currentWindow.end)}
                        disabled={!!err}
                        className="px-2.5 py-1.5 rounded-lg text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 transition flex items-center justify-center gap-1"
                      >
                        <Play className="w-3 h-3 inline" />
                        <span>معاينة 6s</span>
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>

          {/* Batch Actions Bar */}
          <div className="flex items-center justify-between gap-3 flex-wrap mt-4 pt-3 border-t border-[#222e3d]">
            <label className="text-xs text-[#cfdcec] font-semibold flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedIndices.length === session.candidates.length && session.candidates.length > 0}
                onChange={handleSelectAll}
                className="rounded"
              />
              <span>تحديد كل اللقطات ({selectedIndices.length}/{session.candidates.length})</span>
            </label>

            <button
              onClick={handleBatch}
              disabled={selectedIndices.length === 0}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#e63946] to-[#b3212c] hover:brightness-110 disabled:opacity-40 transition shadow-lg shadow-[#e63946]/20"
            >
              <Zap className="w-4 h-4" />
              <span>إنشاء بطاقات معاينة تجريبية ({selectedIndices.length})</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
