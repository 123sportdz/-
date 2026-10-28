import { beforeEach, expect, test } from 'bun:test';
import { geminiService } from '../src/services/geminiService';
import { storage } from '../src/services/storage';
import { installBrowserStorage } from './browserStorage';

beforeEach(installBrowserStorage);

const request = {
  mode: 'script',
  topic: 'هدف في الوقت القاتل',
  source: 'لقطة كرة قدم تجريبية',
  platform: 'instagram',
  language: 'ar',
  length: 'short' as const,
  tone: 'حماسي',
  audience: 'مشجعو كرة القدم',
  instructions: '',
};

test('does not call Gemini without per-request text consent', async () => {
  storage.saveSettings({ ...storage.getSettings(), gemini_api_key: 'test-key' });

  const result = await geminiService.generateContent({ ...request, allowExternalText: false });

  expect(result.source).toBe('local');
  expect(result.text.length).toBeGreaterThan(0);
});

test('uses the local generator when no API key is present', async () => {
  const result = await geminiService.generateContent({ ...request, allowExternalText: true });

  expect(result.source).toBe('local');
  expect(result.text.length).toBeGreaterThan(0);
});

test('keeps short voice scripts within the configured word cap', async () => {
  const result = await geminiService.generateContent({ ...request, allowExternalText: false });

  expect(result.text.trim().split(/\s+/).length).toBeLessThanOrEqual(22);
});
