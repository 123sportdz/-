import { describe, expect, test } from 'bun:test';
import type { DashboardJob, DashboardScoutSession } from '../src/services/dashboardApi';
import { getWorkflowGuideState } from '../src/services/workflowGuide';

const scout = (status: DashboardScoutSession['status']): DashboardScoutSession => ({
  id: 'scout-1',
  status,
  stage: status,
  progress: 0,
  duration: 0,
  candidates: [],
});

const job = (overrides: Partial<DashboardJob>): DashboardJob => ({
  id: 'job-1',
  status: 'done',
  created: 1,
  ...overrides,
});

describe('production workflow guide state', () => {
  test('does not infer rights, scouting, rendering, or quality completion from an empty workspace', () => {
    expect(getWorkflowGuideState(false, null, [])).toEqual({
      source: 'waiting',
      scout: 'optional',
      render: 'waiting',
      quality: 'waiting',
    });
  });

  test('shows an active scout and render as in progress', () => {
    const state = getWorkflowGuideState(true, scout('analyzing'), [job({ status: 'running' })]);
    expect(state).toEqual({
      source: 'ready',
      scout: 'running',
      render: 'running',
      quality: 'waiting',
    });
  });

  test('marks quality passed only when the latest completed job explicitly passes', () => {
    const state = getWorkflowGuideState(true, scout('ready'), [
      job({ id: 'older', created: 1, quality_report: { ok: true } }),
      job({ id: 'newer', created: 2, quality_report: { ok: false, issues: ['duration'] } }),
    ]);
    expect(state.quality).toBe('attention');
    expect(state.scout).toBe('ready');
  });

  test('keeps a missing or indeterminate quality report in manual review', () => {
    expect(getWorkflowGuideState(false, null, [job({ quality_report: undefined })]).quality).toBe('manual');
    expect(getWorkflowGuideState(false, null, [job({ quality_report: { issues: [] } })]).quality).toBe('manual');
  });

  test('does not treat a failed render as completed', () => {
    const state = getWorkflowGuideState(false, scout('failed'), [job({ status: 'failed' })]);
    expect(state.render).toBe('failed');
    expect(state.quality).toBe('waiting');
    expect(state.scout).toBe('failed');
  });
});
