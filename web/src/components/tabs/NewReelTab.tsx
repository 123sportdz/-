import React, { useState } from 'react';
import { Upload, Link2, Film, Sparkles, Zap, Shield, Play, Eye, AlertTriangle, Target } from 'lucide-react';
import { AppSettings, Job, ScoutCandidate, VoiceSettings } from '../../types';
import { VoiceStudio } from '../voice/VoiceStudio';
import { ScoutReview } from '../scout/ScoutReview';
import { ProShotTracker } from '../scout/ProShotTracker';
import { videoProcessor } from '../../services/videoProcessor';
import confetti from 'canvas-confetti';

interface NewReelTabProps {
  settings: AppSettings;
  voice: VoiceSettings;
  onVoiceChange: (voice: VoiceSettings) => void;
  onCreateJob: (jobData: Partial<Job>) => void;
  onBatchCreateJobs: (jobsData: Array<Partial<Job>>) => void;
  onPreviewVideo: (job: Job) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

export const NewReelTab: React.FC<NewReelTabProps> = ({
  settings,
  voice,
  onVoiceChange,
  onCreateJob,
  onBatchCreateJobs,
  onPreviewVideo,
  onToast,
}) => {
  // Form State
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [extractedVideoUrl, setExtractedVideoUrl] = useState<string | null>(null);
  const [extractedThumb, setExtractedThumb] = useState<string | null>(null);
  const [videoMeta, setVideoMeta] = useState<{ duration: number; width: number; height: number } | null>(null);
  const [isProcessingInput, setIsProcessingInput] = useState<boolean>(false);

  const [srcUrl, setSrcUrl] = useState<string>('');
  const [subject, setSubject] = useState<string>('action');
  const [layout, setLayout] = useState<string>('single');
  const [tracker, setTracker] = useState<string>('auto');
  const [quality, setQuality] = useState<string>('auto');
  const [outSize, setOutSize] = useState<string>('1080x1920');
  const [accent, setAccent] = useState<string>('auto');
  const [framing, setFraming] = useState<string>('normal');
  const [vcenter, setVcenter] = useState<string>('auto');
  const [zoom, setZoom] = useState<string>('auto');
  const [showChannelName, setShowChannelName] = useState<boolean>(settings.show_channel_name ?? true);
  const [brandY, setBrandY] = useState<number>(13.0);
  const [brandScale, setBrandScale] = useState<number>(100);
  const [trimStart, setTrimStart] = useState<string>('');
  const [trimEnd, setTrimEnd] = useState<string>('');

  // Toggles
  const [autocut, setAutocut] = useState<boolean>(false);
  const [bridge, setBridge] = useState<boolean>(true);
  const [replay, setReplay] = useState<boolean>(true);
  const [burst, setBurst] = useState<boolean>(false);
  const [hook, setHook] = useState<boolean>(false);
  const [retryHealing, setRetryHealing] = useState<boolean>(true);
  const [maxDur, setMaxDur] = useState<number>(58);
  const [genThumb, setGenThumb] = useState<boolean>(true);
  const [activeViewMode, setActiveViewMode] = useState<'standard' | 'tracker'>('standard');

  // Status message
  const [statusMsg, setStatusMsg] = useState<string>('');

  const processUploadedFile = async (file: File) => {
    setSelectedFile(file);
    setIsProcessingInput(true);
    try {
      const meta = await videoProcessor.extractVideoMetadata(file);
      setExtractedVideoUrl(meta.objectUrl);
      setExtractedThumb(meta.thumbnail);
      setVideoMeta({ duration: meta.duration, width: meta.width, height: meta.height });
      if (meta.duration > 0) {
        setMaxDur(Math.min(58, Math.round(meta.duration)));
      }
      onToast(`تم فحص المقطع بنجاح: ${file.name} (${meta.duration.toFixed(1)} ثانية، ${meta.width}x${meta.height})`, 'ok');
    } catch (err) {
      console.warn('Metadata extraction fallback:', err);
      const fallbackUrl = URL.createObjectURL(file);
      setExtractedVideoUrl(fallbackUrl);
      onToast(`تم اختيار الملف: ${file.name}`, 'ok');
    } finally {
      setIsProcessingInput(false);
    }
  };

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      processUploadedFile(file);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      processUploadedFile(file);
    }
  };

  const applyPreset = (presetName: 'pro' | 'goal' | 'celeb' | 'fast') => {
    switch (presetName) {
      case 'pro':
        setSubject('action');
        setLayout('single');
        setTracker('pro');
        setQuality('high');
        setFraming('normal');
        setVcenter('auto');
        setZoom('auto');
        setBridge(true);
        setReplay(true);
        break;
      case 'goal':
        setSubject('ball');
        setLayout('single');
        setTracker('pro');
        setFraming('tight');
        setReplay(true);
        setBurst(true);
        setAutocut(true);
        break;
      case 'celeb':
        setSubject('player');
        setLayout('single');
        setFraming('loose');
        setZoom('1.15');
        setHook(true);
        break;
      case 'fast':
        setQuality('fast');
        setTracker('classic');
        setReplay(false);
        setBridge(false);
        break;
    }
    onToast(`تم تفعيل القالب السريع: ${presetName}`, 'ok');
  };

  const handleStartProcessing = (isQuickCheck: boolean = false) => {
    const videoUrlToUse = extractedVideoUrl || (srcUrl.trim().startsWith('http') ? srcUrl.trim() : undefined);
    if (!videoUrlToUse) {
      onToast(selectedFile ? 'انتظر اكتمال قراءة الفيديو أولاً.' : 'اختر ملف فيديو أو رابط ملف مباشر أولاً.', 'err');
      return;
    }

    const jobTitle = selectedFile
      ? selectedFile.name.replace(/\.[^/.]+$/, '')
      : srcUrl
      ? `ريل ${new Date().toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' })}`
      : 'ريل جديد';

    const thumbToUse = extractedThumb || 'https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=720&auto=format&fit=crop&q=80';
    const durToUse = isQuickCheck ? 6 : (videoMeta?.duration ? Math.min(videoMeta.duration, maxDur) : maxDur);

    const newJob: Partial<Job> = {
      title: isQuickCheck ? `[معاينة 6s] ${jobTitle}` : jobTitle,
      filename: selectedFile ? selectedFile.name : 'input_clip.mp4',
      src_url: srcUrl,
      duration: Math.round(durToUse),
      status: 'running',
      stage: 1,
      stage_text: 'تجهيز ملف الفيديو وفحص الكودك',
      progress: 10,
      out_size: outSize,
      quality,
      subject,
      layout,
      accent,
      tracker,
      show_channel_name: showChannelName,
      brand_y: brandY,
      brand_scale: brandScale,
      rights_status: 'pending',
      youtube_status: 'none',
      telegram_published: false,
      output_url: videoUrlToUse,
      thumbnail_url: thumbToUse,
      commentary_text: voice.commentary ? voice.commentary_script || 'يا لها من لقطة حاسمة!' : undefined,
      audit_log: [
        {
          time: new Date().toLocaleTimeString('ar-EG'),
          event: 'demo_job_created',
          detail: 'بطاقة مهمة تجريبية محلية؛ لم يبدأ محرك الرندر.',
        },
      ],
    };

    onCreateJob(newJob);
    onToast('أُنشئت بطاقة مهمة تجريبية في المتصفح؛ لم تتم معالجة الفيديو.', 'ok');
    confetti({ particleCount: 50, spread: 60, origin: { y: 0.8 } });
  };

  const handleUseScoutCandidate = (candidate: ScoutCandidate, start: number, end: number) => {
    setTrimStart(start.toFixed(1));
    setTrimEnd(end.toFixed(1));
    onToast(`تم اعتماد توقيت اللقطة ${candidate.index + 1}: ${start.toFixed(1)}s إلى ${end.toFixed(1)}s`, 'ok');
  };

  const handlePreviewScoutCandidate = (candidate: ScoutCandidate, start: number, end: number) => {
    const videoUrlToUse = extractedVideoUrl || (srcUrl.trim().startsWith('http') ? srcUrl.trim() : undefined);
    if (!videoUrlToUse) {
      onToast('اختر ملف فيديو أو رابط ملف مباشر قبل المعاينة.', 'err');
      return;
    }
    const tempJob: Job = {
      id: 'preview-' + candidate.id,
      title: `معاينة لقطة ${candidate.index + 1} (${candidate.dur}s)`,
      filename: `candidate_${candidate.index + 1}.mp4`,
      status: 'done',
      stage: 6,
      stage_text: 'معاينة جاهزة',
      progress: 100,
      duration: Math.min(6, Math.max(3, end - start)),
      created_at: 'الآن',
      elapsed_s: 2.5,
      fps: 60,
      speed_x: 2.2,
      out_size: outSize,
      quality,
      subject,
      layout,
      accent,
      tracker,
      show_channel_name: showChannelName,
      brand_y: brandY,
      brand_scale: brandScale,
      rights_status: 'pending',
      youtube_status: 'none',
      output_url: videoUrlToUse,
      thumbnail_url: candidate.thumb || extractedThumb || undefined,
      commentary_text: `عينة إطار عند ${candidate.sample_t.toFixed(1)} ثانية؛ لم يُحلّل الحدث الرياضي.`,
      audit_log: [],
    };
    onPreviewVideo(tempJob);
  };

  const handleBatchScout = (items: Array<{ candidate: ScoutCandidate; start: number; end: number }>) => {
    const videoUrlToUse = extractedVideoUrl || (srcUrl.trim().startsWith('http') ? srcUrl.trim() : undefined);
    if (!videoUrlToUse) {
      onToast('لا يوجد فيديو صالح لدفعة المعاينة.', 'err');
      return;
    }
    const newJobs: Array<Partial<Job>> = items.map((item, idx) => ({
      title: `عينة إطار ${item.candidate.index + 1} · ${item.candidate.sample_t.toFixed(1)} ث`,
      filename: `scout_clip_${item.candidate.index + 1}.mp4`,
      src_url: srcUrl,
      duration: Math.round(item.end - item.start),
      status: idx === 0 ? 'running' : 'queued',
      stage: idx === 0 ? 1 : 0,
      stage_text: idx === 0 ? 'تجهيز ملف اللقطة' : 'في الانتظار',
      progress: idx === 0 ? 15 : 0,
      out_size: outSize,
      quality,
      subject,
      layout,
      accent,
      tracker,
      show_channel_name: showChannelName,
      brand_y: brandY,
      brand_scale: brandScale,
      rights_status: 'pending',
      youtube_status: 'none',
      output_url: videoUrlToUse,
      thumbnail_url: item.candidate.thumb || extractedThumb || undefined,
      commentary_text: voice.commentary ? voice.commentary_script || `عينة إطار عند ${item.candidate.sample_t.toFixed(1)} ثانية.` : undefined,
      audit_log: [
        {
          time: new Date().toLocaleTimeString('ar-EG'),
          event: 'demo_scout_batch_created',
          detail: `بطاقة قص تجريبية من ${item.start.toFixed(1)}s إلى ${item.end.toFixed(1)}s؛ لا يوجد رندر فعلي.`,
        },
      ],
    }));

    onBatchCreateJobs(newJobs);
    onToast(`أُنشئت ${items.length} بطاقة قص تجريبية؛ لم يُرندر فيديو.`, 'ok');
    confetti({ particleCount: 70, spread: 80, origin: { y: 0.7 } });
  };

  return (
    <div className="space-y-6">
      {/* View Mode Toggle: Standard Reel Builder vs Pro Shot Tracker Studio */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-2xl bg-gradient-to-r from-[#141d28] via-[#101720] to-[#0c1219] border border-[#222e3d] shadow-xl">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setActiveViewMode('standard')}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition ${
              activeViewMode === 'standard'
                ? 'bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] text-white shadow-lg'
                : 'text-[#8ea0b5] hover:text-white bg-[#0c1219] border border-[#222e3d]'
            }`}
          >
            <Film className="w-4 h-4 text-[#36d1dc]" />
            <span>🎬 نموذج إعداد الريل السريع</span>
          </button>

          <button
            onClick={() => setActiveViewMode('tracker')}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-black transition ${
              activeViewMode === 'tracker'
                ? 'bg-gradient-to-r from-[#36d1dc] to-[#5b86e5] text-[#0a1118] shadow-lg shadow-[#36d1dc]/25'
                : 'text-[#8ea0b5] hover:text-white bg-[#0c1219] border border-[#222e3d]'
            }`}
          >
            <Target className="w-4 h-4 text-[#e63946]" />
            <span>🎯 معاينة القص والحركة</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#282114] text-[#e5c99a]">
              توضيحية فقط
            </span>
          </button>
        </div>

        <div className="text-[11px] text-[#8ea0b5] hidden lg:flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#25d07a] animate-pulse" />
          <span>
            {activeViewMode === 'tracker'
              ? 'إطار 9:16 ورسوم توضيحية؛ لا يوجد كشف فعلي للكرة أو اللاعبين'
              : 'تفضيلات نموذجية؛ معالجة الفيديو الفعلية غير متصلة'}
          </span>
        </div>
      </div>

      {/* When Pro Shot Tracker is active, show the full tracking canvas suite */}
      {activeViewMode === 'tracker' && (
        <ProShotTracker
          videoUrl={extractedVideoUrl || (srcUrl.trim().startsWith('http') ? srcUrl.trim() : undefined)}
          thumbnailUrl={extractedThumb || undefined}
          sourceTitle={selectedFile?.name || srcUrl}
          onApplyCropSettings={({ subject: newSubject, tracker: newTracker, replay: newReplay, burst: newBurst }) => {
            setSubject(newSubject);
            setTracker(newTracker);
            setReplay(newReplay);
            setBurst(newBurst);
            setActiveViewMode('standard');
          }}
          onToast={onToast}
        />
      )}

      {/* Main Grid Columns */}
      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_1fr] gap-6 items-start">
        {/* Left Column: Input and Parameters */}
        <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl">
          <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-4">
            <span className="w-5 h-5 rounded-md bg-[#182231] border border-[#2c3a4d] grid place-items-center text-xs text-[#8ea0b5]">
              1
            </span>
            <span>اختر المقطع وضوابط المعالجة</span>
          </h2>

        {/* Dropzone */}
        <div
          onDragOver={e => e.preventDefault()}
          onDrop={handleFileDrop}
          onClick={() => document.getElementById('reel_file_input')?.click()}
          className="border-2 border-dashed border-[#2c3a4d] hover:border-[#e63946] bg-[#0c1219] hover:bg-[#e63946]/5 rounded-xl p-5 text-center cursor-pointer transition relative overflow-hidden"
        >
          <Upload className="w-8 h-8 text-[#8ea0b5] mx-auto mb-2" />
          <b className="block text-sm text-[#e8eef6]">اسحب المقطع هنا أو اضغط للاختيار</b>
          <span className="text-xs text-[#8ea0b5]">MP4 / MOV / MKV / WebM — قراءة محلية للمدة والأبعاد وإطار معاينة؛ لا يوجد رندر خادمي</span>
          <input
            type="file"
            id="reel_file_input"
            accept="video/*"
            onChange={handleFileInput}
            className="hidden"
          />

          {isProcessingInput && (
            <div className="mt-3 py-2 px-3 bg-[#182330] rounded-lg text-xs text-[#36d1dc] flex items-center justify-center gap-2">
              <span className="w-3.5 h-3.5 border-2 border-[#36d1dc] border-t-transparent rounded-full animate-spin" />
              <span>جارٍ قراءة مدة الفيديو وأبعاده وإنشاء إطار معاينة محلي...</span>
            </div>
          )}

          {selectedFile && !isProcessingInput && (
            <div className="mt-3 p-2.5 bg-[#131d27] border border-[#27384c] rounded-xl flex items-center gap-3 text-right">
              {extractedThumb ? (
                <img
                  src={extractedThumb}
                  alt="معاينة المقطع"
                  className="w-14 h-14 object-cover rounded-lg border border-[#3b4c63] flex-shrink-0"
                />
              ) : (
                <div className="w-14 h-14 rounded-lg bg-[#182231] border border-[#2c3a4d] flex items-center justify-center text-xs font-mono text-[#8ea0b5] flex-shrink-0">
                  فيديو
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-xs text-[#25d07a] font-bold truncate">
                  ✓ {selectedFile.name}
                </div>
                <div className="text-[11px] text-[#8ea0b5] mt-0.5">
                  {(selectedFile.size / 1e6).toFixed(1)} MB
                  {videoMeta && ` · ${videoMeta.duration.toFixed(1)} ثانية · ${videoMeta.width}x${videoMeta.height}`}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* URL Input */}
        <div className="mt-4">
          <label className="block text-xs font-semibold text-[#8ea0b5] mb-1">رابط ملف فيديو مباشر (MP4 / WebM فقط؛ لا يوجد جلب من Telegram)</label>
          <div className="relative">
            <input
              type="text"
              value={srcUrl}
              onChange={e => setSrcUrl(e.target.value)}
              placeholder="https://example.com/video.mp4"
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2.5 text-xs text-white placeholder:text-[#6f8291]"
            />
            <Link2 className="w-4 h-4 text-[#8ea0b5] absolute left-3 top-3 pointer-events-none" />
          </div>
        </div>

        {/* Primary Settings Grid */}
        <div className="grid grid-cols-2 gap-3 mt-4 text-xs">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">تفضيل موضوع القص (غير متصل)</label>
            <select
              value={subject}
              onChange={e => setSubject(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="action">🎯 مساحة اللعب (موصى بها)</option>
              <option value="ball">⚽ الكرة</option>
              <option value="player">🏃 اللاعب (Player cam)</option>
            </select>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">التخطيط</label>
            <select
              value={layout}
              onChange={e => setLayout(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="single">🎬 عمودي واحد (موصى به)</option>
              <option value="split">شاشة مقسومة (تكرر رسوم البث)</option>
            </select>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">محرّك التتبّع</label>
            <select
              value={tracker}
              onChange={e => setTracker(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="auto">تلقائي (تفضيل فقط)</option>
              <option value="pro">احترافي (غير متصل)</option>
              <option value="classic">كلاسيكي (غير متصل)</option>
            </select>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">جودة كشف الكرة</label>
            <select
              value={quality}
              onChange={e => setQuality(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="auto">تلقائي (الأفضل لجهازك)</option>
              <option value="high">عالية — تقطيع وتكبير</option>
              <option value="balanced">متوازنة</option>
              <option value="fast">سريعة</option>
              <option value="ultra">قصوى (أبطأ، أدق)</option>
            </select>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">المقاس</label>
            <select
              value={outSize}
              onChange={e => setOutSize(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="1080x1920">1080x1920 (9:16 Full HD)</option>
              <option value="720x1280">720x1280 (9:16 HD)</option>
            </select>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">🎨 لون الهوية</label>
            <select
              value={accent}
              onChange={e => setAccent(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="auto">تلقائي (لون لبس الفريق)</option>
              <option value="#1E46EB">أزرق</option>
              <option value="#E12D37">أحمر</option>
              <option value="#2CB05F">أخضر</option>
              <option value="#F0BE28">أصفر</option>
              <option value="#9628DC">بنفسجي</option>
            </select>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">شدّة التتبّع (الإطار)</label>
            <select
              value={framing}
              onChange={e => setFraming(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="tight">ملتصق — الكرة وسط الإطار</option>
              <option value="normal">متوازن (موصى به)</option>
              <option value="loose">هادئ — حركة أقل</option>
            </select>
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">🖼️ الإطار العمودي</label>
            <select
              value={vcenter}
              onChange={e => setVcenter(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            >
              <option value="auto">تلقائي (قص 1.12× يتابع الكرة رأسياً)</option>
              <option value="off">كامل (الملعب كله)</option>
              <option value="1.25">مقرّب أكثر (1.25×)</option>
            </select>
          </div>
        </div>

        {/* Channel Name & Badge Sliders */}
        <div className="mt-4 p-3 bg-[#0c1219] border border-[#222e3d] rounded-xl text-xs">
          <label className="flex items-center gap-2 mb-2 font-semibold text-white cursor-pointer">
            <input
              type="checkbox"
              checked={showChannelName}
              onChange={e => setShowChannelName(e.target.checked)}
              className="rounded"
            />
            <span>إظهار اسم القناة في شارة هذا المقطع</span>
          </label>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
            <div>
              <div className="flex justify-between text-[#8ea0b5] mb-1">
                <span>موضع شارة القناة الرأسي</span>
                <span className="text-[#36d1dc] font-mono">{brandY}% من الأعلى</span>
              </div>
              <input
                type="range"
                min="3"
                max="35"
                step="0.5"
                value={brandY}
                onChange={e => setBrandY(Number(e.target.value))}
                className="w-full accent-[#36d1dc] h-1.5 bg-[#090e14] rounded cursor-pointer"
              />
            </div>

            <div>
              <div className="flex justify-between text-[#8ea0b5] mb-1">
                <span>حجم شارة القناة</span>
                <span className="text-[#36d1dc] font-mono">{brandScale}%</span>
              </div>
              <input
                type="range"
                min="55"
                max="120"
                step="5"
                value={brandScale}
                onChange={e => setBrandScale(Number(e.target.value))}
                className="w-full accent-[#36d1dc] h-1.5 bg-[#090e14] rounded cursor-pointer"
              />
            </div>
          </div>
          <p className="text-[10px] text-[#8ea0b5] mt-2 leading-relaxed">
            الافتراضي 13% لتقليل التداخل مع لوحة النتيجة. علامات البث الأصلية تبقى كما هي وفقاً لميثاق النزاهة الرياضية.
          </p>
        </div>

        {/* Manual Trim */}
        <div className="grid grid-cols-2 gap-3 mt-4 text-xs">
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">البداية (mm:ss أو ثوانٍ)</label>
            <input
              type="text"
              value={trimStart}
              onChange={e => setTrimStart(e.target.value)}
              placeholder="فارغ = من البداية"
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            />
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">النهاية (mm:ss أو ثوانٍ)</label>
            <input
              type="text"
              value={trimEnd}
              onChange={e => setTrimEnd(e.target.value)}
              placeholder="فارغ = للنهاية"
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white"
            />
          </div>
        </div>

        {/* Checkbox Options */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mt-4 text-xs">
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input type="checkbox" checked={autocut} onChange={e => setAutocut(e.target.checked)} className="rounded" />
            <span>✂️ اقتطاع لحظة الهدف تلقائياً من الصوت</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input type="checkbox" checked={bridge} onChange={e => setBridge(e.target.checked)} className="rounded" />
            <span>تفضيل جسر القالب (غير متصل)</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input type="checkbox" checked={replay} onChange={e => setReplay(e.target.checked)} className="rounded" />
            <span>🎬 إعادة بطيئة للحظة الهدف (Slow-Mo)</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input type="checkbox" checked={burst} onChange={e => setBurst(e.target.checked)} className="rounded" />
            <span>💥 انفجار ومؤثر «هدف!»</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input type="checkbox" checked={hook} onChange={e => setHook(e.target.checked)} className="rounded" />
            <span>🎬 مقدمة سينمائية خاطفة</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input type="checkbox" checked={retryHealing} onChange={e => setRetryHealing(e.target.checked)} className="rounded" />
            <span>تفضيل إعادة المحاولة (غير متصل)</span>
          </label>
        </div>

        {/* Action Buttons */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 mt-5">
          <button
            onClick={() => handleStartProcessing(true)}
            className="px-3.5 py-2.5 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 transition flex items-center justify-center gap-1.5 shadow"
          >
            <Play className="w-3.5 h-3.5" />
            <span>إنشاء بطاقة معاينة 6s</span>
          </button>

          <button
            onClick={() => handleStartProcessing(false)}
            className="px-3.5 py-2.5 rounded-xl text-xs font-black text-white bg-gradient-to-r from-[#e63946] to-[#b3212c] hover:brightness-110 transition flex items-center justify-center gap-1.5 shadow-lg shadow-[#e63946]/30"
          >
            <Zap className="w-4 h-4" />
            <span>إنشاء بطاقة مهمة تجريبية</span>
          </button>

          <button
            onClick={() => setActiveViewMode(activeViewMode === 'tracker' ? 'standard' : 'tracker')}
            className={`px-3.5 py-2.5 rounded-xl text-xs font-bold transition flex items-center justify-center gap-1.5 border ${
              activeViewMode === 'tracker'
                ? 'bg-[#36d1dc] text-[#0a1118] border-[#36d1dc]'
                : 'bg-[#182231] hover:bg-[#222e3d] text-[#36d1dc] border-[#36d1dc]/40'
            }`}
          >
            <Target className="w-4 h-4" />
            <span>معاينة حركة توضيحية</span>
          </button>

          <button
            onClick={() => {
              handlePreviewScoutCandidate({
                id: 'preview-sample',
                index: 0,
                dur: 15,
                start: 0,
                end: 15,
                sample_t: 7.5,
                source_duration: 15,
                thumb: 'https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=720&auto=format&fit=crop&q=80',
              }, 0, 6);
            }}
            className="px-3.5 py-2.5 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition flex items-center justify-center gap-1.5"
          >
            <Eye className="w-3.5 h-3.5" />
            <span>🖼️ صورة</span>
          </button>
        </div>
      </div>

      {/* Right Column: Presets & Commentary Voice Studio */}
      <div>
        <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-5 shadow-xl">
          <h2 className="text-sm font-bold text-[#cfdcec] flex items-center gap-2 mb-3">
            <span className="w-5 h-5 rounded-md bg-[#182231] border border-[#2c3a4d] grid place-items-center text-xs text-[#8ea0b5]">
              2
            </span>
            <span>قوالب سريعة وضوابط النشر</span>
          </h2>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
            <button
              onClick={() => applyPreset('pro')}
              className="px-3 py-2 rounded-xl text-xs font-bold bg-[#182231] hover:bg-[#222e3d] text-white border border-[#2c3a4d] transition"
            >
              🎥 عمودي نظيف
            </button>
            <button
              onClick={() => applyPreset('goal')}
              className="px-3 py-2 rounded-xl text-xs font-bold bg-[#182231] hover:bg-[#222e3d] text-white border border-[#2c3a4d] transition"
            >
              ⚽ هدف
            </button>
            <button
              onClick={() => applyPreset('celeb')}
              className="px-3 py-2 rounded-xl text-xs font-bold bg-[#182231] hover:bg-[#222e3d] text-white border border-[#2c3a4d] transition"
            >
              🎉 احتفال
            </button>
            <button
              onClick={() => applyPreset('fast')}
              className="px-3 py-2 rounded-xl text-xs font-bold bg-[#182231] hover:bg-[#222e3d] text-white border border-[#2c3a4d] transition"
            >
              ⚡ سريع
            </button>
          </div>

          {/* Source marks & ball trail */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs pb-3 border-b border-[#222e3d]">
            <div className="rounded-lg border border-[#222e3d] bg-[#0c1219] px-3 py-2 text-[#8ea0b5]">
              علامات البث المصدرية محفوظة؛ لا تتوفر إزالة العلامات في نموذج الويب.
            </div>

            <div className="rounded-lg border border-[#664c30] bg-[#282114] px-3 py-2 text-[#e5c99a]">
              مسار الكرة غير متصل بمحرك الكشف في هذا النموذج.
            </div>
          </div>

          <div className="mt-3 rounded-xl border border-[#664c30] bg-[#282114] p-3 text-[11px] leading-relaxed text-[#e5c99a]">
            الرفع التلقائي غير متاح في هذا النموذج. لن يُرسل الملف إلى YouTube أو Telegram.
          </div>

          {/* Voice Studio Panel */}
          <VoiceStudio voice={voice} onChange={onVoiceChange} onToast={onToast} />
        </div>
      </div>

      {/* Full Width Bottom: Scout Match Review */}
      <div className="col-span-1 xl:col-span-2">
        <ScoutReview
          sourceFile={selectedFile}
          sourceUrl={extractedVideoUrl || srcUrl}
          maxDuration={maxDur}
          onUseCandidate={handleUseScoutCandidate}
          onPreviewCandidate={handlePreviewScoutCandidate}
          onBatchProcess={handleBatchScout}
          sourceLabel={selectedFile?.name || srcUrl}
        />
      </div>
    </div>
  </div>
);
};
