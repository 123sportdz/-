import React, { useState } from 'react';
import {
  PenTool,
  Sparkles,
  Copy,
  Download,
  Plus,
  Save,
  Trash2,
  Film,
  CheckCircle,
  FileText,
  Clock,
} from 'lucide-react';
import { CreativeDraft, Job } from '../../types';
import { CONTENT_MODES, geminiService, SCRIPT_WORD_LIMITS } from '../../services/geminiService';

interface CreativeStudioTabProps {
  completedJobs: Job[];
  drafts: CreativeDraft[];
  onSaveDraft: (draft: CreativeDraft) => void;
  onDeleteDraft: (id: string) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

export const CreativeStudioTab: React.FC<CreativeStudioTabProps> = ({
  completedJobs,
  drafts,
  onSaveDraft,
  onDeleteDraft,
  onToast,
}) => {
  const [selectedJobId, setSelectedJobId] = useState<string>('');
  const [currentMode, setCurrentMode] = useState<string>('script');
  const [topic, setTopic] = useState<string>('');
  const [sourceText, setSourceText] = useState<string>('');
  const [platform, setPlatform] = useState<string>('instagram');
  const [language, setLanguage] = useState<string>('ar');
  const [length, setLength] = useState<'short' | 'medium' | 'long'>('short');
  const [tone, setTone] = useState<string>('حماسي وطبيعي');
  const [audience, setAudience] = useState<string>('مشجعو كرة القدم');
  const [instructions, setInstructions] = useState<string>('');

  // Generation & Editor State
  const [generating, setGenerating] = useState<boolean>(false);
  const [activeDraftId, setActiveDraftId] = useState<string>('');
  const [draftTitle, setDraftTitle] = useState<string>('');
  const [editorText, setEditorText] = useState<string>('');

  const selectedJob = completedJobs.find(j => j.id === selectedJobId);

  // Calculate live word count
  const wordCount = editorText.trim() ? editorText.trim().split(/\s+/).length : 0;
  const scriptCap = currentMode === 'script' ? SCRIPT_WORD_LIMITS[length] || 22 : null;

  const handleGenerate = async () => {
    setGenerating(true);
    onToast('جارٍ كتابة محتوى كروي مخصص للريل...', 'ok');

    try {
      const res = await geminiService.generateContent({
        mode: currentMode,
        topic,
        source: sourceText,
        platform,
        language,
        length,
        tone,
        audience,
        instructions,
        jobTitle: selectedJob?.title,
      });

      setEditorText(res.text);
      setDraftTitle(res.title);
      setActiveDraftId('draft-' + Date.now());
      onToast('تم توليد محتوى الريل بنجاح! ⚽✨', 'ok');
    } catch {
      onToast('تعذر التوليد، يرجى المحاولة ثانية', 'err');
    } finally {
      setGenerating(false);
    }
  };

  const handleSaveCurrentDraft = () => {
    if (!editorText.trim()) {
      onToast('لا يوجد نص لحفظه', 'err');
      return;
    }

    const draft: CreativeDraft = {
      id: activeDraftId || 'draft-' + Date.now(),
      title: draftTitle.trim() || `مسودة ريل ${new Date().toLocaleTimeString('ar-EG')}`,
      mode: currentMode,
      job_id: selectedJobId,
      job_title: selectedJob?.title,
      topic,
      source: sourceText,
      platform,
      language,
      length,
      tone,
      audience,
      instructions,
      text: editorText,
      created_at: 'الآن',
    };

    onSaveDraft(draft);
    setActiveDraftId(draft.id);
    onToast('تم حفظ المسودة محلياً بنجاح (المسودات لا تُنشر تلقائياً)', 'ok');
  };

  const handleLoadDraft = (d: CreativeDraft) => {
    setActiveDraftId(d.id);
    setDraftTitle(d.title);
    setEditorText(d.text);
    setCurrentMode(d.mode || 'script');
    setTopic(d.topic || '');
    setSourceText(d.source || '');
    setLanguage(d.language || 'ar');
    setPlatform(d.platform || 'instagram');
    onToast(`تم تحميل المسودة: ${d.title}`, 'ok');
  };

  const handleCopy = () => {
    if (!editorText) return;
    navigator.clipboard.writeText(editorText);
    onToast('تم نسخ النص إلى الحافظة بنجاح ⧉', 'ok');
  };

  const handleDownloadMarkdown = () => {
    if (!editorText) return;
    const blob = new Blob([`# ${draftTitle}\n\n${editorText}`], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(draftTitle || 'reel_copy').replace(/\s+/g, '_')}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    onToast('تم تنزيل ملف Markdown بنجاح', 'ok');
  };

  const handleNewText = () => {
    setActiveDraftId('');
    setDraftTitle('');
    setEditorText('');
    setTopic('');
    setSourceText('');
  };

  return (
    <div className="space-y-6">
      {/* Hero Strip */}
      <div className="bg-gradient-to-r from-[#14252a]/95 to-[#111a22]/95 border border-[#47cbb3]/25 rounded-2xl p-5 shadow-xl">
        <div className="text-[11px] font-extrabold tracking-widest text-[#44d2c2] uppercase mb-1">
          ELHADATH · REEL CONTENT DESK
        </div>
        <h1 className="text-xl sm:text-2xl font-black text-white mb-1.5">
          استوديو محتوى الريلز — نصّ يخدم اللقطة
        </h1>
        <p className="text-xs text-[#a9bbc9] max-w-2xl leading-relaxed">
          أنشئ تعليقاً صوتياً أو شعرياً، عناوين، افتتاحية جذابة، كابشن، أو ملخصاً — مرتبطاً بريل مكتمل من مصنعك أو بتفاصيل تدخلها بنفسك.
        </p>
        <div className="text-[10px] text-[#d5c39f] mt-2">
          🔒 الخصوصية: ثلاث لقطات ثابتة فقط تُحلّل عند ربط ريل؛ لا يُرسل الفيديو كاملاً ولا يحدث نشر تلقائي إطلاقاً.
        </div>
      </div>

      {/* Main Workspace */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_1.3fr] gap-6 items-start">
        {/* Controls Column */}
        <div className="bg-[#111a23] border border-[#263747] rounded-2xl p-5 shadow-xl text-xs">
          <div className="flex items-center justify-between pb-3 border-b border-[#263747] mb-3">
            <div>
              <h2 className="text-sm font-bold text-white">السياق والمخرج الكروي</h2>
              <p className="text-[11px] text-[#8ea0b5]">اختر ريلًا مكتملاً أو أدخل تفاصيل اللقطة.</p>
            </div>
            <span className="text-[10px] px-2.5 py-0.5 rounded-full border border-[#3ecabb]/40 text-[#44d2c2] bg-[#1a3737]/40 font-bold">
              01 · جهّز
            </span>
          </div>

          {/* Reel Link Dropdown */}
          <div className="mb-3">
            <label className="block text-[#bdcbd6] font-bold mb-1">
              ريل من مهامك المكتملة <span className="text-[#718596] font-normal">(اختياري)</span>
            </label>
            <select
              value={selectedJobId}
              onChange={e => setSelectedJobId(e.target.value)}
              className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
            >
              <option value="">بدون ريل — سأدخل تفاصيل اللقطة يدوياً</option>
              {completedJobs.map(j => (
                <option key={j.id} value={j.id}>
                  {j.title} ({j.duration} ثانية)
                </option>
              ))}
            </select>
          </div>

          {/* 13 Modes Grid */}
          <label className="block text-[#bdcbd6] font-bold mb-2">نوع محتوى الريل (13 أداة رياضية)</label>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 mb-4">
            {Object.entries(CONTENT_MODES).map(([key, config]) => {
              const isActive = currentMode === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setCurrentMode(key)}
                  className={`flex items-center gap-1.5 p-2 rounded-xl text-[11px] font-bold border transition text-right ${
                    isActive
                      ? 'border-[#48cbbc] bg-gradient-to-r from-[#1b393a] to-[#12232b] text-white shadow-inner'
                      : 'border-[#293947] bg-[#0e161e] text-[#8ea0b5] hover:text-white hover:border-[#477477]'
                  }`}
                >
                  <span className="text-[#44d2c2]">{config.icon}</span>
                  <span className="truncate">{config.label}</span>
                </button>
              );
            })}
          </div>

