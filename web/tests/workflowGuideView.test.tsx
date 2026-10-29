import { describe, expect, mock, test } from 'bun:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { DashboardJob, DashboardScoutSession } from '../src/services/dashboardApi';
import { WorkflowGuide } from '../src/components/WorkflowGuide';

const scoutSession: DashboardScoutSession | null = null;
const jobs: DashboardJob[] = [];

describe('production workflow guide view', () => {
  test('shows the complete seven-step path and preserves manual publishing boundaries', () => {
    const onNavigate = mock(() => {});
    const html = renderToStaticMarkup(createElement(WorkflowGuide, {
      sourceReady: false,
      scoutSession,
      jobs,
      onNavigate,
    }));

    for (const step of [
      'اختر المصدر',
      'راجع الحقوق',
      'اكشف اللقطات',
      'أنشئ الرندر',
      'افحص الجودة',
      'ارفعه كخاص',
      'راجع في Studio',
    ]) {
      expect(html).toContain(step);
    }
    expect(html).toContain('لا تُسجّل هذه الصفحة الحقوق ولا ترفع الفيديو خارج خادم المشروع');
    expect(html).toContain('التقرير الغائب أو غير الحاسم لا يُعد نجاحاً');
    expect(html).toContain('href="/"');
    expect(html).toContain('href="https://studio.youtube.com/"');
    expect(html).toContain('target="_blank"');
    expect(onNavigate).not.toHaveBeenCalled();
  });

  test('does not mark rights, private upload, or Studio review complete by default', () => {
    const html = renderToStaticMarkup(createElement(WorkflowGuide, {
      sourceReady: false,
      scoutSession,
      jobs,
      onNavigate: () => {},
    }));

    expect(html.match(/مراجعة يدوية/g)).toHaveLength(3);
    expect(html).not.toContain('اجتاز التقرير');
  });
});
