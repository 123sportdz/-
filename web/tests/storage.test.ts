import { beforeEach, expect, test } from 'bun:test';
import { storage } from '../src/services/storage';
import type { Job } from '../src/types';
import { installBrowserStorage } from './browserStorage';

beforeEach(installBrowserStorage);

test('keeps credentials out of persistent browser storage', () => {
  storage.saveSettings({
    ...storage.getSettings(),
    gemini_api_key: 'gemini-test-secret',
    telegram_token: 'telegram-test-secret',
  });

  const persisted = JSON.parse(localStorage.getItem('elhadath_settings') || '{}');
  expect(persisted).not.toHaveProperty('gemini_api_key');
  expect(persisted).not.toHaveProperty('telegram_token');
  expect(sessionStorage.getItem('elhadath_session_gemini_api_key')).toBe('gemini-test-secret');
  expect(storage.getSettings().gemini_api_key).toBe('gemini-test-secret');
  expect(storage.getSettings().telegram_token).toBe('');
});

test('migrates legacy secrets out of localStorage', () => {
  localStorage.setItem('elhadath_settings', JSON.stringify({
    brand_name: 'Demo',
    gemini_api_key: 'legacy-gemini-secret',
    telegram_token: 'legacy-telegram-secret',
    tg_phone: '+2135550101',
    tg_user_linked: true,
  }));

  const settings = storage.getSettings();
  const persisted = JSON.parse(localStorage.getItem('elhadath_settings') || '{}');
  expect(settings.gemini_api_key).toBe('legacy-gemini-secret');
  expect(settings.telegram_token).toBe('');
  expect(settings.tg_phone).toBe('');
  expect(settings.tg_user_linked).toBe(false);
  expect(persisted).not.toHaveProperty('gemini_api_key');
  expect(persisted).not.toHaveProperty('telegram_token');
  expect(persisted).not.toHaveProperty('tg_phone');
  expect(persisted).not.toHaveProperty('tg_user_linked');
  expect(sessionStorage.getItem('elhadath_session_gemini_api_key')).toBe('legacy-gemini-secret');
});

test('clears only this prototype and its session key', () => {
  localStorage.setItem('unrelated-app-data', 'keep');
  localStorage.setItem('elhadath_settings', '{}');
  localStorage.setItem('elhadath_voice_studio_pos', 'floating');
  sessionStorage.setItem('elhadath_session_gemini_api_key', 'session-secret');

  storage.clearAppData();

  expect(localStorage.getItem('unrelated-app-data')).toBe('keep');
  expect(localStorage.getItem('elhadath_settings')).toBeNull();
  expect(localStorage.getItem('elhadath_voice_studio_pos')).toBeNull();
  expect(sessionStorage.getItem('elhadath_session_gemini_api_key')).toBeNull();
});

test('does not restore saved automation as running or publishing', () => {
  localStorage.setItem('elhadath_automation', JSON.stringify({
    enabled: true,
    upload: 'both',
    metrics: { jobsProcessed: 4, runsTotal: 9, errors: 2 },
  }));

  const automation = storage.getAutomation();

  expect(automation.enabled).toBe(false);
  expect(automation.upload).toBe('none');
  expect(automation.metrics.jobsProcessed).toBe(0);
  expect(automation.metrics.runsTotal).toBe(0);
  expect(automation.metrics.errors).toBe(0);
});

test('removes fabricated platform successes from stored prototype jobs', () => {
  const job = {
    id: 'old-demo',
    title: 'Old sample',
    status: 'done',
    rights_status: 'recorded',
    youtube_status: 'ready',
    youtube_video_id: 'fake-id',
    telegram_published: true,
    audit_log: [
      { time: '12:00', event: 'rights_verified', detail: 'fake' },
      { time: '12:01', event: 'published_telegram', detail: 'fake' },
    ],
  } as unknown as Job;
  localStorage.setItem('elhadath_jobs', JSON.stringify([job]));

  const [normalized] = storage.getJobs();

  expect(normalized.rights_status).toBe('pending');
  expect(normalized.youtube_status).toBe('none');
  expect(normalized.youtube_video_id).toBeUndefined();
  expect(normalized.telegram_published).toBe(false);
  expect(normalized.audit_log).toEqual([]);
  expect(normalized.stage_text).toContain('لا يوجد رندر فعلي');
});
