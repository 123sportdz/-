import { AppSettings, AutomationSettings, CreativeDraft, Job, LogoItem, LogoSettings, ScoutSession, VoiceSettings } from '../types';

const STORAGE_KEYS = {
  JOBS: 'elhadath_jobs',
  SETTINGS: 'elhadath_settings',
  LOGOS: 'elhadath_logos',
  LOGO_SETTINGS: 'elhadath_logo_settings',
  VOICE: 'elhadath_voice',
  AUTOMATION: 'elhadath_automation',
  DRAFTS: 'elhadath_drafts',
  SCOUT: 'elhadath_scout_session',
  VOICE_STUDIO_POSITION: 'elhadath_voice_studio_pos',
  VOICE_STUDIO_SIZE: 'elhadath_voice_studio_size',
};

const SESSION_KEYS = {
  GEMINI_API_KEY: 'elhadath_session_gemini_api_key',
};

const DEFAULT_SETTINGS: AppSettings = {
  brand_name: 'الحدث الرياضي',
  brand_url: 't.me/elhadath_sports',
  show_channel_name: true,
  telegram_channel: '@OffsideOffside1',
  youtube_channel_id: 'UC_ElhadathDZ_Reels',
  telegram_token: '',
  telegram_chat: '@elhadath_reels',
  device: 'auto',
  youtube_privacy: 'private',
  batch_size: 8,
  gemini_api_key: '',
  gemini_model: 'gemini-2.5-flash',
  auto_ai_title: true,
  auto_youtube: false,
  auto_telegram: false,
  schedule_peak: true,
  auto_translate: true,
  tg_user_linked: false,
  tg_phone: '',
};

const DEFAULT_VOICE: VoiceSettings = {
  commentary: true,
  commtext: true,
  voice_engine: 'auto',
  commentary_style: 'broadcast',
  edge_voice: 'ar-DZ-IsmaelNeural',
  gemini_voice: 'Fenrir',
  voice_rate: 10,
  voice_pitch: 0,
  voice_gain: 1.9,
  voice_duck: 0.22,
  commentary_energy: 70,
  commentary_words: 22,
  voice_mix: 'auto',
  commentary_script: '',
};

const DEFAULT_LOGO_SETTINGS: LogoSettings = {
  selectedLogoId: 'logo-1',
  position: 'top-right',
  scale: 16,
  opacity: 95,
  darkPlate: false,
  enabled: true,
};

const DEFAULT_LOGOS: LogoItem[] = [
  {
    id: 'logo-1',
    name: 'شعار الحدث الرسمي (أحمر وأبيض)',
    url: 'https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=150&auto=format&fit=crop&q=80',
    size_kb: 48,
  },
  {
    id: 'logo-2',
    name: 'شعار البث الرياضي الذهبي',
    url: 'https://images.unsplash.com/photo-1579952363873-27f3bade9f55?w=150&auto=format&fit=crop&q=80',
    size_kb: 62,
  },
];

const DEFAULT_AUTOMATION: AutomationSettings = {
  enabled: false,
  interval: 300,
  limit: 5,
  source: 'telegram',
  channel: '@OffsideOffside1',
  folder: 'watch',
  rightsManifest: 'rights_manifest.json',
  quality: 'auto',
  layout: 'single',
  subject: 'action',
  upload: 'none',
  metrics: {
    lastRun: 'لم تبدأ أي دورة بعد',
    jobsProcessed: 0,
    runsTotal: 0,
    errors: 0,
    statusText: 'غير متصل — تفضيلات الأتمتة نموذجية فقط',
  },
};

