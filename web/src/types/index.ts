export type JobStatus = 'queued' | 'running' | 'done' | 'failed';

export interface Job {
  id: string;
  title: string;
  label?: string;
  filename: string;
  src_url?: string;
  status: JobStatus;
  stage: number;
  stage_text: string;
  progress: number;
  duration: number; // in seconds
  created_at: string;
  elapsed_s: number;
  fps: number;
  speed_x: number;
  out_size: string;
  quality: string;
  subject: string;
  layout: string;
  accent: string;
  tracker: string;
  show_channel_name: boolean;
  brand_y: number;
  brand_scale: number;
  rights_status: 'pending' | 'recorded';
  rights_declaration?: {
    visualRights: boolean;
    audioRights: boolean;
    sourceRef: string;
    evidence: string;
    scope: 'private' | 'unlisted' | 'public';
    containsSyntheticMedia: boolean;
    recorded_at: string;
  };
  youtube_status: 'none' | 'unchecked' | 'processing' | 'ready' | 'attention';
  youtube_video_id?: string;
  telegram_published?: boolean;
  output_url?: string;
  thumbnail_url?: string;
  commentary_text?: string;
  commentary_audio_url?: string;
  audit_log: Array<{
    time: string;
    event: string;
    detail: string;
  }>;
  quality_report?: {
    ball_detections: number;
    ball_confidence_avg: number;
    tracking_switches: number;
    camera_smoothness: number;
    encoder: string;
    failover_applied: boolean;
  };
}

export interface ScoutCandidate {
  id: string;
  index: number;
  dur: number;
  start: number;
  end: number;
  sample_t: number;
  source_duration: number;
  thumb: string;
}

export interface ScoutSession {
  id: string;
  status: 'queued' | 'downloading' | 'analyzing' | 'ready' | 'failed';
  stage: string;
  progress: number;
  duration: number;
  label?: string;
  error?: string;
  candidates: ScoutCandidate[];
}

export interface VoiceSettings {
  commentary: boolean;
  commtext: boolean;
  voice_engine: 'auto' | 'edge' | 'gemini';
  commentary_style: 'broadcast' | 'algerian' | 'analyst' | 'cinematic' | 'calm';
  edge_voice: string;
  gemini_voice: string;
  voice_rate: number; // -20 to +50
  voice_pitch: number; // -12 to +12
  voice_gain: number; // 0.5 to 3.0
  voice_duck: number; // 0 to 1
  commentary_energy: number; // 0 to 100
  commentary_words: number; // 8 to 80 (default 22)
  voice_mix: 'auto' | 'fixed' | 'original' | 'voice_only';
  commentary_script: string;
}

export interface LogoItem {
  id: string;
  name: string;
  url: string;
  size_kb: number;
}

export interface LogoSettings {
  selectedLogoId: string;
  position: 'top-left' | 'top-center' | 'top-right' | 'center-left' | 'center' | 'center-right' | 'bottom-left' | 'bottom-center' | 'bottom-right';
  scale: number; // 4 to 45%
  opacity: number; // 20 to 100%
  darkPlate: boolean;
  enabled: boolean;
}

export interface AutomationSettings {
  enabled: boolean;
  interval: number;
  limit: number;
  source: 'telegram' | 'folder' | 'both';
  channel: string;
  folder: string;
  rightsManifest: string;
  quality: string;
  layout: string;
  subject: string;
  upload: 'none' | 'telegram' | 'youtube' | 'both';
  metrics: {
    lastRun: string;
    jobsProcessed: number;
    runsTotal: number;
    errors: number;
    statusText: string;
  };
}

export interface AppSettings {
  brand_name: string;
  brand_url: string;
  show_channel_name: boolean;
  telegram_channel: string;
  youtube_channel_id: string;
  telegram_token: string;
  telegram_chat: string;
  device: string;
  youtube_privacy: 'private' | 'unlisted' | 'public';
  batch_size: number;
  gemini_api_key: string;
  gemini_model: string;
  auto_ai_title: boolean;
  auto_youtube: boolean;
  auto_telegram: boolean;
  schedule_peak: boolean;
  auto_translate: boolean;
  tg_user_linked: boolean;
  tg_phone?: string;
}

export interface CreativeDraft {
  id: string;
  title: string;
  mode: string;
  job_id?: string;
  job_title?: string;
  topic: string;
  source: string;
  platform: string;
  language: string;
  length: 'short' | 'medium' | 'long';
  tone: string;
  audience: string;
  instructions: string;
  text: string;
  created_at: string;
}

export interface ChannelPost {
  id: string;
  postId: number;
  title: string;
  text: string;
  date: string;
  duration: string;
  views: string;
  videoUrl: string;
  thumbUrl: string;
}
