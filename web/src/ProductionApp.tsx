import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Download,
  Film,
  HardDrive,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
  X,
  XCircle,
  Zap,
} from 'lucide-react';
import {
  DashboardJob,
  DashboardQueue,
  DashboardScoutSession,
  DashboardSystemInfo,
  dashboardApi,
} from './services/dashboardApi';
import type { ReactNode } from 'react';
import { WorkflowGuide } from './components/WorkflowGuide';

type Section = 'create' | 'jobs';
type JobFilter = 'all' | 'active' | 'done' | 'failed';

const emptyQueue: DashboardQueue = {
  running: 0,
  waiting: 0,
  limit: 1,
  gpu: false,
  gpu_limit: 1,
  gpu_available: 0,
  gpu_waiting: 0,
};

const statusLabels: Record<string, string> = {
  queued: 'في الانتظار',
  running: 'قيد المعالجة',
  cancelling: 'جارٍ الإيقاف',
  done: 'مكتملة',
  failed: 'فشلت',
};

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '—';
  const units = ['بايت', 'KB', 'MB', 'GB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toLocaleString('ar-EG', { maximumFractionDigits: 1 })} ${units[unit]}`;
}

function formatTime(value?: number): string {
  if (!value || !Number.isFinite(value)) return '—';
  return new Date(value * 1000).toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' });
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'تعذّر الاتصال بخادم المعالجة. تأكد من تشغيل لوحة التحكم ثم أعد المحاولة.';
}

function isActive(status: string): boolean {
  return status === 'queued' || status === 'running' || status === 'cancelling';
}