          {/* Topic & Source details */}
          <div className="space-y-3">
            <div>
              <label className="block text-[#bdcbd6] font-bold mb-1">
                الحدث أو زاوية التعليق <span className="text-[#718596] font-normal">(مثلاً: هدف الدقيقة 92)</span>
              </label>
              <input
                type="text"
                value={topic}
                onChange={e => setTopic(e.target.value)}
                placeholder="هدف الفوز القاتل بتسديدة لولبية"
                maxLength={2000}
                className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
              />
            </div>

            <div>
              <label className="block text-[#bdcbd6] font-bold mb-1">
                تفاصيل مؤكدة عن اللقطة <span className="text-[#718596] font-normal">(الفريق، اللاعب، النتيجة...)</span>
              </label>
              <textarea
                rows={2}
                value={sourceText}
                onChange={e => setSourceText(e.target.value)}
                placeholder="رياض محرز يستلم الكرة على مشارف المنطقة، يراوغ إلى الداخل ويسدد في أقصى الزاوية التسعين..."
                maxLength={8000}
                className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
              />
            </div>

            {/* Platform & Language */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[#bdcbd6] font-bold mb-1">المنصة</label>
                <select
                  value={platform}
                  onChange={e => setPlatform(e.target.value)}
                  className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
                >
                  <option value="instagram">Instagram Reels</option>
                  <option value="tiktok">TikTok</option>
                  <option value="youtube_shorts">YouTube Shorts</option>
                  <option value="general">عام</option>
                </select>
              </div>

              <div>
                <label className="block text-[#bdcbd6] font-bold mb-1">لغة الإخراج</label>
                <select
                  value={language}
                  onChange={e => setLanguage(e.target.value)}
                  className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
                >
                  <option value="ar">العربية الفصحى الرياضية</option>
                  <option value="dz">الدارجة الجزائرية العفوية</option>
                  <option value="fr">Français</option>
                  <option value="en">English</option>
                </select>
              </div>
            </div>

            {/* Length & Tone */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[#bdcbd6] font-bold mb-1">
                  طول النص {scriptCap ? `(حد أقصى ${scriptCap} كلمة)` : ''}
                </label>
                <select
                  value={length}
                  onChange={e => setLength(e.target.value as any)}
                  className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
                >
                  <option value="short">قصير — مناسب للريل (22 كلمة)</option>
                  <option value="medium">متوسط (40 كلمة)</option>
                  <option value="long">مفصّل (65 كلمة)</option>
                </select>
              </div>

              <div>
                <label className="block text-[#bdcbd6] font-bold mb-1">النبرة</label>
                <select
                  value={tone}
                  onChange={e => setTone(e.target.value)}
                  className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
                >
                  <option>حماسي وطبيعي</option>
                  <option>شاعري دون مبالغة</option>
                  <option>تحليلي ومهني</option>
                  <option>جزائري عفوي</option>
                  <option>هادئ وواضح</option>
                </select>
              </div>
            </div>

            {/* Audience & Instructions */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[#bdcbd6] font-bold mb-1">الجمهور</label>
                <input
                  type="text"
                  value={audience}
                  onChange={e => setAudience(e.target.value)}
                  className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
                />
              </div>

              <div>
                <label className="block text-[#bdcbd6] font-bold mb-1">توجيه إضافي</label>
                <input
                  type="text"
                  value={instructions}
                  onChange={e => setInstructions(e.target.value)}
                  placeholder="مثلاً: بلا وسوم أو بلغة سريعة"
                  className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-2.5 text-white"
                />
              </div>
            </div>
          </div>

          {/* Generate Button */}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="w-full mt-5 py-3 rounded-xl text-xs font-black text-[#06201d] bg-gradient-to-r from-[#55d8c5] to-[#21a99e] hover:brightness-110 disabled:opacity-50 transition flex items-center justify-center gap-2 shadow-lg shadow-[#55d8c5]/20"
          >
            <Sparkles className={`w-4 h-4 ${generating ? 'animate-spin' : ''}`} />
            <span>{generating ? 'جارٍ التوليد...' : '✦ أنشئ محتوى للريل'}</span>
          </button>
        </div>

        {/* Editor and Drafts Column */}
        <div className="space-y-6">
          {/* Editor Card */}
          <div className="bg-[#111a23] border border-[#263747] rounded-2xl p-5 shadow-xl text-xs">
            <div className="flex items-center justify-between pb-3 border-b border-[#263747] mb-3">
              <div>
                <h2 className="text-sm font-bold text-white">مساحة المراجعة والتحرير</h2>
                <p className="text-[11px] text-[#8ea0b5]">راجع النص الرياضي وعدّله بحرية كاملة.</p>
              </div>
              <span className="text-[10px] px-2.5 py-0.5 rounded-full border border-[#3ecabb]/40 text-[#44d2c2] bg-[#1a3737]/40 font-bold">
                02 · حرّر
              </span>
            </div>

            {/* Title & Word Counter */}
            <div className="flex items-center gap-2 mb-2">
              <input
                type="text"
                value={draftTitle}
                onChange={e => setDraftTitle(e.target.value)}
                placeholder="عنوان المسودة..."
                className="flex-1 bg-[#0b131a] border border-[#293a48] rounded-xl p-2 text-white font-bold"
              />
              <div className="text-[11px] text-[#8ea0b5] font-mono px-2 py-1 rounded bg-[#0b131a] border border-[#293a48] shrink-0">
                {wordCount} كلمة {scriptCap ? `/ الحد ${scriptCap}` : ''}
              </div>
            </div>

            {/* Textarea */}
            <textarea
              rows={9}
              value={editorText}
              onChange={e => setEditorText(e.target.value)}
              placeholder="اكتب أو حرّر نص الريل هنا... أو اضغط «أنشئ محتوى للريل» للتوليد الآلي."
              className="w-full bg-[#0b131a] border border-[#293a48] rounded-xl p-3 text-white text-sm leading-relaxed"
            />

            {/* Actions */}
            <div className="flex items-center gap-2 flex-wrap mt-3">
              <button
                type="button"
                onClick={handleSaveCurrentDraft}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-[#8ce6d8] bg-[#173633] border border-[#287469] hover:bg-[#1e4844] transition"
              >
                <Save className="w-3.5 h-3.5" />
                <span>▣ حفظ محلي</span>
              </button>

              <button
                type="button"
                onClick={handleCopy}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[#15212b] hover:bg-[#1e2f3d] text-[#d7e2eb] border border-[#304351] transition"
              >
                <Copy className="w-3.5 h-3.5" />
                <span>⧉ نسخ</span>
              </button>

              <button
                type="button"
                onClick={handleDownloadMarkdown}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[#15212b] hover:bg-[#1e2f3d] text-[#d7e2eb] border border-[#304351] transition"
              >
                <Download className="w-3.5 h-3.5" />
                <span>↓ Markdown</span>
              </button>

              <button
                type="button"
                onClick={handleNewText}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[#15212b] hover:bg-[#1e2f3d] text-[#d7e2eb] border border-[#304351] transition mr-auto"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>＋ نص جديد</span>
              </button>
            </div>
          </div>

          {/* Local Drafts Card */}
          <div className="bg-[#111a23] border border-[#263747] rounded-2xl p-5 shadow-xl text-xs">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-bold text-white flex items-center gap-2">
                <FileText className="w-4 h-4 text-[#44d2c2]" />
                <span>مسودات محتوى الريلز المحفوظة</span>
              </h2>
              <span className="text-[10px] text-[#8ea0b5] px-2 py-0.5 rounded-full border border-[#263747] bg-[#0e171e]">
                {drafts.length} / 100
              </span>
            </div>

            {drafts.length === 0 ? (
              <div className="text-center py-8 text-[#8ea0b5] border border-dashed border-[#293a47] rounded-xl">
                لا توجد مسودات محفوظة حتى الآن. احفظ نصوصك للعودة إليها لاحقاً.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {drafts.map(d => (
                  <div
                    key={d.id}
                    onClick={() => handleLoadDraft(d)}
                    className="p-2.5 rounded-xl border border-[#263846] bg-[#0e171e] hover:border-[#44d2c2]/50 cursor-pointer transition flex flex-col justify-between"
                  >
                    <div>
                      <h3 className="font-bold text-white truncate mb-1">{d.title}</h3>
                      <p className="text-[11px] text-[#8294a2] line-clamp-2 leading-relaxed">{d.text}</p>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-[#6e8290] mt-2 pt-1.5 border-t border-[#1a2833]">
                      <span>{d.created_at}</span>
                      <button
                        onClick={e => {
                          e.stopPropagation();
                          onDeleteDraft(d.id);
                        }}
                        className="text-[#8ea0b5] hover:text-[#ff9aa2] p-0.5"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
