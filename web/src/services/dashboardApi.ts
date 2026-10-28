export class DashboardApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'DashboardApiError';
  }
}

export interface DashboardConfig {
  max_upload_bytes: number;
  show_channel_name?: boolean;
  brand_name?: string;
}

export interface DashboardQueue {
  running: number;
  waiting: number;
  limit: number;
  gpu: boolean;
  gpu_limit: number;
  gpu_available: number;
  gpu_waiting: number;
}

export interface DashboardSystemInfo {
  python: string;
  cpu_cores: number;
  torch: string | null;
  cuda: boolean;
  gpu_name: string;
  vram_gb: number;
  device_cfg: string;
  ffmpeg: string;
  disk_free_gb: number;
  recommended: { quality: string; device: string; batch: number; tracker: string };
}

export interface DashboardJob {
  id: string;
  status: 'queued' | 'running' | 'cancelling' | 'done' | 'failed';
  stage?: string;
  progress?: number;
  duration?: number;
  created?: number;
  elapsed?: number;
  estimate?: number;
  title?: string;
  label?: string;
  media?: string;
  thumb?: string;
  quality_report?: { ok?: boolean; issues?: string[] };
  publish_in_progress?: boolean;
}

export interface DashboardScoutCandidate {
  start: number;
  end: number;
  dur: number;
  peak_t: number;
  score: number;
  cheer_z: number;
  reasons: string[];
  stats: { coverage: number; danger: number; speed_p95: number; n: number };
}

export interface DashboardScoutSession {
  id: string;
  status: 'queued' | 'downloading' | 'analyzing' | 'ready' | 'failed';
  stage: string;
  progress: number;
  duration: number;
  label?: string;
  error?: string;
  candidates: DashboardScoutCandidate[];
}

export interface CreateJobRequest {
  input: string;
  subject: 'action' | 'ball' | 'player';
  out_size: string;
  quality: 'auto' | 'fast' | 'balanced' | 'high' | 'ultra';
  layout: 'single' | 'split';
  tracker: 'auto' | 'pro' | 'classic';
  framing: string;
  zoom: string;
  max_dur: number;
  thumb: boolean;
  keep_watermarks: true;
  auto_youtube: false;
  auto_telegram: false;
  show_channel_name: boolean;
  scout_id?: string;
  scout_index?: number;
  start?: string;
  end?: string;
}

export async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\') || /[\u0000-\u001f]/.test(path)) {
    throw new DashboardApiError('مسار طلب غير صالح.', 400);
  }
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers,
  });
  const body = await response.json().catch(() => null) as Record<string, unknown> | null;
  if (!response.ok) {
    if (response.status === 401) {
      throw new DashboardApiError('انتهت جلسة الدخول أو لم تُسجّل بعد. افتح اللوحة الحالية عبر رابط الدخول ثم أعد المحاولة.', 401);
    }
    if (response.status >= 500) {
      throw new DashboardApiError('حدث خطأ داخل خادم المعالجة. راجع سجل المهمة أو تقرير التشخيص من اللوحة الحالية.', response.status);
    }
    const detail = typeof body?.detail === 'string' ? body.detail.slice(0, 360) : 'تعذّر تنفيذ الطلب.';
    throw new DashboardApiError(detail, response.status);
  }
  return body as T;
}

function safeMedia(value: unknown, id: string): string | undefined {
  if (typeof value !== 'string') return undefined;
  const parts = value.split('/');
  if (parts.length !== 4 || parts[0] !== '' || parts[1] !== 'media' || parts[2] !== id) return undefined;
  if (!/^[A-Za-z0-9_.-]+\.mp4$/i.test(parts[3]) || parts[3].includes('..')) return undefined;
  return value;
}

function safeThumb(value: unknown, id: string): string | undefined {
  return value === `/api/jobs/${id}/thumb` ? value : undefined;
}

