import type { DashboardJob, DashboardScoutSession } from './dashboardApi';

export type WorkflowGuideState = {
  source: 'ready' | 'waiting';
  scout: 'ready' | 'running' | 'failed' | 'optional';
  render: 'running' | 'done' | 'failed' | 'waiting';
  quality: 'passed' | 'attention' | 'manual' | 'waiting';
};

export function getWorkflowGuideState(
  sourceReady: boolean,
  scoutSession: DashboardScoutSession | null,
  jobs: DashboardJob[],
): WorkflowGuideState {
  const latestCompleted = jobs
    .filter(job => job.status === 'done')
    .sort((left, right) => (right.created || 0) - (left.created || 0))[0];
  const latestJob = [...jobs].sort((left, right) => (right.created || 0) - (left.created || 0))[0];
  const active = jobs.some(job => ['queued', 'running', 'cancelling'].includes(job.status));
  const scoutRunning = Boolean(scoutSession && ['queued', 'downloading', 'analyzing'].includes(scoutSession.status));

  return {
    source: sourceReady ? 'ready' : 'waiting',
    scout: scoutSession?.status === 'ready' ? 'ready'
      : scoutRunning ? 'running'
        : scoutSession?.status === 'failed' ? 'failed' : 'optional',
    render: active ? 'running'
      : latestJob?.status === 'failed' ? 'failed'
        : latestCompleted ? 'done' : 'waiting',
    quality: !latestCompleted ? 'waiting'
      : latestCompleted.quality_report?.ok === true ? 'passed'
        : latestCompleted.quality_report?.ok === false ? 'attention' : 'manual',
  };
}
