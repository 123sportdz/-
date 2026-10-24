import React, { useState } from 'react';
import { X, ShieldCheck, ShieldAlert, AlertTriangle, CheckCircle2, Lock, Tv, Send } from 'lucide-react';
import { Job } from '../../types';

interface RightsGateModalProps {
  job: Job;
  mode: 'review' | 'youtube';
  onClose: () => void;
  onSaveRights: (jobId: string, rightsData: {
    visualRights: boolean;
    audioRights: boolean;
    sourceRef: string;
    evidence: string;
    scope: 'private' | 'unlisted' | 'public';
    containsSyntheticMedia: boolean;
  }) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

export const RightsGateModal: React.FC<RightsGateModalProps> = ({
  job,
  mode,
  onClose,
  onSaveRights,
  onToast,
}) => {
  const [visualRights, setVisualRights] = useState<boolean>(job.rights_status === 'recorded');
  const [audioRights, setAudioRights] = useState<boolean>(job.rights_status === 'recorded');
  const [sourceRef, setSourceRef] = useState<string>(job.src_url || 'https://t.me/OffsideOffside1/2984');
  const [evidence, setEvidence] = useState<string>('بث رياضي مصرح / مقطع قصير مع الحفاظ على علامات المصدر');
  const [scope, setScope] = useState<'private' | 'unlisted' | 'public'>('private');
  const [containsSyntheticMedia, setContainsSyntheticMedia] = useState<boolean>(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Verification according to AGENTS.md rights gate rule
    if ((scope === 'public' || scope === 'unlisted') && (!visualRights || !audioRights)) {
      onToast('تنبيه أمني: عند النشر العام أو غير المدرج يجب تأكيد حقوق الصورة والصوت بالكامل؛ غير ذلك يُسمح بالرفع الخاص (Private) فقط للمراجعة.', 'err');
      return;
    }

    onSaveRights(job.id, {
      visualRights,
      audioRights,
      sourceRef,
      evidence,
      scope,
      containsSyntheticMedia,
    });

    onToast(
      mode === 'youtube'
        ? `تم التحقق من بوابة الحقوق والبدء برفع الريل على YouTube Shorts (${scope}) بنجاح`
        : 'تم توثيق بيانات الحقوق وتسجيلها في outputs/audit/events.jsonl',
      'ok'
    );
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="relative bg-[#131a23] border border-[#2c3a4d] rounded-2xl max-w-xl w-full p-5 sm:p-6 shadow-2xl max-h-[92vh] overflow-y-auto text-xs">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-[#222e3d] mb-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-[#36d1dc]" />
            <div>
              <h2 className="text-sm sm:text-base font-bold text-white">
                {mode === 'youtube' ? 'بوابة التحقق من الحقوق ونشر YouTube' : 'نموذج مراجعة حقوق البث والملكية'}
              </h2>
              <span className="text-[11px] text-[#8ea0b5]">{job.title}</span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-[#182231] hover:bg-[#222e3d] text-[#8ea0b5] hover:text-white transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Warning Banner */}
        <div className="p-3 rounded-xl bg-[#282114] border border-[#664c30] text-[#e5c99a] mb-4 leading-relaxed flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-[#f0b429] shrink-0 mt-0.5" />
          <div>
            <b>سياسة النزاهة وحقوق البث الرياضي:</b> علامات المصدر الأصلية لا تُحذف إلا بترخيص. الحقوق المجهولة تُرفع كفيديو خاص (Private) للمراجعة فقط ولا يُسمح بنشرها للعامة دون تأكيد.
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Checkbox Gates */}
          <div className="space-y-2.5 p-3 rounded-xl bg-[#0c1219] border border-[#222e3d]">
            <label className="flex items-start gap-2 text-[#cfdcec] font-semibold cursor-pointer">
              <input
                type="checkbox"
                checked={visualRights}
                onChange={e => setVisualRights(e.target.checked)}
                className="mt-0.5 rounded"
              />
              <span>أؤكد امتلاك حقوق الصورة أو الحصول على إذن/ترخيص لاستخدام هذه اللقطة الكروية.</span>
            </label>

            <label className="flex items-start gap-2 text-[#cfdcec] font-semibold cursor-pointer">
              <input
                type="checkbox"
                checked={audioRights}
                onChange={e => setAudioRights(e.target.checked)}
                className="mt-0.5 rounded"
              />
              <span>أؤكد سلامة الصوت والموسيقى المصاحبة وعدم مخالفتها لسياسات البث الرياضي.</span>
            </label>
          </div>

          {/* Source Reference & Evidence */}
          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">مرجع المصدر (رابط البث أو القناة)</label>
            <input
              type="text"
              required
              value={sourceRef}
              onChange={e => setSourceRef(e.target.value)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>

          <div>
            <label className="block text-[#8ea0b5] font-semibold mb-1">سند الاستخدام / الملاحظة التوثيقية</label>
            <textarea
              rows={2}
              required
              value={evidence}
              onChange={e => setEvidence(e.target.value)}
              placeholder="مثلاً: ملخص مصرح به للنشر مع إبقاء شعار الناقل الأصلي دون مساس..."
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white"
            />
          </div>

          {/* Scope selection */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[#8ea0b5] font-semibold mb-1">نطاق الخصوصية على يوتيوب</label>
              <select
                value={scope}
                onChange={e => setScope(e.target.value as any)}
                className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-white font-medium"
              >
                <option value="private">private (خاص — آمن للفحص)</option>
                <option value="unlisted">unlisted (غير مدرج)</option>
                <option value="public">public (عام للملأ)</option>
              </select>
            </div>

            <div className="flex items-end">
              <label className="flex items-center gap-2 p-2.5 rounded-xl bg-[#0c1219] border border-[#222e3d] text-[#cfdcec] font-medium cursor-pointer w-full">
                <input
                  type="checkbox"
                  checked={containsSyntheticMedia}
                  onChange={e => setContainsSyntheticMedia(e.target.checked)}
                  className="rounded"
                />
                <span>يتضمن وسائط معدلة أو ذكاء اصطناعي (containsSyntheticMedia)</span>
              </label>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-[#222e3d]">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d]"
            >
              إلغاء
            </button>

            <button
              type="submit"
              className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-xs font-black text-white bg-gradient-to-r from-[#25d07a] to-[#1d5c3e] hover:brightness-110 shadow-lg shadow-[#25d07a]/20 transition"
            >
              <CheckCircle2 className="w-4 h-4" />
              <span>{mode === 'youtube' ? 'تأكيد الحقوق ورفع الفيديو' : 'حفظ التوثيق واعتماد الحقوق'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
