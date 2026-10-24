import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { HeroBanner } from './components/HeroBanner';
import { NewReelTab } from './components/tabs/NewReelTab';
import { JobsTab } from './components/tabs/JobsTab';
import { BrandTab } from './components/tabs/BrandTab';
import { ChannelTab } from './components/tabs/ChannelTab';
import { AutomationTab } from './components/tabs/AutomationTab';
import { SettingsTab } from './components/tabs/SettingsTab';
import { CreativeStudioTab } from './components/tabs/CreativeStudioTab';
import { VideoModal } from './components/modals/VideoModal';
import { RightsGateModal } from './components/modals/RightsGateModal';
import { storage } from './services/storage';
import { AppSettings, AutomationSettings, CreativeDraft, Job, LogoItem, LogoSettings, VoiceSettings, ChannelPost } from './types';
import confetti from 'canvas-confetti';

export function App() {
  // Global State
  const [activeTab, setActiveTab] = useState<'new' | 'jobs' | 'brand' | 'chan' | 'auto' | 'set' | 'studio'>('new');
  const [settings, setSettings] = useState<AppSettings>(storage.getSettings());
  const [jobs, setJobs] = useState<Job[]>(storage.getJobs());
  const [voice, setVoice] = useState<VoiceSettings>(storage.getVoice());
  const [logos, setLogos] = useState<LogoItem[]>(storage.getLogos());
  const [logoSettings, setLogoSettings] = useState<LogoSettings>(storage.getLogoSettings());
  const [automation, setAutomation] = useState<AutomationSettings>(storage.getAutomation());
  const [drafts, setDrafts] = useState<CreativeDraft[]>(storage.getDrafts());

  // Active Modals
  const [modalVideoJob, setModalVideoJob] = useState<Job | null>(null);
  const [rightsModalState, setRightsModalState] = useState<{ job: Job; mode: 'review' | 'youtube' } | null>(null);

  // Toasts
  const [toasts, setToasts] = useState<Array<{ id: string; msg: string; type: 'ok' | 'err' }>>([]);

  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    const id = 'toast-' + Math.random().toString(36).substring(2, 9);
    setToasts(prev => [...prev, { id, msg, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  };

  // Background processor for running jobs (simulates the 6-stage rendering pipeline with NVENC resilience)
  useEffect(() => {
    const interval = setInterval(() => {
      setJobs(prevJobs => {
        let changed = false;
        const updated = prevJobs.map(job => {
          if (job.status === 'running') {
            changed = true;
            const nextProgress = Math.min(100, job.progress + 15);
            let nextStage = job.stage;
            let nextStageText = job.stage_text;

            if (nextProgress >= 100) {
              return {
                ...job,
                status: 'done' as const,
                stage: 6,
                stage_text: 'اكتملت المعالجة بنجاح',
                progress: 100,
                elapsed_s: Number((job.elapsed_s + 2.5).toFixed(1)),
                audit_log: [
                  ...job.audit_log,
                  {
                    time: new Date().toLocaleTimeString('ar-EG'),
                    event: 'render_complete',
                    detail: 'تم التصدير بنجاح عبر مشفر NVENC H.264 بمعدل 1080x1920 وبدون أخطاء',
                  },
                ],
              };
            } else if (nextProgress > 80) {
              nextStage = 6;
              nextStageText = 'الرندر والترميز (NVENC H.264)';
            } else if (nextProgress > 60) {
              nextStage = 5;
              nextStageText = 'التتبّع والكاميرا العمودية';
            } else if (nextProgress > 40) {
              nextStage = 4;
              nextStageText = 'كشف اللاعبين والمساحات';
            } else if (nextProgress > 20) {
              nextStage = 3;
              nextStageText = 'كشف الكرة (YOLO11n-q16)';
            }

            return {
              ...job,
              progress: nextProgress,
              stage: nextStage,
              stage_text: nextStageText,
              elapsed_s: Number((job.elapsed_s + 1.2).toFixed(1)),
            };
          }
          return job;
        });

        if (changed) {
          storage.saveJobs(updated);
        }
        return updated;
      });
    }, 1800);

    return () => clearInterval(interval);
  }, []);

  // Handlers
  const handleCreateJob = (jobData: Partial<Job>) => {
    const newJob: Job = {
      id: 'job-' + Math.floor(1000 + Math.random() * 9000),
      title: jobData.title || 'ريل جديد',
      filename: jobData.filename || 'clip.mp4',
      src_url: jobData.src_url,
      status: jobData.status || 'running',
      stage: jobData.stage || 1,
      stage_text: jobData.stage_text || 'تجهيز الملف',
      progress: jobData.progress || 10,
      duration: jobData.duration || 58,
      created_at: 'الآن',
      elapsed_s: 0,
      fps: 59.94,
      speed_x: 1.95,
      out_size: jobData.out_size || '1080x1920',
      quality: jobData.quality || 'auto',
      subject: jobData.subject || 'action',
      layout: jobData.layout || 'single',
      accent: jobData.accent || 'auto',
      tracker: jobData.tracker || 'pro',
      show_channel_name: jobData.show_channel_name ?? true,
      brand_y: jobData.brand_y ?? 13,
      brand_scale: jobData.brand_scale ?? 100,
      rights_status: jobData.rights_status || 'pending',
      youtube_status: jobData.youtube_status || 'none',
      output_url: jobData.output_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
      thumbnail_url: jobData.thumbnail_url || 'https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=720&auto=format&fit=crop&q=80',
      commentary_text: jobData.commentary_text,
      audit_log: jobData.audit_log || [
        {
          time: new Date().toLocaleTimeString('ar-EG'),
          event: 'job_enqueued',
          detail: 'تم إنشاء المهمة عبر واجهة المستخدم',
        },
      ],
      quality_report: {
        ball_detections: 980,
        ball_confidence_avg: 0.93,
        tracking_switches: 0,
        camera_smoothness: 0.97,
        encoder: 'h264_nvenc',
        failover_applied: false,
      },
    };

    const updated = [newJob, ...jobs];
    setJobs(updated);
    storage.saveJobs(updated);
  };

  const handleBatchCreateJobs = (batchData: Array<Partial<Job>>) => {
    const newItems: Job[] = batchData.map((b, idx) => ({
      id: 'job-' + Math.floor(1000 + Math.random() * 9000 + idx),
      title: b.title || `ريل ${idx + 1}`,
      filename: b.filename || `clip_${idx + 1}.mp4`,
      src_url: b.src_url,
      status: b.status || (idx === 0 ? 'running' : 'queued'),
      stage: b.stage || (idx === 0 ? 1 : 0),
      stage_text: b.stage_text || (idx === 0 ? 'تجهيز المقطع' : 'في الانتظار'),
      progress: b.progress || (idx === 0 ? 15 : 0),
      duration: b.duration || 30,
      created_at: 'الآن',
      elapsed_s: 0,
      fps: 60,
      speed_x: 2.1,
      out_size: b.out_size || '1080x1920',
      quality: b.quality || 'auto',
      subject: b.subject || 'action',
      layout: b.layout || 'single',
      accent: b.accent || 'auto',
      tracker: b.tracker || 'pro',
      show_channel_name: b.show_channel_name ?? true,
      brand_y: b.brand_y ?? 13,
      brand_scale: b.brand_scale ?? 100,
      rights_status: 'pending',
      youtube_status: 'none',
      output_url: b.output_url || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
      thumbnail_url: b.thumbnail_url || 'https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=720&auto=format&fit=crop&q=80',
      commentary_text: b.commentary_text,
      audit_log: b.audit_log || [],
      quality_report: {
        ball_detections: 750,
        ball_confidence_avg: 0.92,
        tracking_switches: 0,
        camera_smoothness: 0.98,
        encoder: 'h264_nvenc',
        failover_applied: false,
      },
    }));

    const updated = [...newItems, ...jobs];
    setJobs(updated);
    storage.saveJobs(updated);
  };

  const handlePublishTelegram = (job: Job) => {
    const updated = jobs.map(j => {
      if (j.id === job.id) {
        return {
          ...j,
          telegram_published: true,
          audit_log: [
            ...j.audit_log,
            {
              time: new Date().toLocaleTimeString('ar-EG'),
              event: 'published_telegram',
              detail: `نُشر بنجاح على القناة الرسمية ${settings.telegram_chat || '@elhadath_reels'}`,
            },
          ],
        };
      }
      return j;
    });
    setJobs(updated);
    storage.saveJobs(updated);
    showToast(`تم نشر «${job.title}» على تيليجرام بنجاح 📤`, 'ok');
    confetti({ particleCount: 40, spread: 50 });
  };

  const handleSuggestTitle = (job: Job) => {
    const suggestions = [
      `صاروخية لا تُصد ولا تُرد من قلب المعركة! ⚽🔥`,
      `كيف مرت هذه الكرة في الشباك؟! لقطة للتاريخ 🤯`,
      `أفضل لقطة كروية في هذه الجولة بدون منازع! ⚡👑`,
      `عندما يكتب الأبطال مجدهم بالقدم اليسرى! 🇩🇿⚽`,
    ];
    const picked = suggestions[Math.floor(Math.random() * suggestions.length)];
    const updated = jobs.map(j => (j.id === job.id ? { ...j, title: picked } : j));
    setJobs(updated);
    storage.saveJobs(updated);
    showToast(`تم تحديث العنوان الذكي: ${picked}`, 'ok');
  };

  const handleRetryFailed = () => {
    const updated = jobs.map(j =>
      j.status === 'failed'
        ? {
            ...j,
            status: 'running' as const,
            progress: 10,
            stage: 1,
            stage_text: 'إعادة محاولة المعالجة',
          }
        : j
    );
    setJobs(updated);
    storage.saveJobs(updated);
    showToast('تمت إعادة إدراج المهام الفاشلة في طابور المعالجة', 'ok');
  };

  const handleClearFinished = () => {
    const remaining = jobs.filter(j => j.status !== 'done');
    setJobs(remaining);
    storage.saveJobs(remaining);
    showToast('تم تنظيف المهام المكتملة بنجاح 🧹', 'ok');
  };

  const handleMontage = () => {
    const doneJobs = jobs.filter(j => j.status === 'done').slice(0, 3);
    if (doneJobs.length === 0) {
      showToast('يجب أن تكون هناك مهمة مكتملة واحدة على الأقل لصنع المونتاج', 'err');
      return;
    }

    const montageJob: Partial<Job> = {
      title: '🏆 ريل الترتيب لأفضل 3 لقطات لهذا الأسبوع',
      filename: 'top3_montage_reel.mp4',
      duration: Math.min(58, doneJobs.reduce((acc, curr) => acc + curr.duration, 0)),
      status: 'running',
      stage: 1,
      stage_text: 'دمج المقاطع ومطابقة الموسيقى',
      progress: 20,
      out_size: '1080x1920',
      quality: 'ultra',
      subject: 'action',
      layout: 'single',
      accent: '#E12D37',
      tracker: 'pro',
      show_channel_name: true,
      brand_y: 13,
      brand_scale: 100,
      rights_status: 'recorded',
      youtube_status: 'none',
      output_url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyBlazes.mp4',
      thumbnail_url: doneJobs[0]?.thumbnail_url,
      commentary_text: 'ريل تجميعي لأروع لحظات الإثارة والمهارة!',
      audit_log: [
        {
          time: new Date().toLocaleTimeString('ar-EG'),
          event: 'montage_created',
          detail: `تم دمج ${doneJobs.length} مقاطع في ريل موحد`,
        },
      ],
    };

    handleCreateJob(montageJob);
    showToast('تم بدء تجميع ريل الترتيب (أفضل 3 أهداف)! 🏆', 'ok');
    confetti({ particleCount: 60, spread: 70 });
  };

  const handleDeleteJob = (id: string) => {
    const updated = jobs.filter(j => j.id !== id);
    setJobs(updated);
    storage.saveJobs(updated);
    showToast('تم حذف المهمة بنجاح', 'ok');
  };

  const handleSaveRightsRecord = (
    jobId: string,
    rightsData: {
      visualRights: boolean;
      audioRights: boolean;
      sourceRef: string;
      evidence: string;
      scope: 'private' | 'unlisted' | 'public';
      containsSyntheticMedia: boolean;
    }
  ) => {
    const updated = jobs.map(j => {
      if (j.id === jobId) {
        return {
          ...j,
          rights_status: 'recorded' as const,
          youtube_status: 'ready' as const,
          youtube_video_id: 'yt_' + Math.random().toString(36).substring(2, 8),
          audit_log: [
            ...j.audit_log,
            {
              time: new Date().toLocaleTimeString('ar-EG'),
              event: 'rights_gate_approved',
              detail: `تم توثيق الحقوق (${rightsData.scope}) - المرجع: ${rightsData.sourceRef} (synthetic: ${rightsData.containsSyntheticMedia})`,
            },
          ],
        };
      }
      return j;
    });
    setJobs(updated);
    storage.saveJobs(updated);
  };

  const handleConvertPostToReel = (post: ChannelPost) => {
    setActiveTab('new');
    showToast(`تم نقل المقطع «${post.title}» إلى نموذج الريل الجديد`, 'ok');
  };

  const handleExportDiagnostics = () => {
    const report = {
      app: 'elhadath-reels',
      version: '1.66.0',
      timestamp: new Date().toISOString(),
      platform: 'React / Vite / Tailwind v4 / Node 22',
      hardware: {
        detector: 'YOLO11n (quantize=16)',
        encoder: 'NVENC H.264 (Hardware) with automatic libx264 CPU failover',
        cuda: 'Available & Cached cleared pre-encode',
      },
      jobs_count: jobs.length,
      settings: {
        brand_name: settings.brand_name,
        show_channel_name: settings.show_channel_name,
        youtube_privacy: settings.youtube_privacy,
        device: settings.device,
      },
      audit_events_count: jobs.reduce((acc, j) => acc + (j.audit_log?.length || 0), 0),
    };

    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `elhadath_diagnostics_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('تم تحميل تقرير تشخيص النظام بنجاح', 'ok');
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Header */}
      <Header settings={settings} jobs={jobs} onExportDiagnostics={handleExportDiagnostics} />

      {/* Main Navigation Bar */}
      <nav className="sticky top-[69px] z-30 flex items-center gap-1.5 px-6 border-b border-[#222e3d] bg-[#0f151c]/70 backdrop-blur-md overflow-x-auto">
        <button
          onClick={() => setActiveTab('new')}
          className={`flex items-center gap-1.5 py-3.5 px-4 text-xs font-bold border-b-2 transition whitespace-nowrap ${
            activeTab === 'new'
              ? 'text-white border-[#36d1dc] bg-gradient-to-b from-[#36d1dc]/10 to-transparent'
              : 'text-[#8ea0b5] border-transparent hover:text-white'
          }`}
        >
          <span>⚡ مقطع جديد</span>
        </button>

        <button
          onClick={() => setActiveTab('jobs')}
          className={`flex items-center gap-2 py-3.5 px-4 text-xs font-bold border-b-2 transition whitespace-nowrap ${
            activeTab === 'jobs'
              ? 'text-white border-[#36d1dc] bg-gradient-to-b from-[#36d1dc]/10 to-transparent'
              : 'text-[#8ea0b5] border-transparent hover:text-white'
          }`}
        >
          <span>🎬 المهام</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#182231] border border-[#2c3a4d] text-[#36d1dc] font-mono">
            {jobs.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('brand')}
          className={`flex items-center gap-1.5 py-3.5 px-4 text-xs font-bold border-b-2 transition whitespace-nowrap ${
            activeTab === 'brand'
              ? 'text-white border-[#36d1dc] bg-gradient-to-b from-[#36d1dc]/10 to-transparent'
              : 'text-[#8ea0b5] border-transparent hover:text-white'
          }`}
        >
          <span>🎨 الهوية والشعار</span>
        </button>

        <button
          onClick={() => setActiveTab('chan')}
          className={`flex items-center gap-1.5 py-3.5 px-4 text-xs font-bold border-b-2 transition whitespace-nowrap ${
            activeTab === 'chan'
              ? 'text-white border-[#36d1dc] bg-gradient-to-b from-[#36d1dc]/10 to-transparent'
              : 'text-[#8ea0b5] border-transparent hover:text-white'
          }`}
        >
          <span>📡 القناة</span>
        </button>

        <button
          onClick={() => setActiveTab('auto')}
          className={`flex items-center gap-1.5 py-3.5 px-4 text-xs font-bold border-b-2 transition whitespace-nowrap ${
            activeTab === 'auto'
              ? 'text-white border-[#36d1dc] bg-gradient-to-b from-[#36d1dc]/10 to-transparent'
              : 'text-[#8ea0b5] border-transparent hover:text-white'
          }`}
        >
          <span>🤖 الأتمتة</span>
        </button>

        <button
          onClick={() => setActiveTab('set')}
          className={`flex items-center gap-1.5 py-3.5 px-4 text-xs font-bold border-b-2 transition whitespace-nowrap ${
            activeTab === 'set'
              ? 'text-white border-[#36d1dc] bg-gradient-to-b from-[#36d1dc]/10 to-transparent'
              : 'text-[#8ea0b5] border-transparent hover:text-white'
          }`}
        >
          <span>⚙️ الإعدادات</span>
        </button>

        {/* Studio Link / Tab with special glow */}
        <button
          onClick={() => setActiveTab('studio')}
          className={`flex items-center gap-1.5 py-3.5 px-4 text-xs font-black border-b-2 transition whitespace-nowrap mr-auto ${
            activeTab === 'studio'
              ? 'text-white border-[#44d2c2] bg-gradient-to-b from-[#44d2c2]/15 to-transparent'
              : 'text-[#44d2c2] hover:text-white hover:border-[#44d2c2]/50'
          }`}
        >
          <span>🎬 محتوى الريلز</span>
        </button>
      </nav>

      {/* Main Content Area */}
      <main className="flex-1 max-w-[1500px] w-full mx-auto p-4 sm:p-6">
        {/* Hero banner displayed on primary tabs */}
        {(activeTab === 'new' || activeTab === 'jobs') && (
          <HeroBanner
            jobs={jobs}
            onFocusNew={() => setActiveTab('new')}
            onFocusJobs={() => setActiveTab('jobs')}
          />
        )}

        {/* Tab 1: New Reel */}
        {activeTab === 'new' && (
          <NewReelTab
            settings={settings}
            voice={voice}
            onVoiceChange={updated => {
              setVoice(updated);
              storage.saveVoice(updated);
            }}
            onCreateJob={handleCreateJob}
            onBatchCreateJobs={handleBatchCreateJobs}
            onPreviewVideo={j => setModalVideoJob(j)}
            onToast={showToast}
          />
        )}

        {/* Tab 2: Jobs Center */}
        {activeTab === 'jobs' && (
          <JobsTab
            jobs={jobs}
            onPlayJob={j => setModalVideoJob(j)}
            onOpenRightsModal={j => setRightsModalState({ job: j, mode: 'review' })}
            onOpenYoutubeModal={j => setRightsModalState({ job: j, mode: 'youtube' })}
            onPublishTelegram={handlePublishTelegram}
            onSuggestTitle={handleSuggestTitle}
            onRetryFailed={handleRetryFailed}
            onClearFinished={handleClearFinished}
            onMontage={handleMontage}
            onDeleteJob={handleDeleteJob}
            onToast={showToast}
          />
        )}

        {/* Tab 3: Brand & Logo */}
        {activeTab === 'brand' && (
          <BrandTab
            logos={logos}
            settings={logoSettings}
            onSaveSettings={updated => {
              setLogoSettings(updated);
              storage.saveLogoSettings(updated);
            }}
            onUploadLogo={newLogo => {
              const updated = [newLogo, ...logos];
              setLogos(updated);
              storage.saveLogos(updated);
            }}
            onDeleteLogo={id => {
              const updated = logos.filter(l => l.id !== id);
              setLogos(updated);
              storage.saveLogos(updated);
            }}
            onToast={showToast}
          />
        )}

        {/* Tab 4: Channel Scraper */}
        {activeTab === 'chan' && (
          <ChannelTab
            channelHandle={settings.telegram_channel}
            onConvertPostToReel={handleConvertPostToReel}
            onToast={showToast}
          />
        )}

        {/* Tab 5: Automation */}
        {activeTab === 'auto' && (
          <AutomationTab
            automation={automation}
            onSaveAutomation={(updated, startNow) => {
              setAutomation(updated);
              storage.saveAutomation(updated);
            }}
            onToast={showToast}
          />
        )}

        {/* Tab 6: Settings */}
        {activeTab === 'set' && (
          <SettingsTab
            settings={settings}
            onSaveSettings={updated => {
              setSettings(updated);
              storage.saveSettings(updated);
            }}
            onToast={showToast}
          />
        )}

        {/* Tab 7: Creative Studio */}
        {activeTab === 'studio' && (
          <CreativeStudioTab
            completedJobs={jobs.filter(j => j.status === 'done')}
            drafts={drafts}
            onSaveDraft={draft => {
              storage.addDraft(draft);
              setDrafts(storage.getDrafts());
            }}
            onDeleteDraft={id => {
              storage.deleteDraft(id);
              setDrafts(storage.getDrafts());
            }}
            onToast={showToast}
          />
        )}
      </main>

      {/* Video Preview Modal */}
      {modalVideoJob && (
        <VideoModal
          job={modalVideoJob}
          settings={settings}
          logoSettings={logoSettings}
          onClose={() => setModalVideoJob(null)}
        />
      )}

      {/* Rights Gate Compliance Modal */}
      {rightsModalState && (
        <RightsGateModal
          job={rightsModalState.job}
          mode={rightsModalState.mode}
          onClose={() => setRightsModalState(null)}
          onSaveRights={handleSaveRightsRecord}
          onToast={showToast}
        />
      )}

      {/* Stacking Toasts */}
      <div className="fixed bottom-5 left-5 z-50 flex flex-col gap-2 max-w-md pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`pointer-events-auto px-4 py-2.5 rounded-xl text-xs font-semibold shadow-2xl border transition-all animate-in slide-in-from-bottom-2 ${
              t.type === 'err'
                ? 'bg-[#27191b] border-[#704446] text-[#ffd6d9] border-r-4 border-r-[#e63946]'
                : 'bg-[#182231] border-[#2c3a4d] text-white border-r-4 border-r-[#25d07a]'
            }`}
          >
            {t.msg}
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;
