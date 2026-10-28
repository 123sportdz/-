import { afterEach, describe, expect, it, mock } from 'bun:test';
import { DashboardApiError, dashboardApi, requestJson } from '../src/services/dashboardApi';

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('dashboard API adapter', () => {
  it('uses the same-origin session and limits job objects to display-safe fields', async () => {
    const fakeFetch = mock(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.credentials).toBe('same-origin');
      return new Response(JSON.stringify([{
        id: 'abc12345',
        status: 'done',
        label: 'goal.mp4',
        input: '/private/incoming/goal.mp4',
        output: '/private/outputs/reel.mp4',
        source_url: 'https://private.example/video',
        log: ['private path'],
        media: '/media/abc12345/reel_abc12345.mp4',
        thumb: '/api/jobs/abc12345/thumb',
        progress: 100,
        created: 1700000000,
        quality_report: { ok: true, issues: [], encoder: 'libx264' },
      }]), { status: 200 });
    });
    globalThis.fetch = fakeFetch as typeof fetch;

    const [job] = await dashboardApi.jobs();
    expect(job).toMatchObject({
      id: 'abc12345',
      status: 'done',
      progress: 100,
      media: '/media/abc12345/reel_abc12345.mp4',
      thumb: '/api/jobs/abc12345/thumb',
      quality_report: { ok: true, issues: [] },
    });
    expect(job).not.toHaveProperty('input');
    expect(job).not.toHaveProperty('output');
    expect(job).not.toHaveProperty('source_url');
    expect(job).not.toHaveProperty('log');
  });

  it('rejects media URLs that could escape the local dashboard', async () => {
    globalThis.fetch = mock(async () => new Response(JSON.stringify([{
      id: 'abc12345', status: 'done', media: 'https://attacker.example/video.mp4',
      thumb: '/api/jobs/../config',
    }]), { status: 200 })) as typeof fetch;

    const [job] = await dashboardApi.jobs();
    expect(job.media).toBeUndefined();
    expect(job.thumb).toBeUndefined();
  });

  it('creates a server render without enabling external publishing', async () => {
    const fakeFetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(input).toBe('/api/jobs');
      expect(init?.method).toBe('POST');
      expect(init?.credentials).toBe('same-origin');
      const payload = JSON.parse(String(init?.body));
      expect(payload.auto_youtube).toBe(false);
      expect(payload.auto_telegram).toBe(false);
      expect(payload.keep_watermarks).toBe(true);
      return new Response(JSON.stringify({ id: 'new-job-123' }), { status: 200 });
    });
    globalThis.fetch = fakeFetch as typeof fetch;

    const result = await dashboardApi.createJob({
      input: '/project/incoming/clip.mp4',
      subject: 'action',
      out_size: '1080x1920',
      quality: 'auto',
      layout: 'single',
      tracker: 'auto',
      framing: 'normal',
      zoom: 'auto',
      max_dur: 58,
      thumb: true,
      keep_watermarks: true,
      auto_youtube: false,
      auto_telegram: false,
      show_channel_name: true,
    });

    expect(result.id).toBe('new-job-123');
  });

  it('provides a clear session message for unauthorized API requests', async () => {
    globalThis.fetch = mock(async () => new Response(JSON.stringify({ detail: 'private server detail' }), { status: 401 })) as typeof fetch;

    await expect(requestJson('/api/jobs')).rejects.toMatchObject({
      status: 401,
      message: expect.stringContaining('جلسة الدخول'),
    });
  });

  it('does not reveal internal server errors in the browser', async () => {
    globalThis.fetch = mock(async () => new Response(JSON.stringify({ detail: 'secret path /private/config.json' }), { status: 500 })) as typeof fetch;

    try {
      await requestJson('/api/jobs');
      throw new Error('Expected the request to fail');
    } catch (error) {
      expect(error).toBeInstanceOf(DashboardApiError);
      expect((error as Error).message).not.toContain('/private/config.json');
      expect((error as Error).message).toContain('تقرير التشخيص');
    }
  });
});