export function ProductionApp() {
  const [section, setSection] = useState<Section>('create');
  const [workflowTarget, setWorkflowTarget] = useState<string | null>(null);
  const [filter, setFilter] = useState<JobFilter>('all');
  const [jobs, setJobs] = useState<DashboardJob[]>([]);
  const [queue, setQueue] = useState<DashboardQueue>(emptyQueue);
  const [systemInfo, setSystemInfo] = useState<DashboardSystemInfo | null>(null);
  const [maxUploadBytes, setMaxUploadBytes] = useState(4 * 1024 ** 3);
  const [connected, setConnected] = useState(false);
  const [pageError, setPageError] = useState('');
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState('');
  const [uploaded, setUploaded] = useState<{ file: File; path: string } | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isScouting, setIsScouting] = useState(false);
  const [formError, setFormError] = useState('');
  const [scoutError, setScoutError] = useState('');
  const [scoutSession, setScoutSession] = useState<DashboardScoutSession | null>(null);
  const [trimValues, setTrimValues] = useState<Record<number, { start: string; end: string }>>({});
  const [subject, setSubject] = useState<'action' | 'ball' | 'player'>('action');
  const [quality, setQuality] = useState<'auto' | 'fast' | 'balanced' | 'high' | 'ultra'>('auto');
  const [layout, setLayout] = useState<'single' | 'split'>('single');
  const [tracker, setTracker] = useState<'auto' | 'pro' | 'classic'>('auto');
  const [maxDuration, setMaxDuration] = useState(58);
  const [showChannelName, setShowChannelName] = useState(true);
  const [selectedVideo, setSelectedVideo] = useState<DashboardJob | null>(null);
  const [notice, setNotice] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [nextJobs, nextQueue] = await Promise.all([dashboardApi.jobs(), dashboardApi.queue()]);
      setJobs(nextJobs);
      setQueue(nextQueue);
      setConnected(true);
      setPageError('');
    } catch (error) {
      setConnected(false);
      setPageError(errorText(error));
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    void dashboardApi.config().then(config => {
      if (!mounted) return;
      setMaxUploadBytes(config.max_upload_bytes || 4 * 1024 ** 3);
      setShowChannelName(config.show_channel_name !== false);
    }).catch(() => undefined);
    void dashboardApi.systemInfo().then(info => {
      if (mounted) setSystemInfo(info);
    }).catch(() => undefined);
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    let timer = 0;
    const update = async () => {
      try {
        const [nextJobs, nextQueue] = await Promise.all([dashboardApi.jobs(), dashboardApi.queue()]);
        if (!mounted) return;
        setJobs(nextJobs);
        setQueue(nextQueue);
        setConnected(true);
        setPageError('');
      } catch (error) {
        if (!mounted) return;
        setConnected(false);
        setPageError(errorText(error));
      }
      if (mounted) timer = window.setTimeout(update, 3000);
    };
    void update();
    return () => {
      mounted = false;
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (!scoutSession || !['queued', 'downloading', 'analyzing'].includes(scoutSession.status)) return;
    let mounted = true;
    let timer = 0;
    const poll = async () => {
      try {
        const current = await dashboardApi.scout(scoutSession.id);
        if (mounted) setScoutSession(current);
      } catch (error) {
        if (mounted) {
          setScoutError(errorText(error));
          setScoutSession(null);
        }
      }
      if (mounted) timer = window.setTimeout(poll, 1500);
    };
    timer = window.setTimeout(poll, 700);
    return () => {
      mounted = false;
      window.clearTimeout(timer);
    };
  }, [scoutSession?.id, scoutSession?.status]);

  useEffect(() => {
    if (!workflowTarget) return;
    document.getElementById(workflowTarget)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setWorkflowTarget(null);
  }, [section, workflowTarget]);

  const visibleJobs = useMemo(() => jobs.filter(job => {
    if (filter === 'active') return isActive(job.status);
    if (filter === 'done') return job.status === 'done';
    if (filter === 'failed') return job.status === 'failed';
    return true;
  }), [jobs, filter]);

  const chooseFile = (file?: File) => {
    setFormError('');
    if (!file) {
      setScoutError('');
      setScoutSession(null);
      setTrimValues({});
      setSourceFile(null);
      setUploaded(null);
      return;
    }
    const supported = file.type.startsWith('video/') || /\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(file.name);
    if (!supported) {
      setFormError('اختر ملف فيديو مدعوماً مثل MP4 أو MOV أو MKV.');
      return;
    }
    if (file.size > maxUploadBytes) {
      setFormError(`حجم الملف ${formatBytes(file.size)} يتجاوز الحد ${formatBytes(maxUploadBytes)}.`);
      return;
    }
    setScoutError('');
    setScoutSession(null);
    setTrimValues({});
    setSourceFile(file);
    setSourceUrl('');
    setUploaded(null);
  };

  const prepareSource = async (): Promise<string> => {
    const url = sourceUrl.trim();
    if (sourceFile) {
      if (uploaded?.file === sourceFile) return uploaded.path;
      setUploadProgress(0);
      const result = await dashboardApi.upload(sourceFile, setUploadProgress);
      setUploaded({ file: sourceFile, path: result.path });
      setUploadProgress(null);
      return result.path;
    }
    if (!url) throw new Error('اختر فيديو أو أدخل رابطاً عاماً أولاً.');
    if (!/^https?:\/\//i.test(url)) throw new Error('استخدم رابطاً يبدأ بـ http:// أو https://.');
    return url;
  };

  const makeOptions = (input: string) => ({
    input,
    subject,
    out_size: '1080x1920',
    quality,
    layout,
    tracker,
    framing: 'normal' as const,
    zoom: 'auto',
    max_dur: maxDuration,
    thumb: true,
    keep_watermarks: true as const,
    auto_youtube: false as const,
    auto_telegram: false as const,
    show_channel_name: showChannelName,
  });

  const submitJob = async (options: ReturnType<typeof makeOptions> & { scout_id?: string; scout_index?: number; start?: string; end?: string }) => {
    setIsSubmitting(true);
    setFormError('');
    setNotice('');
    try {
      await dashboardApi.createJob(options);
      setNotice('أُضيفت المهمة إلى محرك المعالجة الفعلي. يمكنك متابعة حالتها من قائمة المهام.');
      setSection('jobs');
      await refresh();
    } catch (error) {
      setFormError(errorText(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  const startRender = async () => {
    try {
      const source = await prepareSource();
      await submitJob(makeOptions(source));
    } catch (error) {
      setUploadProgress(null);
      setFormError(errorText(error));
    }
  };

  const startScout = async () => {
    setIsScouting(true);
    setScoutError('');
    setScoutSession(null);
    setTrimValues({});
    try {
      const source = await prepareSource();
      const session = await dashboardApi.startScout(source, 5);
      setScoutSession(session);
    } catch (error) {
      setScoutError(errorText(error));
    } finally {
      setUploadProgress(null);
      setIsScouting(false);
    }
  };

  const updateTrim = (index: number, key: 'start' | 'end', value: string) => {
    const candidate = scoutSession?.candidates[index];
    if (!candidate) return;
    setTrimValues(previous => ({
      ...previous,
      [index]: {
        start: previous[index]?.start ?? candidate.start.toFixed(1),
        end: previous[index]?.end ?? candidate.end.toFixed(1),
        [key]: value,
      },
    }));
  };

  const renderCandidate = async (index: number) => {
    if (!scoutSession || scoutSession.status !== 'ready') return;
    const candidate = scoutSession.candidates[index];
    if (!candidate) return;
    const start = Number(trimValues[index]?.start ?? candidate.start);
    const end = Number(trimValues[index]?.end ?? candidate.end);
    const duration = end - start;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > scoutSession.duration || duration < 3 || duration > maxDuration) {
      setScoutError(`توقيت اللقطة ${index + 1} غير صالح: يجب أن يبقى داخل الفيديو، ومدته 3–${maxDuration} ثانية.`);
      return;
    }
    if (candidate.peak_t < start || candidate.peak_t > end) {
      setScoutError(`نافذة اللقطة ${index + 1} يجب أن تتضمن لحظة الذروة عند ${candidate.peak_t.toFixed(1)} ثانية.`);
      return;
    }
    setScoutError('');
    await submitJob({
      ...makeOptions(''),
      scout_id: scoutSession.id,
      scout_index: index,
      start: start.toFixed(2),
      end: end.toFixed(2),
    });
  };

  const cancelJob = async (job: DashboardJob) => {
    if (!window.confirm(`إيقاف المهمة ${job.id}؟`)) return;
    try {
      await dashboardApi.cancelJob(job.id);
      await refresh();
    } catch (error) {
      setPageError(errorText(error));
    }
  };

  const deleteJob = async (job: DashboardJob) => {
    if (!window.confirm(`حذف المهمة ${job.id} وملف ناتجها من الخادم؟`)) return;
    try {
      await dashboardApi.deleteJob(job.id);
      if (selectedVideo?.id === job.id) setSelectedVideo(null);
      await refresh();
    } catch (error) {
      setPageError(errorText(error));
    }
  };

  const runningCount = jobs.filter(job => job.status === 'running').length;
  const waitingCount = jobs.filter(job => job.status === 'queued').length;
  const scoutBusy = isScouting || Boolean(scoutSession && ['queued', 'downloading', 'analyzing'].includes(scoutSession.status));

  return (
    <main dir="rtl" className="min-h-screen text-[#e8eef6]">
      <header className="sticky top-0 z-30 border-b border-[#2c3a4d] bg-[#0b0f14]/95 px-4 py-3 backdrop-blur-xl sm:px-7">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="grid size-11 place-items-center rounded-xl bg-gradient-to-br from-[#e63946] to-[#7a1420] text-xl shadow-lg">⚽</div>
            <div>
              <h1 className="text-base font-black sm:text-lg">elhadath-reels</h1>
              <p className="text-xs text-[#8ea0b5]">واجهة إنتاج متصلة بالمحرك الفعلي</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={`size-2 rounded-full ${connected ? 'bg-[#25d07a]' : 'bg-[#e63946]'}`} />
            <span className={connected ? 'text-[#25d07a]' : 'text-[#f0b429]'}>{connected ? 'الخادم متصل' : 'الخادم غير متصل'}</span>
            <a href="/" className="mr-2 rounded-lg border border-[#2c3a4d] px-3 py-2 text-[#c9d6e5] hover:bg-[#182231]">اللوحة الحالية</a>
            <a href="/app/demo/" className="rounded-lg border border-[#2c3a4d] px-3 py-2 text-[#c9d6e5] hover:bg-[#182231]">النموذج التجريبي</a>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-7">
        {pageError && (
          <div role="alert" className="mb-5 flex items-start gap-3 rounded-xl border border-[#7a1f2b] bg-[#2a1014] p-4 text-sm text-[#ffd1d5]">
            <AlertTriangle className="mt-0.5 size-5 shrink-0" />
            <div className="flex-1"><p className="font-bold">{pageError}</p><p className="mt-1 text-xs opacity-80">لن تتحول المهام إلى بيانات نموذجية؛ ستبقى الواجهة صريحة عند تعذّر الاتصال.</p></div>
            <button onClick={() => void refresh()} aria-label="إعادة المحاولة" className="rounded-lg p-1 hover:bg-white/10"><RefreshCw className="size-4" /></button>
          </div>
        )}

        {notice && (
          <div role="status" className="mb-5 flex items-center gap-2 rounded-xl border border-[#1c6d4c] bg-[#10251d] p-4 text-sm text-[#b5f3d0]">
            <CheckCircle2 className="size-5 shrink-0" />{notice}<button onClick={() => setNotice('')} className="mr-auto p-1" aria-label="إغلاق"><X className="size-4" /></button>
          </div>
        )}

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric icon={<Activity className="size-4" />} label="قيد التنفيذ" value={runningCount} />
          <Metric icon={<Film className="size-4" />} label="في الطابور" value={waitingCount} />
          <Metric icon={<Cpu className="size-4" />} label="المعالج" value={systemInfo?.cuda ? (systemInfo.gpu_name || 'GPU') : 'CPU'} small />
          <Metric icon={<HardDrive className="size-4" />} label="المتزامن المسموح" value={`${queue.limit} مهمة`} small />
        </section>

        <div className="mt-6 flex flex-wrap gap-2 border-b border-[#222e3d] pb-3">
          <button onClick={() => setSection('create')} className={tabClass(section === 'create')}><Zap className="size-4" /> مقطع جديد</button>
          <button onClick={() => setSection('jobs')} className={tabClass(section === 'jobs')}><Film className="size-4" /> المهام الفعلية <span className="rounded-full bg-black/20 px-2">{jobs.length}</span></button>
          <button onClick={() => void refresh()} className="mr-auto rounded-lg border border-[#2c3a4d] px-3 py-2 text-xs text-[#c9d6e5] hover:bg-[#182231]"><RefreshCw className="ml-1 inline size-3.5" /> تحديث</button>
        </div>

        <WorkflowGuide
          sourceReady={Boolean(sourceFile || sourceUrl.trim())}
          scoutSession={scoutSession}
          jobs={jobs}
          onNavigate={(targetSection, targetId) => {
            setSection(targetSection);
            setWorkflowTarget(targetId);
          }}
        />

        {section === 'create' ? (
          <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,.9fr)]">
            <section id="workflow-source" className="scroll-mt-24 rounded-2xl border border-[#222e3d] bg-[#131a23] p-4 sm:p-6">
              <div className="mb-5 flex items-start gap-3">
                <div className="grid size-10 place-items-center rounded-xl bg-[#2a1820] text-[#ff6b76]"><Upload className="size-5" /></div>
                <div><h2 className="text-lg font-extrabold">أرسل مقطعاً إلى محرك المعالجة</h2><p className="mt-1 text-xs leading-6 text-[#8ea0b5]">الرفع إلى خادمك نفسه. لا يُرسل الفيديو إلى Gemini أو أي خدمة خارجية من هذه الصفحة.</p></div>
              </div>

              <label
                htmlFor="production-video"
                onDragOver={event => event.preventDefault()}
                onDrop={event => { event.preventDefault(); chooseFile(event.dataTransfer.files[0]); }}
                className="flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-[#3a4c61] bg-[#0f151c] px-4 py-5 text-center hover:border-[#e63946]"
              >
                <Upload className="mb-2 size-6 text-[#36d1dc]" />
                <span className="text-sm font-bold">{sourceFile ? sourceFile.name : 'اسحب ملف فيديو إلى هنا أو اختره'}</span>
                <span className="mt-1 text-xs text-[#8ea0b5]">الحد الأقصى الحالي: {formatBytes(maxUploadBytes)}</span>
                <input id="production-video" type="file" accept="video/*,.mkv,.avi,.m4v" className="sr-only" onChange={event => {
                  const file = event.target.files?.[0];
                  if (file) chooseFile(file);
                  event.target.value = '';
                }} />
              </label>
              {sourceFile && (
                <div className="mt-2 flex items-center justify-between text-xs text-[#8ea0b5]">
                  <span>{formatBytes(sourceFile.size)} · {sourceFile.type || 'فيديو'}</span>
                  <button onClick={() => chooseFile()} className="rounded px-2 py-1 text-[#ff9aa2] hover:bg-white/5">إزالة</button>
                </div>
              )}

              <div className="my-4 flex items-center gap-3 text-[11px] text-[#65778c]"><span className="h-px flex-1 bg-[#222e3d]" />أو رابط فيديو عام<span className="h-px flex-1 bg-[#222e3d]" /></div>
              <label className="block text-xs font-bold text-[#c9d6e5]" htmlFor="production-url">رابط HTTP/HTTPS</label>
              <input id="production-url" type="url" value={sourceUrl} onChange={event => {
                const value = event.target.value;
                setSourceUrl(value);
                setScoutSession(null);
                setTrimValues({});
                setScoutError('');
                if (value) {
                  setSourceFile(null);
                  setUploaded(null);
                }
              }} placeholder="https://…" dir="ltr" className="mt-2 w-full rounded-xl border border-[#2c3a4d] bg-[#0b0f14] px-3 py-3 text-sm text-white outline-none focus:border-[#36d1dc]" />
              <p className="mt-2 text-[11px] leading-5 text-[#73859a]">قد يرفض الخادم الروابط الخاصة أو الداخلية. استخدم ملفاً محلياً إذا لم يكن الرابط عاماً.</p>

              <div className="mt-5 grid gap-3 sm:grid-cols-2">
                <Field label="تركيز التتبّع"><select value={subject} onChange={event => setSubject(event.target.value as typeof subject)} className={fieldClass}><option value="action">الحركة / اللقطة</option><option value="ball">الكرة</option><option value="player">اللاعب</option></select></Field>
                <Field label="الجودة"><select value={quality} onChange={event => setQuality(event.target.value as typeof quality)} className={fieldClass}><option value="auto">تلقائي</option><option value="fast">سريع</option><option value="balanced">متوازن</option><option value="high">عالٍ</option><option value="ultra">فائق</option></select></Field>
                <Field label="تخطيط الفيديو"><select value={layout} onChange={event => setLayout(event.target.value as typeof layout)} className={fieldClass}><option value="single">لقطة واحدة 9:16</option><option value="split">شاشة مقسومة</option></select></Field>
                <Field label="المتعقّب"><select value={tracker} onChange={event => setTracker(event.target.value as typeof tracker)} className={fieldClass}><option value="auto">تلقائي</option><option value="pro">احترافي</option><option value="classic">كلاسيكي</option></select></Field>
                <Field label="أقصى مدة للريل (ثانية)"><input type="number" min="3" max="600" value={maxDuration} onChange={event => setMaxDuration(Math.max(3, Math.min(600, Number(event.target.value) || 3)))} className={fieldClass} /></Field>
              </div>
              <label className="mt-4 flex items-center gap-2 text-xs text-[#c9d6e5]"><input type="checkbox" checked={showChannelName} onChange={event => setShowChannelName(event.target.checked)} className="accent-[#e63946]" />إظهار اسم القناة حسب إعدادات المشروع</label>

              <div className="mt-4 flex flex-wrap gap-2 rounded-xl border border-[#244d43] bg-[#10221d] p-3 text-xs leading-6 text-[#b5f3d0]">
                <ShieldCheck className="mt-1 size-4 shrink-0" /><span>علامات المصدر محفوظة. النشر التلقائي متوقف. لا يُنفّذ أي رفع إلى YouTube أو Telegram من هذا المسار.</span>
              </div>

              {uploadProgress !== null && (
                <div role="status" className="mt-4 rounded-xl border border-[#2c3a4d] bg-[#0f151c] p-3 text-xs">
                  <div className="mb-2 flex justify-between"><span>رفع الفيديو إلى الخادم</span><span>{uploadProgress}%</span></div>
                  <div className="h-2 overflow-hidden rounded-full bg-[#222e3d]"><div className="h-full rounded-full bg-[#36d1dc] transition-all" style={{ width: `${uploadProgress}%` }} /></div>
                </div>
              )}
              {formError && <p role="alert" className="mt-4 rounded-lg border border-[#7a1f2b] bg-[#2a1014] p-3 text-xs leading-6 text-[#ffd1d5]">{formError}</p>}
              <button id="workflow-render" onClick={() => void startRender()} disabled={isSubmitting || uploadProgress !== null || (!sourceFile && !sourceUrl.trim())} className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-[#e63946] px-4 py-3 text-sm font-black text-white transition hover:bg-[#ff4c59] disabled:cursor-not-allowed disabled:opacity-50">
                {isSubmitting || uploadProgress !== null ? <LoaderCircle className="size-4 animate-spin" /> : <Play className="size-4" />}
                {uploadProgress !== null ? 'جارٍ رفع الملف…' : isSubmitting ? 'جارٍ إنشاء المهمة…' : 'ابدأ الرندر الفعلي'}
              </button>
            </section>

            <section id="workflow-scout" className="scroll-mt-24 rounded-2xl border border-[#222e3d] bg-[#131a23] p-4 sm:p-6">
              <div className="mb-4 flex items-start gap-3">
                <div className="grid size-10 place-items-center rounded-xl bg-[#182231] text-[#36d1dc]"><Activity className="size-5" /></div>
                <div><h2 className="text-lg font-extrabold">كشف اللقطات ومراجعتها</h2><p className="mt-1 text-xs leading-6 text-[#8ea0b5]">يستعمل جلسة الكشّاف الحقيقية على الخادم؛ تُحفظ الجلسات مؤقتاً في الذاكرة.</p></div>
              </div>
              <button onClick={() => void startScout()} disabled={scoutBusy || isSubmitting || uploadProgress !== null || (!sourceFile && !sourceUrl.trim())} className="flex w-full items-center justify-center gap-2 rounded-xl border border-[#2c3a4d] bg-[#182231] px-4 py-3 text-sm font-bold hover:bg-[#222e3d] disabled:opacity-50">
                {scoutBusy ? <LoaderCircle className="size-4 animate-spin" /> : <Activity className="size-4" />}
                {scoutBusy ? 'جارٍ تحليل الفيديو…' : 'حلّل الفيديو لاستخراج اللقطات'}
              </button>
              {scoutError && <p role="alert" className="mt-3 rounded-lg border border-[#7a1f2b] bg-[#2a1014] p-3 text-xs leading-6 text-[#ffd1d5]">{scoutError}</p>}
              {scoutSession && (
                <div className="mt-4 rounded-xl border border-[#2c3a4d] bg-[#0f151c] p-3">
                  <div className="flex items-center justify-between gap-3"><div><p className="text-sm font-bold">{scoutSession.label || 'جلسة تحليل'}</p><p className="mt-1 text-xs text-[#8ea0b5]">{scoutSession.stage} · {Math.round(scoutSession.progress)}%</p></div><span className="text-xs text-[#36d1dc]">{scoutSession.duration ? `${scoutSession.duration.toFixed(1)} ث` : 'جارٍ التحليل'}</span></div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#222e3d]"><div className="h-full bg-[#36d1dc] transition-all" style={{ width: `${Math.max(0, Math.min(100, scoutSession.progress))}%` }} /></div>
                  {scoutSession.status === 'failed' && <p className="mt-3 text-xs leading-5 text-[#ff9aa2]">{scoutSession.error || 'تعذّر تحليل الفيديو.'}</p>}
                  {scoutSession.status === 'ready' && scoutSession.candidates.length === 0 && <p className="mt-3 text-xs text-[#8ea0b5]">لم يعثر التحليل على لقطات مرشّحة.</p>}
                  {scoutSession.status === 'ready' && scoutSession.candidates.length > 0 && (
                    <div className="mt-4 space-y-4">
                      {scoutSession.candidates.map((candidate, index) => {
                        const selected = trimValues[index] || { start: candidate.start.toFixed(1), end: candidate.end.toFixed(1) };
                        return (
                          <article key={`${scoutSession.id}-${index}`} className="overflow-hidden rounded-xl border border-[#222e3d] bg-[#131a23]">
                            <img src={`/api/scout/${encodeURIComponent(scoutSession.id)}/thumb/${index}`} alt={`إطار اللقطة ${index + 1}`} loading="lazy" className="aspect-video w-full bg-[#0b0f14] object-cover" />
                            <div className="p-3">
                              <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-bold">لقطة {index + 1} · التقييم {candidate.score.toFixed(0)}</h3><span className="text-[11px] text-[#8ea0b5]">الذروة {candidate.peak_t.toFixed(1)} ث</span></div>
                              <p className="mt-1 text-[11px] leading-5 text-[#8ea0b5]">{candidate.reasons.slice(0, 3).join(' · ') || `تغطية ${Math.round(candidate.stats.coverage * 100)}%`}</p>
                              <div className="mt-3 grid grid-cols-2 gap-2">
                                <label className="text-[11px] text-[#8ea0b5]">البداية (ث)<input type="number" step="0.1" min="0" max={scoutSession.duration} value={selected.start} onChange={event => updateTrim(index, 'start', event.target.value)} className={fieldClass} /></label>
                                <label className="text-[11px] text-[#8ea0b5]">النهاية (ث)<input type="number" step="0.1" min="0" max={scoutSession.duration} value={selected.end} onChange={event => updateTrim(index, 'end', event.target.value)} className={fieldClass} /></label>
                              </div>
                              <button onClick={() => void renderCandidate(index)} disabled={isSubmitting} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-[#e63946] px-3 py-2 text-xs font-bold hover:bg-[#ff4c59] disabled:opacity-50"><Film className="size-4" />أرسل هذه اللقطة للرندر</button>
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>
        ) : (
          <section id="workflow-jobs" className="scroll-mt-24 mt-5 rounded-2xl border border-[#222e3d] bg-[#131a23] p-4 sm:p-6">
            <div className="mb-5 flex flex-wrap items-center gap-3">
              <div className="flex-1"><h2 className="text-lg font-extrabold">طابور محرك الرندر الفعلي</h2><p className="mt-1 text-xs text-[#8ea0b5]">تُحدّث الحالة كل 3 ثوانٍ من خادم المشروع، من دون بيانات نموذجية.</p></div>
              <label className="sr-only" htmlFor="job-filter">تصفية المهام</label>
              <select id="job-filter" value={filter} onChange={event => setFilter(event.target.value as JobFilter)} className={`${fieldClass} mt-0 w-auto min-w-36`}><option value="all">كل المهام</option><option value="active">النشطة</option><option value="done">المكتملة</option><option value="failed">الفاشلة</option></select>
            </div>
            {visibleJobs.length === 0 ? (
              <div className="rounded-xl border border-dashed border-[#2c3a4d] px-4 py-12 text-center"><Film className="mx-auto size-8 text-[#65778c]" /><p className="mt-3 text-sm font-bold">لا توجد مهام فعلية في هذا العرض</p><p className="mt-1 text-xs text-[#8ea0b5]">ابدأ معالجة فيديو حقيقي من تبويب «مقطع جديد».</p></div>
            ) : (
              <div className="space-y-3">{visibleJobs.map(job => (
                <article key={job.id} className="rounded-xl border border-[#222e3d] bg-[#0f151c] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="max-w-full truncate text-sm font-bold">{job.title || job.label || `مهمة ${job.id}`}</h3><StatusBadge status={job.status} /></div><p className="mt-1 text-[11px] text-[#8ea0b5]">#{job.id} · {formatTime(job.created)}{job.duration ? ` · ${job.duration.toFixed(1)} ث` : ''}</p></div>
                    <div className="flex gap-2">
                      {isActive(job.status) && <button onClick={() => void cancelJob(job)} title="إيقاف المهمة" className="rounded-lg border border-[#6b5720] px-2.5 py-2 text-xs text-[#f3d489] hover:bg-[#282114]"><XCircle className="size-4" /></button>}
                      {job.status === 'done' && job.media && <a href={job.media} download className="rounded-lg border border-[#2c3a4d] px-2.5 py-2 text-xs text-[#c9d6e5] hover:bg-[#182231]" title="تنزيل الفيديو"><Download className="size-4" /></a>}
                      {(job.status === 'done' || job.status === 'failed') && <button onClick={() => void deleteJob(job)} title="حذف المهمة والملف" className="rounded-lg border border-[#6b2b34] px-2.5 py-2 text-xs text-[#ff9aa2] hover:bg-[#2a1014]"><Trash2 className="size-4" /></button>}
                    </div>
                  </div>
                  {isActive(job.status) && <div className="mt-3"><div className="mb-1 flex justify-between gap-3 text-[11px] text-[#8ea0b5]"><span className="truncate">{job.stage || statusLabels[job.status] || job.status}</span><span>{Math.max(0, Math.min(100, Math.round(job.progress || 0)))}%</span></div><div className="h-2 overflow-hidden rounded-full bg-[#222e3d]"><div className="h-full bg-gradient-to-l from-[#36d1dc] to-[#25d07a] transition-all" style={{ width: `${Math.max(0, Math.min(100, job.progress || 0))}%` }} /></div></div>}
                  {job.estimate && <p className="mt-2 text-[11px] text-[#8ea0b5]">الوقت التقديري: {Math.ceil(job.estimate)} ثانية {job.elapsed ? `· المنقضي ${Math.ceil(job.elapsed)} ث` : ''}</p>}
                  {job.quality_report?.ok === false && <p className="mt-3 flex items-start gap-2 rounded-lg border border-[#6b5720] bg-[#282114] p-2.5 text-[11px] leading-5 text-[#f3d489]"><AlertTriangle className="mt-0.5 size-4 shrink-0" />مكتمل مع ملاحظات جودة: {(job.quality_report.issues || []).join('، ') || 'راجع تقرير المهمة من اللوحة الحالية.'}</p>}
                  {job.status === 'done' && job.media && <button onClick={() => setSelectedVideo(job)} className="mt-3 flex items-center gap-2 rounded-lg border border-[#2c3a4d] px-3 py-2 text-xs font-bold hover:bg-[#182231]"><Play className="size-4" />معاينة الفيديو الناتج</button>}
                </article>
              ))}</div>
            )}
          </section>
        )}

        <footer className="mt-6 rounded-xl border border-[#222e3d] bg-[#0f151c] p-4 text-[11px] leading-6 text-[#8ea0b5]">
          <p className="flex items-start gap-2"><ShieldCheck className="mt-1 size-4 shrink-0 text-[#36d1dc]" /><span>هذه الصفحة تستخدم جلسة لوحة التحكم الحالية وواجهات المشروع. لا تعرض مسارات الملفات الخام، ولا تحفظ مهام الخادم في LocalStorage. النشر غير مفعّل هنا؛ استخدم بوابة الحقوق الموجودة في اللوحة الحالية لأي نشر، وستظل تتحقق على الخادم.</span></p>
        </footer>
      </div>

      {selectedVideo?.media && (
        <div role="dialog" aria-modal="true" aria-label="معاينة الفيديو" className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-4" onClick={() => setSelectedVideo(null)}>
          <div className="relative w-full max-w-md rounded-2xl border border-[#2c3a4d] bg-[#131a23] p-3" onClick={event => event.stopPropagation()}>
            <button onClick={() => setSelectedVideo(null)} aria-label="إغلاق المعاينة" className="absolute left-5 top-5 z-10 rounded-full bg-black/70 p-2 hover:bg-black"><X className="size-4" /></button>
            <video src={selectedVideo.media} controls playsInline className="max-h-[78vh] w-full rounded-xl bg-black" />
            <p className="px-1 pt-3 text-sm font-bold">{selectedVideo.title || selectedVideo.label || `مهمة ${selectedVideo.id}`}</p>
          </div>
        </div>
      )}
    </main>
  );
}

function Metric({ icon, label, value, small = false }: { icon: ReactNode; label: string; value: ReactNode; small?: boolean }) {
  return <div className="flex items-center gap-3 rounded-xl border border-[#222e3d] bg-[#131a23] p-4"><div className="grid size-9 place-items-center rounded-lg bg-[#182231] text-[#36d1dc]">{icon}</div><div><p className="text-[11px] text-[#8ea0b5]">{label}</p><p className={`mt-0.5 font-extrabold ${small ? 'text-sm' : 'text-lg'}`}>{value}</p></div></div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-xs font-bold text-[#c9d6e5]">{label}{children}</label>;
}

function StatusBadge({ status }: { status: string }) {
  const active = isActive(status);
  const completed = status === 'done';
  const failed = status === 'failed';
  const style = completed ? 'border-[#1c6d4c] bg-[#10251d] text-[#b5f3d0]' : failed ? 'border-[#7a1f2b] bg-[#2a1014] text-[#ffd1d5]' : active ? 'border-[#245d66] bg-[#102529] text-[#b2eff2]' : 'border-[#2c3a4d] bg-[#182231] text-[#c9d6e5]';
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold ${style}`}>{completed ? <CheckCircle2 className="size-3" /> : failed ? <XCircle className="size-3" /> : null}{statusLabels[status] || status}</span>;
}

function tabClass(active: boolean): string {
  return `inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-bold transition ${active ? 'border-[#e63946] bg-[#2a1820] text-white' : 'border-[#2c3a4d] text-[#8ea0b5] hover:bg-[#182231]'}`;
}

const fieldClass = 'mt-1 w-full rounded-lg border border-[#2c3a4d] bg-[#0b0f14] px-3 py-2.5 text-sm text-white outline-none focus:border-[#36d1dc]';