const DEFAULT_JOBS: Job[] = [
  {
    id: 'job-9842',
    title: 'صاروخية محرز في الوقت القاتل ⚽🇩🇿',
    label: 'هدف محلي',
    filename: 'mahrez_last_minute_screamer.mp4',
    src_url: 'https://t.me/OffsideOffside1/2984',
    status: 'done',
    stage: 6,
    stage_text: 'اكتملت المعالجة بنجاح',
    progress: 100,
    duration: 34,
    created_at: 'منذ 25 دقيقة',
    elapsed_s: 18.4,
    fps: 59.94,
    speed_x: 1.85,
    out_size: '1080x1920',
    quality: 'ultra',
    subject: 'action',
    layout: 'single',
    accent: '#1E46EB',
    tracker: 'pro',
    show_channel_name: true,
    brand_y: 13,
    brand_scale: 100,
    rights_status: 'pending',
    youtube_status: 'unchecked',
    telegram_published: false,
    output_url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
    thumbnail_url: 'https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=720&auto=format&fit=crop&q=80',
    commentary_text: 'الله يا رياض! تسديدة من خارج منطقة الجزاء تسكن الشباك المستحيلة!',
    audit_log: [
      { time: '14:02:10', event: 'job_enqueued', detail: 'مصدر المقطع: رابط تيليجرام @OffsideOffside1' },
      { time: '14:02:12', event: 'detector_init', detail: 'تم تحميل YOLO11n مع دقة quantize=16 (الذاكرة محررة)' },
      { time: '14:02:22', event: 'render_complete', detail: 'استخدم NVENC H.264 بمعدل 1080x1920 وبدون أخطاء' },
    ],
    quality_report: {
      ball_detections: 1024,
      ball_confidence_avg: 0.94,
      tracking_switches: 0,
      camera_smoothness: 0.98,
      encoder: 'h264_nvenc (Hardware)',
      failover_applied: false,
    },
  },
  {
    id: 'job-9841',
    title: 'تصدي إعجازي من الحارس قبل أن تعبر الخط 🧤',
    label: 'لقطة دفاعية',
    filename: 'great_goal_line_save.mp4',
    src_url: 'https://t.me/OffsideOffside1/2982',
    status: 'done',
    stage: 6,
    stage_text: 'اكتملت المعالجة بنجاح',
    progress: 100,
    duration: 28,
    created_at: 'منذ ساعة',
    elapsed_s: 14.2,
    fps: 60.0,
    speed_x: 2.1,
    out_size: '1080x1920',
    quality: 'high',
    subject: 'ball',
    layout: 'single',
    accent: '#2CB05F',
    tracker: 'pro',
    show_channel_name: true,
    brand_y: 13,
    brand_scale: 100,
    rights_status: 'pending',
    youtube_status: 'unchecked',
    telegram_published: false,
    output_url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4',
    thumbnail_url: 'https://images.unsplash.com/photo-1518091043644-c1d4457512c6?w=720&auto=format&fit=crop&q=80',
    commentary_text: 'مستحيل! بأطراف الأصابع يمنع هدفاً محققاً كان سيهز المدرجات!',
    audit_log: [
      { time: '13:30:00', event: 'job_enqueued', detail: 'رفع محلي عبر لوحة التحكم' },
      { time: '13:30:14', event: 'render_complete', detail: 'المقاس 1080x1920 معدل الإطارات 60.0 fps' },
    ],
    quality_report: {
      ball_detections: 840,
      ball_confidence_avg: 0.91,
      tracking_switches: 1,
      camera_smoothness: 0.96,
      encoder: 'libx264 (CPU Fallback)',
      failover_applied: true,
    },
  },
  {
    id: 'job-9840',
    title: 'مراوغة مارادونية وتمريرة الهدف الذهبي ⚡',
    label: 'مهارة فردية',
    filename: 'dribble_and_assist.mp4',
    status: 'done',
    stage: 6,
    stage_text: 'اكتملت المعالجة',
    progress: 100,
    duration: 42,
    created_at: 'منذ ساعتين',
    elapsed_s: 22.8,
    fps: 59.94,
    speed_x: 1.84,
    out_size: '1080x1920',
    quality: 'balanced',
    subject: 'player',
    layout: 'single',
    accent: '#E12D37',
    tracker: 'auto',
    show_channel_name: true,
    brand_y: 13,
    brand_scale: 100,
    rights_status: 'pending',
    youtube_status: 'unchecked',
    telegram_published: false,
    output_url: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyBlazes.mp4',
    thumbnail_url: 'https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=720&auto=format&fit=crop&q=80',
    commentary_text: 'يمر ببراعة من الأول والثاني ويهدي الكرة على طبق من ذهب!',
    audit_log: [
      { time: '12:15:10', event: 'job_enqueued', detail: 'مقطع سريع' },
      { time: '12:15:33', event: 'render_complete', detail: 'نجاح التصدير' },
    ],
    quality_report: {
      ball_detections: 1250,
      ball_confidence_avg: 0.95,
      tracking_switches: 0,
      camera_smoothness: 0.99,
      encoder: 'h264_nvenc',
      failover_applied: false,
    },
  },
];

