import { ArrowLeft, ExternalLink, ListChecks } from 'lucide-react';
import type { DashboardJob, DashboardScoutSession } from '../services/dashboardApi';
import { getWorkflowGuideState } from '../services/workflowGuide';

type Section = 'create' | 'jobs';
type StepStatus = 'ready' | 'waiting' | 'running' | 'failed' | 'optional' | 'done' | 'passed' | 'attention' | 'manual';
type Action =
  | { label: string; href: string; external?: boolean }
  | { label: string; section: Section; targetId: string };

type WorkflowGuideProps = {
  sourceReady: boolean;
  scoutSession: DashboardScoutSession | null;
  jobs: DashboardJob[];
  onNavigate: (section: Section, targetId: string) => void;
};

const statusLabels: Record<StepStatus, string> = {
  ready: 'المصدر محدد',
  waiting: 'بانتظار خطوة',
  running: 'جارٍ التنفيذ',
  failed: 'يحتاج إعادة محاولة',
  optional: 'اختياري',
  done: 'اكتمل الرندر',
  passed: 'اجتاز التقرير',
  attention: 'راجع الملاحظات',
  manual: 'مراجعة يدوية',
};

const statusClasses: Record<StepStatus, string> = {
  ready: 'border-[#1c6d4c] bg-[#10251d] text-[#b5f3d0]',
  waiting: 'border-[#2c3a4d] bg-[#0f151c] text-[#8ea0b5]',
  running: 'border-[#215a69] bg-[#10232b] text-[#a9edf1]',
  failed: 'border-[#7a1f2b] bg-[#2a1014] text-[#ffd1d5]',
  optional: 'border-[#2c3a4d] bg-[#0f151c] text-[#aab8c8]',
  done: 'border-[#1c6d4c] bg-[#10251d] text-[#b5f3d0]',
  passed: 'border-[#1c6d4c] bg-[#10251d] text-[#b5f3d0]',
  attention: 'border-[#6b5720] bg-[#282114] text-[#f3d489]',
  manual: 'border-[#6b5720] bg-[#282114] text-[#f3d489]',
};

export function WorkflowGuide({ sourceReady, scoutSession, jobs, onNavigate }: WorkflowGuideProps) {
  const state = getWorkflowGuideState(sourceReady, scoutSession, jobs);
  const steps: { title: string; description: string; status: StepStatus; action: Action }[] = [
    {
      title: 'اختر المصدر',
      description: 'حدد ملفاً محلياً أو رابطاً عاماً. الرفع هنا إلى خادم المشروع فقط.',
      status: state.source,
      action: { label: 'اذهب إلى المصدر', section: 'create', targetId: 'workflow-source' },
    },
    {
      title: 'راجع الحقوق',
      description: 'راجع حقوق الصورة والصوت في المهمة قبل النشر. اكتمال الرندر أو تسجيل إقرار لا يثبت الملكية أو الترخيص.',
      status: 'manual',
      action: { label: 'افتح اللوحة الحالية', href: '/' },
    },
    {
      title: 'اكشف اللقطات',
      description: 'الكشّاف اختياري: راجع الإطارات واضبط القص حول الذروة، أو انتقل مباشرة إلى الرندر.',
      status: state.scout,
      action: { label: 'اذهب إلى الكشّاف', section: 'create', targetId: 'workflow-scout' },
    },
    {
      title: 'أنشئ الرندر',
      description: 'ينشئ زر الرندر مهمة فعلية على الخادم؛ لا يرفع الفيديو إلى YouTube أو Telegram.',
      status: state.render,
      action: { label: 'اذهب إلى الرندر', section: 'create', targetId: 'workflow-render' },
    },
    {
      title: 'افحص الجودة',
      description: 'راجع تقرير آخر مهمة مكتملة ومعاينتها. التقرير الغائب أو غير الحاسم لا يُعد نجاحاً.',
      status: state.quality,
      action: { label: 'افتح المهام', section: 'jobs', targetId: 'workflow-jobs' },
    },
    {
      title: 'ارفعه كخاص',
      description: 'الرفع غير متاح هنا. من اللوحة الحالية، اجتز بوابة الحقوق واختر «خاص» صراحةً بعد التحقق من القناة.',
      status: 'manual',
      action: { label: 'افتح اللوحة الحالية', href: '/' },
    },
    {
      title: 'راجع في Studio',
      description: 'بعد الرفع الخاص، افحص حالة المعالجة والقيود في YouTube Studio بنفسك.',
      status: 'manual',
      action: { label: 'افتح YouTube Studio', href: 'https://studio.youtube.com/', external: true },
    },
  ];

  return (
    <section aria-labelledby="workflow-guide-title" className="mt-5 rounded-2xl border border-[#2c3a4d] bg-[#101720] p-4 sm:p-5">
      <div className="mb-4 flex items-start gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#182231] text-[#36d1dc]"><ListChecks className="size-5" /></div>
        <div>
          <h2 id="workflow-guide-title" className="text-base font-extrabold">دليل سير العمل</h2>
          <p className="mt-1 text-xs leading-6 text-[#8ea0b5]">خطوات إرشادية وليست بوابة نشر: لا تُسجّل هذه الصفحة الحقوق ولا ترفع الفيديو خارج خادم المشروع.</p>
        </div>
      </div>
      <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, index) => {
          const action = step.action;
          return (
            <li key={step.title} className="flex min-h-48 flex-col rounded-xl border border-[#222e3d] bg-[#131a23] p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="grid size-7 place-items-center rounded-full bg-[#222e3d] text-xs font-black text-[#c9d6e5]">{index + 1}</span>
                <span className={`rounded-full border px-2 py-1 text-[10px] font-bold ${statusClasses[step.status]}`}>{statusLabels[step.status]}</span>
              </div>
              <h3 className="mt-3 text-sm font-bold">{step.title}</h3>
              <p className="mt-1 flex-1 text-[11px] leading-5 text-[#8ea0b5]">{step.description}</p>
              {'section' in action ? (
                <button onClick={() => onNavigate(action.section, action.targetId)} className="mt-3 flex items-center gap-1 self-start rounded-lg border border-[#2c3a4d] px-2.5 py-2 text-[11px] font-bold text-[#c9d6e5] hover:bg-[#182231]">
                  {action.label}<ArrowLeft className="size-3.5" />
                </button>
              ) : (
                <a href={action.href} target={action.external ? '_blank' : undefined} rel={action.external ? 'noreferrer' : undefined} className="mt-3 flex items-center gap-1 self-start rounded-lg border border-[#2c3a4d] px-2.5 py-2 text-[11px] font-bold text-[#c9d6e5] hover:bg-[#182231]">
                  {action.label}{action.external ? <ExternalLink className="size-3.5" /> : <ArrowLeft className="size-3.5" />}
                </a>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
