import React, { useState, useEffect, useRef } from 'react';
import {
  Mic,
  Volume2,
  Sparkles,
  Square,
  Maximize2,
  Minimize2,
  Move,
  Layout,
  Dock,
  Sliders,
  Radio,
  Music,
  Activity,
  Layers,
  ChevronDown,
  ChevronUp,
  X,
  VolumeX,
} from 'lucide-react';
import { VoiceSettings } from '../../types';
import { voiceSynth } from '../../services/voiceSynth';
import { soundEffects } from '../../services/soundEffects';

export type VoiceStudioPosition = 'inline' | 'floating' | 'bottom_dock' | 'sidebar';
export type VoiceStudioSize = 'compact' | 'normal' | 'expanded';

interface VoiceStudioProps {
  voice: VoiceSettings;
  onChange: (updated: VoiceSettings) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
  // Optional initial positioning
  initialPosition?: VoiceStudioPosition;
  initialSize?: VoiceStudioSize;
  allowDockingControls?: boolean;
}

export const VoiceStudio: React.FC<VoiceStudioProps> = ({
  voice,
  onChange,
  onToast,
  initialPosition = 'inline',
  initialSize = 'normal',
  allowDockingControls = true,
}) => {
  // Load layout from localStorage or fallback
  const [position, setPosition] = useState<VoiceStudioPosition>(() => {
    try {
      const saved = localStorage.getItem('elhadath_voice_studio_pos');
      return (saved as VoiceStudioPosition) || initialPosition;
    } catch {
      return initialPosition;
    }
  });

  const [size, setSize] = useState<VoiceStudioSize>(() => {
    try {
      const saved = localStorage.getItem('elhadath_voice_studio_size');
      return (saved as VoiceStudioSize) || initialSize;
    } catch {
      return initialSize;
    }
  });

  const [isMinimized, setIsMinimized] = useState<boolean>(false);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [stadiumReverb, setStadiumReverb] = useState<number>(35); // 0-100%
  const [soundFxVolume, setSoundFxVolume] = useState<number>(80);

  // Floating window drag coordinates
  const [floatingCoords, setFloatingCoords] = useState<{ x: number; y: number }>({ x: 40, y: 120 });
  const isDraggingRef = useRef<boolean>(false);
  const dragStartRef = useRef<{ startX: number; startY: number; initX: number; initY: number }>({
    startX: 0,
    startY: 0,
    initX: 40,
    initY: 120,
  });

  // Save changes to localStorage
  const handlePositionChange = (newPos: VoiceStudioPosition) => {
    setPosition(newPos);
    try {
      localStorage.setItem('elhadath_voice_studio_pos', newPos);
    } catch {}
    onToast(
      `تم تغيير موضع استوديو الصوت: ${
        newPos === 'floating'
          ? 'نافذة عائمة قابلة للتحريك'
          : newPos === 'bottom_dock'
          ? 'شريط تحكم سفلي مثبت'
          : newPos === 'sidebar'
          ? 'لوحة جانبية'
          : 'مدمج داخل الصفحة'
      }`,
      'ok'
    );
  };

  const handleSizeChange = (newSize: VoiceStudioSize) => {
    setSize(newSize);
    setIsMinimized(false);
    try {
      localStorage.setItem('elhadath_voice_studio_size', newSize);
    } catch {}
  };

  const update = (patch: Partial<VoiceSettings>) => {
    onChange({ ...voice, ...patch });
  };

  const applyPreset = (style: VoiceSettings['commentary_style']) => {
    switch (style) {
      case 'broadcast':
        update({
          commentary_style: 'broadcast',
          commentary_energy: 85,
          voice_gain: 2.1,
          voice_rate: 15,
          voice_duck: 0.2,
          commentary_words: 22,
        });
        break;
      case 'algerian':
        update({
          commentary_style: 'algerian',
          edge_voice: 'ar-DZ-IsmaelNeural',
          commentary_energy: 80,
          voice_gain: 2.0,
          voice_rate: 12,
          voice_duck: 0.22,
          commentary_words: 24,
        });
        break;
      case 'analyst':
        update({
          commentary_style: 'analyst',
          commentary_energy: 50,
          voice_gain: 1.7,
          voice_rate: 5,
          voice_duck: 0.3,
          commentary_words: 30,
        });
        break;
      case 'cinematic':
        update({
          commentary_style: 'cinematic',
          commentary_energy: 75,
          voice_gain: 2.0,
          voice_rate: 0,
          voice_duck: 0.15,
          commentary_words: 20,
        });
        break;
      case 'calm':
        update({
          commentary_style: 'calm',
          commentary_energy: 40,
          voice_gain: 1.6,
          voice_rate: -5,
          voice_duck: 0.25,
          commentary_words: 25,
        });
        break;
    }
    onToast(`تم تطبيق نمط التعليق: ${style}`, 'ok');
  };

  const handleAudioPreview = async () => {
    if (isPlaying) {
      voiceSynth.stop();
      setIsPlaying(false);
      return;
    }

    setIsPlaying(true);
    onToast('تشغيل محلي بصوت المتصفح؛ لا يُرسل النص إلى خدمة خارجية.', 'ok');
    try {
      await voiceSynth.playPreview(voice, () => {
        setIsPlaying(false);
      });
    } catch {
      setIsPlaying(false);
      onToast('تعذر تشغيل الصوت في المتصفح', 'err');
    }
  };

  // Dragging support for floating mode
  const handleMouseDown = (e: React.MouseEvent) => {
    if (position !== 'floating') return;
    isDraggingRef.current = true;
    dragStartRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      initX: floatingCoords.x,
      initY: floatingCoords.y,
    };

    const handleMouseMove = (moveEvt: MouseEvent) => {
      if (!isDraggingRef.current) return;
      const dx = moveEvt.clientX - dragStartRef.current.startX;
      const dy = moveEvt.clientY - dragStartRef.current.startY;
      setFloatingCoords({
        x: Math.max(10, Math.min(window.innerWidth - 380, dragStartRef.current.initX + dx)),
        y: Math.max(10, Math.min(window.innerHeight - 200, dragStartRef.current.initY + dy)),
      });
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
  };

  // Minimized Pill representation (if user minimized)
  if (isMinimized) {
    return (
      <div
        className={`fixed z-50 flex items-center gap-2 p-2 rounded-2xl bg-gradient-to-r from-[#182231] to-[#0c1219] border border-[#36d1dc]/40 shadow-2xl backdrop-blur-md cursor-pointer text-white animate-in fade-in duration-200 ${
          position === 'bottom_dock'
            ? 'bottom-4 left-1/2 -translate-x-1/2'
            : position === 'sidebar'
            ? 'top-24 right-4'
            : 'bottom-6 left-6'
        }`}
        onClick={() => setIsMinimized(false)}
        title="انقر لاستعادة استوديو صوت المعلق"
      >
        <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-[#36d1dc] to-[#2f6fe0] grid place-items-center text-white shadow-md">
          <Mic className="w-4 h-4 animate-pulse" />
        </div>
        <div className="text-xs">
          <div className="font-bold flex items-center gap-1.5">
            <span>استوديو الصوت</span>
            {isPlaying && <span className="w-2 h-2 rounded-full bg-[#25d07a] animate-ping" />}
          </div>
          <div className="text-[10px] text-[#8ea0b5]">
            {voice.commentary_style} · {voice.commentary_words} كلمة
          </div>
        </div>
        <button
          onClick={e => {
            e.stopPropagation();
            setIsMinimized(false);
          }}
          className="p-1 rounded-lg bg-white/10 hover:bg-white/20 transition"
          title="تكبير"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  // Positioning container wrappers
  let containerClasses = '';
  let containerStyles: React.CSSProperties = {};

  if (position === 'floating') {
    containerClasses =
      'fixed z-50 shadow-2xl border-2 border-[#36d1dc]/50 bg-gradient-to-b from-[#182231]/98 to-[#0c1219]/98 backdrop-blur-xl rounded-2xl max-h-[85vh] overflow-y-auto w-[420px] transition-all';
    containerStyles = {
      left: `${floatingCoords.x}px`,
      top: `${floatingCoords.y}px`,
    };
  } else if (position === 'bottom_dock') {
    containerClasses =
      'fixed bottom-0 inset-x-0 z-40 shadow-2xl border-t-2 border-[#36d1dc]/40 bg-gradient-to-r from-[#141e2b]/98 via-[#0c1219]/98 to-[#141e2b]/98 backdrop-blur-xl px-6 py-3.5 max-h-[48vh] overflow-y-auto transition-all';
  } else if (position === 'sidebar') {
    containerClasses =
      'fixed top-[70px] right-0 bottom-0 w-[420px] z-40 shadow-2xl border-l-2 border-[#36d1dc]/40 bg-[#0f151c]/98 backdrop-blur-xl p-4 overflow-y-auto transition-all';
  } else {
    // Inline mode
    containerClasses =
      'mt-4 p-4 rounded-xl border border-[#304056] bg-gradient-to-br from-[#1b2736]/95 to-[#0c1219]/95 text-xs shadow-xl transition-all';
  }

  return (
    <div className={containerClasses} style={containerStyles}>
      {/* Studio Header & Layout Controller */}
      <div
        className={`flex items-center justify-between gap-2 pb-2.5 border-b border-[#2c3a4d] ${
          position === 'floating' ? 'cursor-move' : ''
        }`}
        onMouseDown={handleMouseDown}
      >
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-tr from-[#36d1dc] to-[#2f6fe0] grid place-items-center text-white shadow">
            <Mic className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-1.5">
              <span>استوديو صوت المعلّق الرياضي</span>
              {isPlaying && (
                <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-[#25d07a]/20 text-[#25d07a] border border-[#25d07a]/40 animate-pulse">
                  بث حي
                </span>
              )}
            </h3>
            <p className="text-[10px] text-[#8ea0b5]">
              {position === 'floating' ? 'نافذة عائمة (اسحب لنقلها)' : 'تحكم كامل بنبرة المعلّق وهتاف الملعب'}
            </p>
          </div>
        </div>

        {/* Display / Size / Minimize Controls Toolbar */}
        {allowDockingControls && (
          <div className="flex items-center gap-1 bg-[#090e14]/80 p-1 rounded-xl border border-[#222e3d]">
            {/* Position modes */}
            <button
              onClick={() => handlePositionChange(position === 'inline' ? 'floating' : 'inline')}
              className={`p-1 rounded-lg text-xs transition ${
                position === 'floating'
                  ? 'bg-[#36d1dc] text-[#090e14] font-bold shadow'
                  : 'text-[#8ea0b5] hover:text-white hover:bg-white/10'
              }`}
              title={position === 'floating' ? 'تثبيت داخل الصفحة' : 'تحويل إلى نافذة عائمة'}
            >
              <Move className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => handlePositionChange(position === 'bottom_dock' ? 'inline' : 'bottom_dock')}
              className={`p-1 rounded-lg text-xs transition ${
                position === 'bottom_dock'
                  ? 'bg-[#36d1dc] text-[#090e14] font-bold shadow'
                  : 'text-[#8ea0b5] hover:text-white hover:bg-white/10'
              }`}
              title={position === 'bottom_dock' ? 'إلغاء الشريط السفلي' : 'تثبيت كشريط كونسول سفلي'}
            >
              <Dock className="w-3.5 h-3.5" />
            </button>

            {/* Size modes */}
            <button
              onClick={() => handleSizeChange(size === 'expanded' ? 'normal' : 'expanded')}
              className={`p-1 rounded-lg text-xs transition ${
                size === 'expanded'
                  ? 'bg-[#2f6fe0] text-white font-bold'
                  : 'text-[#8ea0b5] hover:text-white hover:bg-white/10'
              }`}
              title={size === 'expanded' ? 'الحجم العادي' : 'الحجم الموسّع الاحترافي'}
            >
              <Sliders className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => handleSizeChange(size === 'compact' ? 'normal' : 'compact')}
              className={`p-1 rounded-lg text-xs transition ${
                size === 'compact'
                  ? 'bg-[#2f6fe0] text-white font-bold'
                  : 'text-[#8ea0b5] hover:text-white hover:bg-white/10'
              }`}
              title={size === 'compact' ? 'الحجم العادي' : 'الحجم المصغّر السريع'}
            >
              <Layout className="w-3.5 h-3.5" />
            </button>

            {/* Minimize */}
            <button
              onClick={() => setIsMinimized(true)}
              className="p-1 rounded-lg text-[#8ea0b5] hover:text-white hover:bg-white/10 transition"
              title="تصغير إلى شارة عائمة"
            >
              <Minimize2 className="w-3.5 h-3.5" />
            </button>

            {position !== 'inline' && (
              <button
                onClick={() => handlePositionChange('inline')}
                className="p-1 rounded-lg text-[#8ea0b5] hover:text-white hover:bg-white/10 transition"
                title="إغلاق والعودة للصفحة"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Main checkboxes */}
      <div className="grid grid-cols-2 gap-2 my-2.5">
        <label className="flex items-center gap-2 p-1.5 rounded-lg bg-[#0c1219] border border-[#222e3d] text-white font-medium cursor-pointer">
          <input
            type="checkbox"
            checked={voice.commentary}
            onChange={e => update({ commentary: e.target.checked })}
            className="rounded"
          />
          <span className="text-[11px]">تفعيل المعلّق الذكي</span>
        </label>

        <label className="flex items-center gap-2 p-1.5 rounded-lg bg-[#0c1219] border border-[#222e3d] text-white font-medium cursor-pointer">
          <input
            type="checkbox"
            checked={voice.commtext}
            onChange={e => update({ commtext: e.target.checked })}
            className="rounded"
          />
          <span className="text-[11px]">إظهار النص على الفيديو</span>
        </label>
      </div>

      {/* Voice Engine & Style */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 mb-2.5">
        <div>
          <label className="block text-[#8ea0b5] font-semibold mb-1 text-[11px]">مصدر المعاينة</label>
          <div className="rounded-lg border border-[#2c3a4d] bg-[#0c1219] px-2 py-2 text-[11px] text-[#cfdcec]">
            صوت المتصفح المحلي — لا اتصال بـ Gemini أو Edge
          </div>
        </div>

        <div>
          <label className="block text-[#8ea0b5] font-semibold mb-1 text-[11px]">أسلوب التعليق</label>
          <select
            value={voice.commentary_style}
            onChange={e => update({ commentary_style: e.target.value as any })}
            className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg px-2 py-1.5 text-white text-xs"
          >
            <option value="broadcast">🎙️ معلّق رياضي حماسي</option>
            <option value="algerian">🇩🇿 روح جزائرية</option>
            <option value="analyst">📊 محلّل هادئ</option>
            <option value="cinematic">🎬 سينمائي متصاعد</option>
            <option value="calm">🧭 ملخص هادئ</option>
          </select>
        </div>
      </div>

      {/* Style Presets */}
      <div className="flex gap-1.5 flex-wrap mb-2.5">
        <button
          type="button"
          onClick={() => applyPreset('broadcast')}
          className="px-2 py-1 rounded bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] font-bold text-[10px] transition"
        >
          🎙️ حماسي
        </button>
        <button
          type="button"
          onClick={() => applyPreset('algerian')}
          className="px-2 py-1 rounded bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] font-bold text-[10px] transition"
        >
          🇩🇿 جزائري
        </button>
        <button
          type="button"
          onClick={() => applyPreset('analyst')}
          className="px-2 py-1 rounded bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] font-bold text-[10px] transition"
        >
          📊 محلّل
        </button>
        <button
          type="button"
          onClick={() => applyPreset('cinematic')}
          className="px-2 py-1 rounded bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] font-bold text-[10px] transition"
        >
          🎬 سينمائي
        </button>
        <button
          type="button"
          onClick={() => applyPreset('calm')}
          className="px-2 py-1 rounded bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] font-bold text-[10px] transition"
        >
          🧭 هادئ
        </button>
      </div>

      {/* Expanded Audio Visualizer & Stadium Reverb (Shown in normal & expanded modes) */}
      {size !== 'compact' && (
        <div className="p-2.5 rounded-xl bg-[#0a1017] border border-[#222e3d] mb-2.5 space-y-2">
          {/* Audio Visualizer Spectrum Bars */}
          <div className="flex items-center justify-between text-[10px] text-[#8ea0b5]">
            <span className="flex items-center gap-1 text-[#36d1dc] font-bold">
              <Activity className="w-3 h-3" />
              <span>مخطط الترددات الحية للمعلّق:</span>
            </span>
            <span>{isPlaying ? 'معاينة قيد التشغيل' : 'جاهز للمعاينة'}</span>
          </div>

          <div className="flex items-end justify-between h-8 gap-1 px-1 bg-black/40 rounded-lg overflow-hidden">
            {[45, 80, 60, 95, 70, 85, 90, 65, 75, 50, 88, 72].map((baseHeight, i) => {
              const activeHeight = isPlaying ? Math.min(100, Math.max(15, baseHeight + Math.sin(Date.now() / 200 + i) * 35)) : 15;
              return (
                <div
                  key={i}
                  className="flex-1 rounded-t-sm transition-all duration-100"
                  style={{
                    height: `${activeHeight}%`,
                    backgroundColor: i % 2 === 0 ? '#36d1dc' : '#2f6fe0',
                    opacity: isPlaying ? 0.9 : 0.3,
                  }}
                />
              );
            })}
          </div>

          {/* Sound Effects Board (Whistle, Crowd Roar, Net Impact, Horn) */}
          <div className="pt-1.5 border-t border-white/5 flex items-center justify-between gap-1 flex-wrap">
            <span className="text-[10px] text-[#8ea0b5] font-semibold">مؤثرات الملعب الفورية:</span>
            <div className="flex gap-1">
              <button
                type="button"
                onClick={() => soundEffects.playWhistle()}
                className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                title="صفارة الحكم"
              >
                📢 صفارة
              </button>
              <button
                type="button"
                onClick={() => soundEffects.playCrowdRoar()}
                className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                title="هتاف الجماهير"
              >
                🏟️ هتاف
              </button>
              <button
                type="button"
                onClick={() => soundEffects.playBallImpact()}
                className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                title="ارتطام الكرة بالشباك"
              >
                💥 الشباك
              </button>
              <button
                type="button"
                onClick={() => soundEffects.playStadiumHorn()}
                className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                title="بوق تشجيع حماسي"
              >
                🎺 بوق
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sliders Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        <div>
          <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold text-[11px]">
            <span>سرعة الصوت</span>
            <span className="text-[#36d1dc] font-mono">{voice.voice_rate > 0 ? `+${voice.voice_rate}%` : `${voice.voice_rate}%`}</span>
          </div>
          <input
            type="range"
            min="-20"
            max="50"
            value={voice.voice_rate}
            onChange={e => update({ voice_rate: Number(e.target.value) })}
            className="w-full accent-[#36d1dc] h-1.5 bg-[#0a0e13] rounded cursor-pointer"
          />
        </div>

        <div>
          <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold text-[11px]">
            <span>طبقة الصوت</span>
            <span className="text-[#36d1dc] font-mono">{voice.voice_pitch > 0 ? `+${voice.voice_pitch} Hz` : `${voice.voice_pitch} Hz`}</span>
          </div>
          <input
            type="range"
            min="-12"
            max="12"
            value={voice.voice_pitch}
            onChange={e => update({ voice_pitch: Number(e.target.value) })}
            className="w-full accent-[#36d1dc] h-1.5 bg-[#0a0e13] rounded cursor-pointer"
          />
        </div>

        <div>
          <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold text-[11px]">
            <span>قوة صوت المعلّق</span>
            <span className="text-[#36d1dc] font-mono">{voice.voice_gain}×</span>
          </div>
          <input
            type="range"
            min="0.5"
            max="3"
            step="0.1"
            value={voice.voice_gain}
            onChange={e => update({ voice_gain: Number(e.target.value) })}
            className="w-full accent-[#36d1dc] h-1.5 bg-[#0a0e13] rounded cursor-pointer"
          />
        </div>

        <div>
          <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold text-[11px]">
            <span>خفض صوت الملعب (Ducking)</span>
            <span className="text-[#36d1dc] font-mono">{Math.round(voice.voice_duck * 100)}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={voice.voice_duck}
            onChange={e => update({ voice_duck: Number(e.target.value) })}
            className="w-full accent-[#36d1dc] h-1.5 bg-[#0a0e13] rounded cursor-pointer"
          />
        </div>

        <div>
          <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold text-[11px]">
            <span>حماسة النص</span>
            <span className="text-[#36d1dc] font-mono">{voice.commentary_energy}/100</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            value={voice.commentary_energy}
            onChange={e => update({ commentary_energy: Number(e.target.value) })}
            className="w-full accent-[#36d1dc] h-1.5 bg-[#0a0e13] rounded cursor-pointer"
          />
        </div>

        {/* AI commentary length cap: 8 to 80 words (default 22) per AGENTS.md */}
        <div>
          <div className="flex justify-between text-[#8ea0b5] mb-1 font-semibold text-[11px]">
            <span>طول تعليق AI الأقصى</span>
            <span className="text-[#36d1dc] font-mono">{voice.commentary_words} كلمة</span>
          </div>
          <input
            type="range"
            min="8"
            max="80"
            value={voice.commentary_words}
            onChange={e => update({ commentary_words: Number(e.target.value) })}
            className="w-full accent-[#36d1dc] h-1.5 bg-[#0a0e13] rounded cursor-pointer"
          />
          {/* Quick Word Preset Buttons */}
          <div className="flex items-center gap-1 mt-1 justify-end">
            <button
              type="button"
              onClick={() => update({ commentary_words: 22 })}
              className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                voice.commentary_words === 22 ? 'bg-[#36d1dc] text-[#090e14]' : 'bg-[#182231] text-[#8ea0b5]'
              }`}
            >
              22 كلمة (افتراضي)
            </button>
            <button
              type="button"
              onClick={() => update({ commentary_words: 40 })}
              className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                voice.commentary_words === 40 ? 'bg-[#36d1dc] text-[#090e14]' : 'bg-[#182231] text-[#8ea0b5]'
              }`}
            >
              40 كلمة
            </button>
            <button
              type="button"
              onClick={() => update({ commentary_words: 65 })}
              className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                voice.commentary_words === 65 ? 'bg-[#36d1dc] text-[#090e14]' : 'bg-[#182231] text-[#8ea0b5]'
              }`}
            >
              65 كلمة
            </button>
          </div>
        </div>
      </div>

      {/* Manual Script Override */}
      <div className="mt-2.5">
        <label className="block text-[#8ea0b5] font-semibold mb-1 text-[11px]">
          نص المعلّق (اختياري — يتجاوز حد الكلمات الآلي ويكتب بصوتك)
        </label>
        <textarea
          rows={2}
          value={voice.commentary_script}
          onChange={e => update({ commentary_script: e.target.value })}
          placeholder="اكتب نصاً أو اتركه فارغاً لمعاينة عبارة نموذجية محلية..."
          className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg p-2 text-white placeholder:text-[#6f8291] text-xs"
        />
      </div>

      {/* Preview Voice Button */}
      <div className="mt-3 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={handleAudioPreview}
          className={`flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold text-white transition ${
            isPlaying
              ? 'bg-[#e63946] hover:bg-[#d02835]'
              : 'bg-gradient-to-r from-[#1c9ca8] to-[#146b82] hover:brightness-110 shadow-md shadow-[#1c9ca8]/20'
          }`}
        >
          {isPlaying ? (
            <>
              <Square className="w-3.5 h-3.5 fill-current" />
              <span>إيقاف المعاينة</span>
            </>
          ) : (
            <>
              <Volume2 className="w-3.5 h-3.5" />
              <span>🎧 استمع لمعاينة صوت المعلّق</span>
            </>
          )}
        </button>

        <span className="text-[10px] text-[#8ea0b5]">
          الصوت العربي المتاح في المتصفح
        </span>
      </div>
    </div>
  );
};