const DEFAULT_DRAFTS: CreativeDraft[] = [
  {
    id: 'draft-1',
    title: 'صاروخية محرز - تعليق حماسي',
    mode: 'script',
    job_id: 'job-9842',
    job_title: 'صاروخية محرز في الوقت القاتل ⚽🇩🇿',
    topic: 'هدف في الدقيقة 92 حسم المباراة',
    source: 'رياض محرز يسدد بقدمه اليسرى من مسافة 25 متراً في الزاوية التسعين.',
    platform: 'instagram',
    language: 'ar',
    length: 'short',
    tone: 'حماسي وطبيعي',
    audience: 'عشاق الكرة الجزائرية',
    instructions: 'ركز على توقيت اللحظة وجمال التسديدة في أقل من 22 كلمة.',
    text: 'الله يا رياض! في الدقيقة القاتلة، يطلق يسارية صاروخية تستقر في المقص الأيسر! جنون في المدرجات وفرحة لا توصف!',
    created_at: 'منذ نصف ساعة',
  },
  {
    id: 'draft-2',
    title: 'عناوين مقترحة لريل المراوغة',
    mode: 'title',
    job_id: 'job-9840',
    job_title: 'مراوغة مارادونية وتمريرة الهدف الذهبي ⚡',
    topic: 'مهارة استثنائية وأسيست حاسم',
    source: 'مراوغة لاعبين في مساحة ضيقة وتمريرة عرضية متقنة.',
    platform: 'tiktok',
    language: 'ar',
    length: 'short',
    tone: 'حماسي وطبيعي',
    audience: 'مشاهدو التيك توك',
    instructions: 'عناوين خاطفة ومثيرة للاهتمام',
    text: '1. هل رأيت أروع من هذا الأسيست في حياتك؟ 🤯\n2. كيف مرّ من بين مدافعين وصنع المعجزة؟! ⚡\n3. مهارة تُدرّس في كتب كرة القدم! ⚽👑\n4. أسيست الموسم بدون منازع!',
    created_at: 'منذ ساعتين',
  },
];

const SIMULATED_SUCCESS_EVENTS = new Set([
  'job_enqueued',
  'detector_init',
  'render_complete',
  'rights_verified',
  'rights_gate_approved',
  'published_telegram',
  'youtube_uploaded',
  'youtube_upload_complete',
]);

function normalizePrototypeJobs(jobs: Job[]): Job[] {
  return jobs
    .filter(job => job && typeof job === 'object')
    .map(job => {
      const declaration = job.rights_declaration;
      const hasLocalDeclaration = Boolean(
        declaration &&
        typeof declaration.sourceRef === 'string' && declaration.sourceRef.trim() &&
        typeof declaration.evidence === 'string' && declaration.evidence.trim()
      );
      const auditLog = Array.isArray(job.audit_log)
        ? job.audit_log.filter(event => event && !SIMULATED_SUCCESS_EVENTS.has(event.event))
        : [];
      return {
        ...job,
        stage_text: job.status === 'done' ? 'مهمة نموذجية مكتملة — لا يوجد رندر فعلي' : job.stage_text,
        rights_status: hasLocalDeclaration ? 'recorded' : 'pending',
        youtube_status: 'none',
        youtube_video_id: undefined,
        telegram_published: false,
        audit_log: auditLog,
      };
    });
}