function safeJob(value: unknown): DashboardJob | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  const id = typeof source.id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(source.id) ? source.id : '';
  const statuses = ['queued', 'running', 'cancelling', 'done', 'failed'] as const;
  const status = statuses.includes(source.status as typeof statuses[number]) ? source.status as DashboardJob['status'] : null;
  if (!id || !status) return null;
  const number = (key: string) => typeof source[key] === 'number' && Number.isFinite(source[key]) ? source[key] as number : undefined;
  const text = (key: string, limit: number) => typeof source[key] === 'string' ? (source[key] as string).slice(0, limit) : undefined;
  const report = source.quality_report && typeof source.quality_report === 'object' && !Array.isArray(source.quality_report)
    ? source.quality_report as Record<string, unknown>
    : null;
  return {
    id,
    status,
    stage: text('stage', 180),
    progress: number('progress'),
    duration: number('duration'),
    created: number('created'),
    elapsed: number('elapsed'),
    estimate: number('estimate'),
    title: text('title', 200),
    label: text('label', 200),
    media: safeMedia(source.media, id),
    thumb: safeThumb(source.thumb, id),
    quality_report: report ? {
      ok: report.ok === true,
      issues: Array.isArray(report.issues) ? report.issues.filter((item): item is string => typeof item === 'string').slice(0, 12).map(item => item.slice(0, 180)) : [],
    } : undefined,
    publish_in_progress: source.publish_in_progress === true,
  };
}

function uploadError(xhr: XMLHttpRequest): DashboardApiError {
  if (xhr.status === 401) {
    return new DashboardApiError('انتهت جلسة الدخول أو لم تُسجّل بعد. افتح اللوحة الحالية عبر رابط الدخول ثم أعد المحاولة.', 401);
  }
  if (xhr.status >= 500) {
    return new DashboardApiError('تعذّر رفع الفيديو بسبب خطأ في خادم المعالجة.', xhr.status);
  }
  let detail = 'فشل رفع الفيديو.';
  try {
    const body = JSON.parse(xhr.responseText) as { detail?: unknown };
    if (typeof body.detail === 'string') detail = body.detail.slice(0, 360);
  } catch {
    if (xhr.status === 0) detail = 'انقطع الاتصال أثناء رفع الفيديو.';
  }
  return new DashboardApiError(detail, xhr.status);
}

export const dashboardApi = {
  config: () => requestJson<DashboardConfig>('/api/config'),
  jobs: async () => {
    const data = await requestJson<unknown>('/api/jobs');
    if (!Array.isArray(data)) throw new DashboardApiError('استجابة قائمة المهام غير صالحة.', 502);
    return data.map(safeJob).filter((job): job is DashboardJob => job !== null);
  },
  queue: () => requestJson<DashboardQueue>('/api/queue'),
  systemInfo: () => requestJson<DashboardSystemInfo>('/api/sysinfo'),
  createJob: (payload: CreateJobRequest) => requestJson<{ id: string }>('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  cancelJob: (id: string) => requestJson<{ ok: boolean; was?: string }>(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  deleteJob: (id: string) => requestJson<{ ok: boolean }>(`/api/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  startScout: (input: string, count = 5) => requestJson<DashboardScoutSession>('/api/scout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input, count }),
  }),
  scout: (id: string) => requestJson<DashboardScoutSession>(`/api/scout/${encodeURIComponent(id)}`),
  upload: (file: File, onProgress: (percent: number) => void) => new Promise<{ path: string; name: string }>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    xhr.withCredentials = true;
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) onProgress(Math.max(0, Math.min(100, Math.round(event.loaded / event.total * 100))));
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(uploadError(xhr));
        return;
      }
      try {
        const result = JSON.parse(xhr.responseText) as { path?: unknown; name?: unknown };
        if (typeof result.path !== 'string' || typeof result.name !== 'string') {
          reject(new DashboardApiError('استجاب الخادم ببيانات رفع غير مكتملة.', xhr.status));
          return;
        }
        resolve({ path: result.path, name: result.name });
      } catch {
        reject(new DashboardApiError('تعذّرت قراءة استجابة رفع الفيديو.', xhr.status));
      }
    };
    xhr.onerror = () => reject(uploadError(xhr));
    xhr.onabort = () => reject(new DashboardApiError('أُلغي رفع الفيديو.', xhr.status));
    const form = new FormData();
    form.append('file', file, file.name);
    xhr.send(form);
  }),
};
