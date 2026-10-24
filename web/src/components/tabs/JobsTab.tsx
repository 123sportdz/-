import React, { useState } from 'react';
import {
  Search,
  Filter,
  Play,
  Download,
  Trash2,
  RefreshCw,
  Share2,
  Tv,
  Sparkles,
  FileText,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  Clock,
  Layers,
} from 'lucide-react';
import { Job } from '../../types';

interface JobsTabProps {
  jobs: Job[];
  onPlayJob: (job: Job) => void;
  onOpenRightsModal: (job: Job) => void;
  onOpenYoutubeModal: (job: Job) => void;
  onPublishTelegram: (job: Job) => void;
  onSuggestTitle: (job: Job) => void;
  onRetryFailed: () => void;
  onClearFinished: () => void;
  onMontage: () => void;
  onDeleteJob: (id: string) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

export const JobsTab: React.FC<JobsTabProps> = ({
  jobs,
  onPlayJob,
  onOpenRightsModal,
  onOpenYoutubeModal,
  onPublishTelegram,
  onSuggestTitle,
  onRetryFailed,
  onClearFinished,
  onMontage,
  onDeleteJob,
  onToast,
}) => {
  const [search, setSearch] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [workflowFilter, setWorkflowFilter] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('new');
  const [expandedLogJobId, setExpandedLogJobId] = useState<string | null>(null);

  // Filter logic
  const filteredJobs = jobs.filter(job => {
    if (search) {
      const q = search.toLowerCase();
      const matchTitle = job.title.toLowerCase().includes(q);
      const matchFile = job.filename.toLowerCase().includes(q);
      if (!matchTitle && !matchFile) return false;
    }
    if (statusFilter && job.status !== statusFilter) return false;

    if (workflowFilter) {
      if (workflowFilter === 'rights_pending' && job.rights_status !== 'pending') return false;
      if (workflowFilter === 'rights_recorded' && job.rights_status !== 'recorded') return false;
      if (workflowFilter === 'yt_all' && (!job.youtube_status || job.youtube_status === 'none')) return false;
      if (workflowFilter === 'yt_unchecked' && job.youtube_status !== 'unchecked') return false;
      if (workflowFilter === 'yt_processing' && job.youtube_status !== 'processing') return false;
      if (workflowFilter === 'yt_attention' && job.youtube_status !== 'attention') return false;
      if (workflowFilter === 'yt_ready' && job.youtube_status !== 'ready') return false;
    }
    return true;
  });

  // Sort logic
  filteredJobs.sort((a, b) => {
    if (sortBy === 'old') return a.id.localeCompare(b.id);
    if (sortBy === 'dur') return b.duration - a.duration;
    if (sortBy === 'time') return b.elapsed_s - a.elapsed_s;
    return b.id.localeCompare(a.id); // new default
  });

  const exportCsv = () => {
    const headers = ['ID', 'Title', 'Status', 'Duration(s)', 'Elapsed(s)', 'Rights', 'YouTube', 'Created'];
    const rows = jobs.map(j => [
      j.id,
      `"${j.title.replace(/"/g, '""')}"`,
      j.status,
      j.duration,
      j.elapsed_s,
      j.rights_status,
      j.youtube_status,
      `"${j.created_at}"`,
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,\uFEFF' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `elhadath_jobs_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    onToast('تم تصدير سجل المهام إلى CSV بنجاح', 'ok');
  };

  const statusBadge = (status: Job['status']) => {
    switch (status) {
      case 'done':
        return <span className="text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-[#25d07a]/15 text-[#79e0aa] border border-[#1d5c3e]">مكتملة</span>;
      case 'running':
        return <span className="text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-[#3b82f6]/20 text-[#8fb8ff] border border-[#2b4f86] animate-pulse">قيد المعالجة</span>;
      case 'failed':
        return <span className="text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-[#e63946]/20 text-[#ff9aa2] border border-[#6b2a30]">فاشلة</span>;
      case 'queued':
      default:
        return <span className="text-[11px] px-2.5 py-0.5 rounded-full font-bold bg-[#26313f] text-[#a9b8c9] border border-[#35475d]">في الانتظار 🚦</span>;
    }
  };

  return (
    <div>
      {/* Top Toolbar */}
      <div className="flex flex-wrap items-center gap-2.5 mb-4 bg-[#131a23] border border-[#222e3d] p-3 rounded-2xl">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="w-4 h-4 text-[#8ea0b5] absolute right-3 top-2.5 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="🔍 ابحث في المهام (اسم الملف / العنوان)..."
            className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl pr-9 pl-3 py-1.5 text-xs text-white placeholder:text-[#6f8291]"
          />
        </div>

        <button
          onClick={onMontage}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 transition"
          title="دمج أفضل 3 أهداف في ريل مجمّع"
        >
          <Layers className="w-3.5 h-3.5" />
          <span>🏆 ريل الترتيب (أفضل 3)</span>
        </button>

        <button
          onClick={onRetryFailed}
          className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
        >
          <RefreshCw className="w-3 h-3" />
          <span>إعادة الفاشلة</span>
        </button>

        <button
          onClick={onClearFinished}
          className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
        >
          <Trash2 className="w-3 h-3" />
          <span>حذف المكتملة</span>
        </button>

        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="bg-[#0c1219] border border-[#2c3a4d] rounded-xl px-2.5 py-1.5 text-xs text-white"
        >
          <option value="">كل الحالات</option>
          <option value="done">مكتملة</option>
          <option value="running">قيد المعالجة</option>
          <option value="failed">فاشلة</option>
          <option value="queued">في الانتظار</option>
        </select>

        <select
          value={workflowFilter}
          onChange={e => setWorkflowFilter(e.target.value)}
          className="bg-[#0c1219] border border-[#2c3a4d] rounded-xl px-2.5 py-1.5 text-xs text-white"
        >
          <option value="">كل مسارات المتابعة</option>
          <option value="rights_pending">بحاجة لاستكمال بيانات الحقوق</option>
          <option value="rights_recorded">نموذج مراجعة الحقوق مكتمل</option>
          <option value="yt_all">كل مرفوعات YouTube</option>
          <option value="yt_unchecked">YouTube: غير مفحوص</option>
          <option value="yt_processing">YouTube: قيد المعالجة</option>
          <option value="yt_ready">YouTube: اكتملت المعالجة</option>
        </select>

        <select
          value={sortBy}
          onChange={e => setSortBy(e.target.value)}
          className="bg-[#0c1219] border border-[#2c3a4d] rounded-xl px-2.5 py-1.5 text-xs text-white"
        >
          <option value="new">🆕 الأحدث أولاً</option>
          <option value="old">🕒 الأقدم أولاً</option>
          <option value="dur">⏱ الأطول مدةً</option>
          <option value="time">⚙️ الأطول معالجةً</option>
        </select>

        <button
          onClick={exportCsv}
          className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
        >
          <Download className="w-3.5 h-3.5 text-[#36d1dc]" />
          <span>تصدير CSV</span>
        </button>
      </div>

      {/* Summary line */}
      <div className="text-xs text-[#8ea0b5] mb-3">
        إجمالي المعروض: <b className="text-white">{filteredJobs.length}</b> من أصل {jobs.length} مهمة
      </div>

      {/* Jobs List */}
      <div className="space-y-3.5">
        {filteredJobs.length === 0 ? (
          <div className="text-center py-16 px-4 bg-[#131a23] border border-dashed border-[#222e3d] rounded-2xl text-[#8ea0b5]">
            <p className="text-sm font-semibold">لا توجد مهام تطابق البحث أو الفلاتر المحددة</p>
            <button
              onClick={() => { setSearch(''); setStatusFilter(''); setWorkflowFilter(''); }}
              className="mt-3 px-3 py-1.5 rounded-lg text-xs bg-[#26313f] text-white hover:bg-[#324154]"
            >
              ↺ إعادة ضبط الفلاتر
            </button>
          </div>
        ) : (
          filteredJobs.map(job => (
            <div
              key={job.id}
              className="bg-gradient-to-r from-[#131a23] to-[#0f151c] border border-[#222e3d] hover:border-[#35475d] rounded-2xl p-4 transition-all duration-200 grid grid-cols-1 md:grid-cols-[140px_1fr] gap-4"
            >
              {/* 9:16 Thumbnail */}
              <div
                onClick={() => onPlayJob(job)}
                className="relative aspect-[9/16] w-full max-h-52 rounded-xl overflow-hidden bg-[#090e14] border border-[#222e3d] cursor-pointer group shrink-0"
              >
                {job.thumbnail_url ? (
                  <img
                    src={job.thumbnail_url}
                    alt={job.title}
                    className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                  />
                ) : (
                  <div className="w-full h-full grid place-items-center text-2xl text-[#8ea0b5]">🎬</div>
                )}
                <div className="absolute inset-0 bg-black/40 group-hover:bg-black/20 flex items-center justify-center transition">
                  <div className="w-10 h-10 rounded-full bg-white/20 backdrop-blur-md grid place-items-center text-white shadow-lg">
                    <Play className="w-5 h-5 fill-current ml-0.5" />
                  </div>
                </div>
                <div className="absolute bottom-2 right-2 bg-black/80 text-[10px] px-1.5 py-0.5 rounded text-white font-mono">
                  {job.duration}s
                </div>
              </div>

              {/* Main Job Info */}
              <div className="flex flex-col justify-between">
                <div>
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <h3 className="text-sm sm:text-base font-extrabold text-white flex items-center gap-2">
                      <span>{job.title}</span>
                      {statusBadge(job.status)}
                    </h3>
                    <span className="text-[11px] text-[#8ea0b5]">{job.created_at}</span>
                  </div>

                  {/* Progress Bar for running jobs */}
                  {job.status === 'running' && (
                    <div className="mt-2.5">
                      <div className="flex justify-between text-[11px] text-[#aab8ca] mb-1">
                        <span>المرحلة {job.stage}/6: {job.stage_text}</span>
                        <span className="font-mono">{job.progress}%</span>
                      </div>
                      <div className="w-full h-2 rounded-full bg-[#0a0e13] overflow-hidden border border-[#222e3d]">
                        <div
                          className="h-full bg-gradient-to-r from-[#3b82f6] to-[#e63946] transition-all duration-300"
                          style={{ width: `${job.progress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Metadata Chips */}
                  <div className="flex items-center gap-3 flex-wrap text-xs text-[#8ea0b5] mt-2.5">
                    <span>الملف: <b className="text-[#cfdcec]">{job.filename}</b></span>
                    <span>المقاس: <b className="text-[#cfdcec]">{job.out_size}</b></span>
                    <span>الجودة: <b className="text-[#cfdcec]">{job.quality}</b></span>
                    <span>المدة: <b className="text-[#cfdcec]">{job.duration} ثانية</b></span>
                    <span>زمن المعالجة: <b className="text-[#cfdcec]">{job.elapsed_s}s</b> ({job.speed_x}×)</span>
                    <span>FPS: <b className="text-[#cfdcec]">{job.fps}</b></span>
                  </div>

                  {/* Rights and YouTube status */}
                  <div className="flex items-center gap-2 flex-wrap text-xs mt-2.5">
                    {job.rights_status === 'recorded' ? (
                      <span className="flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full bg-[#15312f] border border-[#235e58] text-[#9fe8c4]">
                        <ShieldCheck className="w-3 h-3 text-[#25d07a]" />
                        <span>نموذج الحقوق مكتمل</span>
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full bg-[#2c1a1b] border border-[#5c2428] text-[#ff9aa2]">
                        <ShieldAlert className="w-3 h-3 text-[#e63946]" />
                        <span>بيانات الحقوق معلقة (مراجعة مطلوبة)</span>
                      </span>
                    )}

                    {job.youtube_status === 'ready' && (
                      <span className="flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full bg-[#1b2636] border border-[#284c78] text-[#8fb8ff]">
                        <Tv className="w-3 h-3 text-[#3b82f6]" />
                        <span>يوتيوب: تم الرفع ({job.youtube_video_id})</span>
                      </span>
                    )}

                    {job.telegram_published && (
                      <span className="flex items-center gap-1 text-[11px] px-2.5 py-0.5 rounded-full bg-[#15312f] border border-[#235e58] text-[#9fe8c4]">
                        <Share2 className="w-3 h-3 text-[#25d07a]" />
                        <span>نُشر على تيليجرام</span>
                      </span>
                    )}
                  </div>

                  {/* Commentary snippet */}
                  {job.commentary_text && (
                    <div className="mt-2.5 p-2 rounded-lg bg-[#0c1219] border border-[#222e3d] text-xs text-[#dce8f2]">
                      <b className="text-[#36d1dc] ml-1">🎙️ تعليق صوتي:</b>
                      <span>{job.commentary_text}</span>
                    </div>
                  )}
                </div>

                {/* Job Action Buttons */}
                <div className="flex items-center gap-2 flex-wrap mt-4 pt-3 border-t border-[#222e3d]">
                  <button
                    onClick={() => onPlayJob(job)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 transition"
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>تشغيل الريل</span>
                  </button>

                  <button
                    onClick={() => onOpenRightsModal(job)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
                  >
                    <ShieldCheck className="w-3.5 h-3.5 text-[#36d1dc]" />
                    <span>مراجعة الحقوق</span>
                  </button>

                  <button
                    onClick={() => onOpenYoutubeModal(job)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
                  >
                    <Tv className="w-3.5 h-3.5 text-[#e63946]" />
                    <span>نشر يوتيوب</span>
                  </button>

                  <button
                    onClick={() => onPublishTelegram(job)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
                  >
                    <Share2 className="w-3.5 h-3.5 text-[#25d07a]" />
                    <span>تيليجرام</span>
                  </button>

                  <button
                    onClick={() => onSuggestTitle(job)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
                  >
                    <Sparkles className="w-3.5 h-3.5 text-[#f0b429]" />
                    <span>عنوان ذكي</span>
                  </button>

                  <button
                    onClick={() => setExpandedLogJobId(expandedLogJobId === job.id ? null : job.id)}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-[#182231] hover:bg-[#222e3d] text-[#8ea0b5] border border-[#2c3a4d] transition"
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>سجل التدقيق</span>
                  </button>

                  <button
                    onClick={() => onDeleteJob(job.id)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs text-[#ff9aa2] hover:bg-[#e63946]/20 transition mr-auto"
                    title="حذف المهمة"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>

                {/* Expanded Audit Log Trail */}
                {expandedLogJobId === job.id && (
                  <div className="mt-3 p-3 bg-[#080c11] border border-[#222e3d] rounded-xl text-xs font-mono">
                    <div className="font-bold text-[#36d1dc] mb-1.5">
                      سجل التدقيق المشفر (outputs/audit/events.jsonl):
                    </div>
                    {job.audit_log && job.audit_log.length > 0 ? (
                      <div className="space-y-1">
                        {job.audit_log.map((log, i) => (
                          <div key={i} className="text-[#aab8ca]">
                            <span className="text-[#8ea0b5]">[{log.time}]</span> <span className="text-[#25d07a]">{log.event}:</span> {log.detail}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-[#8ea0b5]">لا توجد سجلات بعد.</div>
                    )}

                    {job.quality_report && (
                      <div className="mt-2 pt-2 border-t border-[#222e3d] text-[11px] text-[#8ea0b5]">
                        <span className="text-white font-bold">تقرير الجودة (v1.65):</span> كشف الكرة: {job.quality_report.ball_detections} إطار (ثقة {Math.round(job.quality_report.ball_confidence_avg * 100)}%) · الكودك: {job.quality_report.encoder} · سلاسة الكاميرا: {Math.round(job.quality_report.camera_smoothness * 100)}%
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