export const storage = {
  getSettings(): AppSettings {
    const raw = localStorage.getItem(STORAGE_KEYS.SETTINGS);
    let saved: Partial<AppSettings> = {};
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          saved = parsed as Partial<AppSettings>;
        }
      } catch {
        saved = {};
      }
    }

    const legacyGeminiKey = String(saved.gemini_api_key || '').trim();
    let sessionGeminiKey = '';
    try {
      sessionGeminiKey = sessionStorage.getItem(SESSION_KEYS.GEMINI_API_KEY) || '';
      if (!sessionGeminiKey && legacyGeminiKey) {
        sessionStorage.setItem(SESSION_KEYS.GEMINI_API_KEY, legacyGeminiKey);
        sessionGeminiKey = legacyGeminiKey;
      }
    } catch {
      sessionGeminiKey = '';
    }

    const persisted: Partial<AppSettings> = { ...DEFAULT_SETTINGS, ...saved };
    delete persisted.gemini_api_key;
    delete persisted.telegram_token;
    delete persisted.tg_phone;
    delete persisted.tg_user_linked;
    if (raw) localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(persisted));

    return {
      ...DEFAULT_SETTINGS,
      ...persisted,
      gemini_api_key: sessionGeminiKey,
      telegram_token: '',
      tg_phone: '',
      tg_user_linked: false,
    };
  },

  saveSettings(settings: AppSettings): void {
    try {
      const apiKey = String(settings.gemini_api_key || '').trim();
      if (apiKey) sessionStorage.setItem(SESSION_KEYS.GEMINI_API_KEY, apiKey);
      else sessionStorage.removeItem(SESSION_KEYS.GEMINI_API_KEY);
    } catch {}

    const persisted: Partial<AppSettings> = { ...settings };
    delete persisted.gemini_api_key;
    delete persisted.telegram_token;
    delete persisted.tg_phone;
    delete persisted.tg_user_linked;
    localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(persisted));
  },

  clearAppData(): void {
    Object.values(STORAGE_KEYS).forEach(key => localStorage.removeItem(key));
    try {
      sessionStorage.removeItem(SESSION_KEYS.GEMINI_API_KEY);
    } catch {}
  },

  getVoice(): VoiceSettings {
    const raw = localStorage.getItem(STORAGE_KEYS.VOICE);
    if (!raw) return DEFAULT_VOICE;
    try {
      return { ...DEFAULT_VOICE, ...JSON.parse(raw) };
    } catch {
      return DEFAULT_VOICE;
    }
  },

  saveVoice(voice: VoiceSettings): void {
    localStorage.setItem(STORAGE_KEYS.VOICE, JSON.stringify(voice));
  },

  getJobs(): Job[] {
    const raw = localStorage.getItem(STORAGE_KEYS.JOBS);
    if (!raw) {
      const jobs = normalizePrototypeJobs(DEFAULT_JOBS);
      this.saveJobs(jobs);
      return jobs;
    }
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) throw new TypeError('Invalid prototype jobs');
      const jobs = normalizePrototypeJobs(parsed as Job[]);
      this.saveJobs(jobs);
      return jobs;
    } catch {
      const jobs = normalizePrototypeJobs(DEFAULT_JOBS);
      this.saveJobs(jobs);
      return jobs;
    }
  },

  saveJobs(jobs: Job[]): void {
    localStorage.setItem(STORAGE_KEYS.JOBS, JSON.stringify(jobs));
  },

  addJob(job: Job): void {
    const current = this.getJobs();
    this.saveJobs([job, ...current]);
  },

  updateJob(id: string, patch: Partial<Job>): Job | undefined {
    const current = this.getJobs();
    const index = current.findIndex(j => j.id === id);
    if (index === -1) return undefined;
    const updated = { ...current[index], ...patch };
    current[index] = updated;
    this.saveJobs(current);
    return updated;
  },

  deleteJob(id: string): void {
    const current = this.getJobs();
    this.saveJobs(current.filter(j => j.id !== id));
  },

  getLogos(): LogoItem[] {
    const raw = localStorage.getItem(STORAGE_KEYS.LOGOS);
    if (!raw) {
      this.saveLogos(DEFAULT_LOGOS);
      return DEFAULT_LOGOS;
    }
    try {
      return JSON.parse(raw);
    } catch {
      return DEFAULT_LOGOS;
    }
  },

  saveLogos(logos: LogoItem[]): void {
    localStorage.setItem(STORAGE_KEYS.LOGOS, JSON.stringify(logos));
  },

  getLogoSettings(): LogoSettings {
    const raw = localStorage.getItem(STORAGE_KEYS.LOGO_SETTINGS);
    if (!raw) return DEFAULT_LOGO_SETTINGS;
    try {
      return { ...DEFAULT_LOGO_SETTINGS, ...JSON.parse(raw) };
    } catch {
      return DEFAULT_LOGO_SETTINGS;
    }
  },

  saveLogoSettings(settings: LogoSettings): void {
    localStorage.setItem(STORAGE_KEYS.LOGO_SETTINGS, JSON.stringify(settings));
  },

  getAutomation(): AutomationSettings {
    const raw = localStorage.getItem(STORAGE_KEYS.AUTOMATION);
    let saved: Partial<AutomationSettings> = {};
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          saved = parsed as Partial<AutomationSettings>;
        }
      } catch {
        saved = {};
      }
    }
    return {
      ...DEFAULT_AUTOMATION,
      ...saved,
      enabled: false,
      upload: 'none',
      metrics: {
        ...DEFAULT_AUTOMATION.metrics,
        ...saved.metrics,
        jobsProcessed: 0,
        runsTotal: 0,
        errors: 0,
        lastRun: 'غير متاح في النموذج',
        statusText: 'غير متصل — تفضيلات الأتمتة نموذجية فقط',
      },
    };
  },

  saveAutomation(settings: AutomationSettings): void {
    const normalized = {
      ...settings,
      enabled: false,
      upload: 'none' as const,
      metrics: {
        ...settings.metrics,
        jobsProcessed: 0,
        runsTotal: 0,
        errors: 0,
        lastRun: 'غير متاح في النموذج',
        statusText: 'غير متصل — تفضيلات الأتمتة نموذجية فقط',
      },
    };
    localStorage.setItem(STORAGE_KEYS.AUTOMATION, JSON.stringify(normalized));
  },

  getDrafts(): CreativeDraft[] {
    const raw = localStorage.getItem(STORAGE_KEYS.DRAFTS);
    if (!raw) {
      this.saveDrafts(DEFAULT_DRAFTS);
      return DEFAULT_DRAFTS;
    }
    try {
      return JSON.parse(raw);
    } catch {
      return DEFAULT_DRAFTS;
    }
  },

  saveDrafts(drafts: CreativeDraft[]): void {
    localStorage.setItem(STORAGE_KEYS.DRAFTS, JSON.stringify(drafts.slice(0, 100)));
  },

  addDraft(draft: CreativeDraft): void {
    const drafts = this.getDrafts();
    const existingIndex = drafts.findIndex(d => d.id === draft.id);
    if (existingIndex >= 0) {
      drafts[existingIndex] = draft;
      this.saveDrafts(drafts);
    } else {
      this.saveDrafts([draft, ...drafts]);
    }
  },

  deleteDraft(id: string): void {
    const drafts = this.getDrafts();
    this.saveDrafts(drafts.filter(d => d.id !== id));
  },
};
