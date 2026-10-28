import React, { useRef, useState, useEffect } from 'react';
import {
  Play,
  Pause,
  RotateCcw,
  Volume2,
  VolumeX,
  Target,
  Maximize2,
  Activity,
  Layers,
  Sparkles,
  Camera,
  ShieldCheck,
  Zap,
  Tv,
} from 'lucide-react';
import { soundEffects } from '../../services/soundEffects';

interface ProShotTrackerProps {
  videoUrl?: string;
  thumbnailUrl?: string;
  sourceTitle?: string;
  onApplyCropSettings?: (settings: { subject: string; tracker: string; replay: boolean; burst: boolean }) => void;
  onToast?: (msg: string, type?: 'ok' | 'err') => void;
}

export const ProShotTracker: React.FC<ProShotTrackerProps> = ({
  videoUrl,
  thumbnailUrl,
  sourceTitle = 'لقطة المباراة',
  onApplyCropSettings,
  onToast,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Playback states
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.0); // 1.0, 0.5, 0.25
  const [isMuted, setIsMuted] = useState<boolean>(true);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(12);

  // Tracking options
  const [showBallTrack, setShowBallTrack] = useState<boolean>(false);
  const [showPlayerBoxes, setShowPlayerBoxes] = useState<boolean>(false);
  const [showCropGuide, setShowCropGuide] = useState<boolean>(true);
  const [showHeatmap, setShowHeatmap] = useState<boolean>(false);
  const [showScoreboard, setShowScoreboard] = useState<boolean>(false);
  const [showSpotlight, setShowSpotlight] = useState<boolean>(false);
  const [subjectFocus, setSubjectFocus] = useState<'action' | 'ball' | 'player'>('action');
  const [homeTeam, setHomeTeam] = useState<string>('فريق 1');
  const [awayTeam, setAwayTeam] = useState<string>('فريق 2');
  const [homeScore, setHomeScore] = useState<number>(0);
  const [awayScore, setAwayScore] = useState<number>(0);
  const [matchMinute, setMatchMinute] = useState<string>('--');
  const [cropCenterX, setCropCenterX] = useState<number>(50);

  // Fallback demo video if no source is given
  const effectiveVideoUrl =
    videoUrl || 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4';

  // Ball history trail points (percentage coordinates)
  const ballTrailRef = useRef<Array<{ x: number; y: number; time: number }>>([]);

  // Animation / Tracking loop on HTML5 Canvas
  useEffect(() => {
    let animationFrameId: number;

    const renderOverlay = () => {
      const canvas = canvasRef.current;
      const video = videoRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      // Match canvas dimensions to display size
      if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) {
        canvas.width = canvas.clientWidth;
        canvas.height = canvas.clientHeight;
      }

      const w = canvas.width;
      const h = canvas.height;

      ctx.clearRect(0, 0, w, h);

      // Current playback time
      const t = video ? video.currentTime : (Date.now() / 1000) % 12;
      setCurrentTime(t);

      // Simulate curved football shot trajectory over time
      const cycle = (t % 6) / 6; // 0 to 1 every 6 seconds
      // Ball moves from right wing to center penalty box to top corner
      const bx = 30 + Math.sin(cycle * Math.PI) * 45;
      const by = 65 - Math.sin(cycle * Math.PI) * 40 + Math.sin(cycle * Math.PI * 4) * 5;

      // Smooth camera pan lerp towards ball or action
      const targetCropX = Math.max(25, Math.min(75, bx));
      setCropCenterX(prev => prev + (targetCropX - prev) * 0.08);

      // Update telemetry
      // Append ball trail
      ballTrailRef.current.push({ x: bx, y: by, time: Date.now() });
      if (ballTrailRef.current.length > 25) {
        ballTrailRef.current.shift();
      }

      // 1. Draw Spotlight if enabled
      if (showSpotlight) {
        ctx.save();
        ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
        ctx.fillRect(0, 0, w, h);

        const spotX = (bx / 100) * w;
        const spotY = (by / 100) * h;
        const rad = 90;

        ctx.globalCompositeOperation = 'destination-out';
        const grad = ctx.createRadialGradient(spotX, spotY, 20, spotX, spotY, rad);
        grad.addColorStop(0, 'rgba(0,0,0,1)');
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(spotX, spotY, rad, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      // 2. Draw Heatmap / Danger Zone
      if (showHeatmap) {
        ctx.save();
        const heatX = (bx / 100) * w;
        const heatY = (by / 100) * h;
        const heatGrad = ctx.createRadialGradient(heatX, heatY, 10, heatX, heatY, 140);
        heatGrad.addColorStop(0, 'rgba(230, 57, 70, 0.45)');
        heatGrad.addColorStop(0.5, 'rgba(244, 162, 97, 0.25)');
        heatGrad.addColorStop(1, 'rgba(42, 157, 143, 0)');
        ctx.fillStyle = heatGrad;
        ctx.beginPath();
        ctx.arc(heatX, heatY, 140, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      // 3. Draw 9:16 Smooth Crop Viewport Guide (Smart Vertical Camera)
      if (showCropGuide) {
        ctx.save();
        // 9:16 aspect ratio box centered at cropCenterX
        const cropBoxHeight = h * 0.95;
        const cropBoxWidth = (cropBoxHeight * 9) / 16;
        const cropX = (cropCenterX / 100) * w - cropBoxWidth / 2;
        const cropY = (h - cropBoxHeight) / 2;

        // Darken outside the vertical 9:16 frame
        ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
        ctx.fillRect(0, 0, cropX, h); // Left pillar
        ctx.fillRect(cropX + cropBoxWidth, 0, w - (cropX + cropBoxWidth), h); // Right pillar

        // Neon border around vertical 9:16 reel frame
        ctx.strokeStyle = '#36d1dc';
        ctx.lineWidth = 2.5;
        ctx.setLineDash([8, 4]);
        ctx.strokeRect(cropX, cropY, cropBoxWidth, cropBoxHeight);
        ctx.setLineDash([]);

        // Vertical frame badge
        ctx.fillStyle = '#36d1dc';
        ctx.fillRect(cropX, cropY - 22, 140, 22);
        ctx.fillStyle = '#0a1118';
        ctx.font = 'bold 11px system-ui, sans-serif';
        ctx.fillText('📱 إطار الريل 9:16 (الهدف)', cropX + 8, cropY - 7);

        // Safe Zone guide (TikTok/Reels UI safety margins)
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
        ctx.lineWidth = 1;
        // Right side interaction margin
        ctx.strokeRect(cropX + cropBoxWidth - 45, cropY + 60, 40, cropBoxHeight - 120);

        ctx.restore();
      }

      // 4. Draw Ball Trajectory Trail & Target Box
      if (showBallTrack) {
        ctx.save();
        // Trail line
        if (ballTrailRef.current.length > 1) {
          ctx.beginPath();
          ctx.strokeStyle = '#f59e0b';
          ctx.lineWidth = 3;
          ctx.lineCap = 'round';
          ballTrailRef.current.forEach((pt, i) => {
            const px = (pt.x / 100) * w;
            const py = (pt.y / 100) * h;
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
          });
          ctx.stroke();
        }

        // Ball Box
        const ballPx = (bx / 100) * w;
        const ballPy = (by / 100) * h;
        const boxSize = 36;

        ctx.strokeStyle = '#25d07a';
        ctx.lineWidth = 2;
        ctx.strokeRect(ballPx - boxSize / 2, ballPy - boxSize / 2, boxSize, boxSize);

        // Reticle corners
        ctx.fillStyle = '#25d07a';
        const cr = 6;
        ctx.fillRect(ballPx - boxSize / 2 - 2, ballPy - boxSize / 2 - 2, cr, 2);
        ctx.fillRect(ballPx - boxSize / 2 - 2, ballPy - boxSize / 2 - 2, 2, cr);
        ctx.fillRect(ballPx + boxSize / 2 + 2 - cr, ballPy - boxSize / 2 - 2, cr, 2);
        ctx.fillRect(ballPx + boxSize / 2, ballPy - boxSize / 2 - 2, 2, cr);

        // Tag label
        ctx.fillStyle = 'rgba(10, 17, 24, 0.85)';
        ctx.fillRect(ballPx - boxSize / 2, ballPy - boxSize / 2 - 20, 115, 18);
        ctx.fillStyle = '#25d07a';
        ctx.font = 'bold 10px monospace';
        ctx.fillText('مسار توضيحي', ballPx - boxSize / 2 + 4, ballPy - boxSize / 2 - 7);

        ctx.restore();
      }

      // 5. Draw Key Players Bounding Boxes
      if (showPlayerBoxes) {
        ctx.save();
        // Striker
        const sx = ((bx - 8) / 100) * w;
        const sy = ((by + 12) / 100) * h;
        const sw = 48;
        const sh = 100;

        ctx.strokeStyle = '#e63946';
        ctx.lineWidth = 1.8;
        ctx.strokeRect(sx - sw / 2, sy - sh / 2, sw, sh);

        ctx.fillStyle = 'rgba(230, 57, 70, 0.9)';
        ctx.fillRect(sx - sw / 2, sy - sh / 2 - 16, 75, 16);
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 9px system-ui, sans-serif';
        ctx.fillText('مهاجم #9 ⚡', sx - sw / 2 + 4, sy - sh / 2 - 4);

        // Defender
        const dx = ((bx + 22) / 100) * w;
        const dy = ((by + 8) / 100) * h;
        const dw = 46;
        const dh = 96;

        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(dx - dw / 2, dy - dh / 2, dw, dh);

        ctx.fillStyle = 'rgba(59, 130, 246, 0.9)';
        ctx.fillRect(dx - dw / 2, dy - dh / 2 - 16, 68, 16);
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 9px system-ui, sans-serif';
        ctx.fillText('مدافع #4 🛡️', dx - dw / 2 + 4, dy - dh / 2 - 4);

        ctx.restore();
      }

      animationFrameId = requestAnimationFrame(renderOverlay);
    };

    animationFrameId = requestAnimationFrame(renderOverlay);
    return () => cancelAnimationFrame(animationFrameId);
  }, [
    showBallTrack,
    showPlayerBoxes,
    showCropGuide,
    showHeatmap,
    showSpotlight,
    cropCenterX,
  ]);

  // Video controls
  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play().catch(() => {});
      }
    }
    setIsPlaying(!isPlaying);
  };

  const handleSpeedChange = (speed: number) => {
    setPlaybackSpeed(speed);
    if (videoRef.current) {
      videoRef.current.playbackRate = speed;
    }
    if (speed < 1.0) {
      soundEffects.playCinematicWhoosh();
      if (onToast) onToast(`تم تفعيل الحركة البطيئة (${speed}×)`, 'ok');
    }
  };

  const toggleMute = () => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted;
    }
    setIsMuted(!isMuted);
  };

  const applyCropToReel = () => {
    if (onApplyCropSettings) {
      onApplyCropSettings({
        subject: subjectFocus,
        tracker: 'auto',
        replay: playbackSpeed < 1.0,
        burst: false,
      });
      if (onToast) onToast('حُفظت تفضيلات معاينة محلية فقط؛ لم يعمل تتبّع أو رندر فعلي.', 'ok');
    }
  };

  return (
    <div className="bg-[#101720] border border-[#222e3d] rounded-2xl overflow-hidden shadow-2xl">
      {/* Tracker Top Bar */}
      <div className="p-4 border-b border-[#222e3d] flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r from-[#141d28] to-[#0c1219]">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-[#36d1dc] to-[#5b86e5] grid place-items-center text-white shadow-lg">
            <Target className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-black text-white">معاينة القص والحركة (توضيحية)</h3>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#282114] border border-[#664c30] text-[#e5c99a]">
                دون كاشف
              </span>
            </div>
            <p className="text-xs text-[#8ea0b5] mt-0.5">
              إطار 9:16 قابل للمعاينة؛ أي مسار أو مربعات أو لوحة نتيجة هي رسومات شكلية وليست كشفاً أو قياسات من الفيديو.
            </p>
          </div>
        </div>

        {/* Quick Speed / Replay selector */}
        <div className="flex items-center gap-1.5 bg-[#090e14] p-1 rounded-xl border border-[#222e3d]">
          <button
            onClick={() => handleSpeedChange(1.0)}
            className={`px-2.5 py-1 rounded-lg text-xs font-bold transition ${
              playbackSpeed === 1.0 ? 'bg-[#2f6fe0] text-white shadow' : 'text-[#8ea0b5] hover:text-white'
            }`}
          >
            1.0× عادي
          </button>
          <button
            onClick={() => handleSpeedChange(0.5)}
            className={`px-2.5 py-1 rounded-lg text-xs font-bold transition flex items-center gap-1 ${
              playbackSpeed === 0.5 ? 'bg-[#e63946] text-white shadow' : 'text-[#8ea0b5] hover:text-white'
            }`}
          >
            <span>0.5× بطيء</span>
          </button>
          <button
            onClick={() => handleSpeedChange(0.25)}
            className={`px-2.5 py-1 rounded-lg text-xs font-bold transition flex items-center gap-1 ${
              playbackSpeed === 0.25 ? 'bg-[#e63946] text-white shadow' : 'text-[#8ea0b5] hover:text-white'
            }`}
          >
            <span>0.25× دقيق</span>
          </button>
        </div>
      </div>

      {/* Main Video & Tracking Stage */}
      <div className="relative aspect-video w-full bg-black overflow-hidden flex items-center justify-center select-none">
        {/* Underlay Video Feed */}
        <video
          ref={videoRef}
          src={effectiveVideoUrl}
          autoPlay
          loop
          muted={isMuted}
          playsInline
          onLoadedMetadata={e => setDuration(e.currentTarget.duration || 12)}
          className="w-full h-full object-cover"
        />

        {/* Dynamic HTML5 Tracking Canvas Overlay */}
        <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />

        {/* Floating TV Lower-Thirds Scoreboard Widget */}
        {showScoreboard && (
          <div className="absolute top-4 left-4 z-20 flex items-center gap-2 bg-black/85 backdrop-blur-md border border-white/20 rounded-xl px-3 py-1.5 shadow-2xl text-xs font-bold text-white">
            <span className="flex items-center gap-1.5 text-[#36d1dc]">
              <Tv className="w-3.5 h-3.5" />
              <span>{matchMinute}</span>
            </span>
            <span className="h-3 w-px bg-white/20" />
            <span className="text-amber-400">{homeTeam}</span>
            <span className="bg-white/20 px-1.5 py-0.5 rounded text-[11px] font-mono">{homeScore}</span>
            <span className="text-white/50">-</span>
            <span className="bg-white/20 px-1.5 py-0.5 rounded text-[11px] font-mono">{awayScore}</span>
            <span className="text-sky-400">{awayTeam}</span>
            <span className="text-[10px] text-[#e5c99a]">لوحة توضيحية</span>
          </div>
        )}

        <div className="absolute top-4 right-4 z-20 rounded-xl border border-[#664c30] bg-[#282114]/90 px-3 py-2 text-right text-[10px] text-[#e5c99a] shadow-xl">
          مسار وحركة توضيحيان — لا توجد قياسات فعلية
        </div>

        {/* Bottom Playback HUD Bar */}
        <div className="absolute bottom-3 inset-x-4 z-20 flex items-center justify-between gap-2 bg-black/75 backdrop-blur-md border border-white/10 rounded-xl px-3 py-2 text-white">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              className="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 transition text-white"
            >
              {isPlaying ? <Pause className="w-4 h-4 fill-current" /> : <Play className="w-4 h-4 fill-current" />}
            </button>
            <button
              onClick={toggleMute}
              className="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 transition text-white"
            >
              {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
            </button>
            <span className="text-xs font-mono text-white/80">
              {currentTime.toFixed(1)}s / {duration.toFixed(1)}s
            </span>
          </div>

          {/* Sound FX Buttons */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => soundEffects.playWhistle()}
              className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#222e3d] text-[#cfdcec] border border-[#2c3a4d] transition"
              title="صفارة الحكم"
            >
              📢 صفارة
            </button>
            <button
              onClick={() => soundEffects.playCrowdRoar()}
              className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#222e3d] text-[#cfdcec] border border-[#2c3a4d] transition"
              title="هتاف الملعب"
            >
              🏟️ هتاف
            </button>
            <button
              onClick={() => soundEffects.playBallImpact()}
              className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#222e3d] text-[#cfdcec] border border-[#2c3a4d] transition"
              title="صدمة الشباك"
            >
              💥 الشباك
            </button>
            <button
              onClick={() => soundEffects.playStadiumHorn()}
              className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#222e3d] text-[#cfdcec] border border-[#2c3a4d] transition"
              title="بوق تشجيع"
            >
              🎺 بوق
            </button>
          </div>
        </div>
      </div>

      {/* Control Strip & Pro Toggles */}
      <div className="p-4 bg-[#131a23] border-t border-[#222e3d] grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
        {/* Toggle Overlays */}
        <div className="space-y-2">
          <span className="block font-bold text-white mb-1.5">طبقات توضيحية غير متصلة:</span>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={showBallTrack}
              onChange={e => setShowBallTrack(e.target.checked)}
              className="rounded"
            />
            <span>مسار كرة توضيحي (لا سرعة فعلية)</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={showPlayerBoxes}
              onChange={e => setShowPlayerBoxes(e.target.checked)}
              className="rounded"
            />
            <span>مربعات لاعبين توضيحية (لا كشف)</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={showCropGuide}
              onChange={e => setShowCropGuide(e.target.checked)}
              className="rounded"
            />
            <span>📱 إطار القص العمودي الذكي 9:16</span>
          </label>
        </div>

        {/* Visual FX Toggles */}
        <div className="space-y-2">
          <span className="block font-bold text-white mb-1.5">مؤثرات الكاميرا والملعب:</span>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={showHeatmap}
              onChange={e => setShowHeatmap(e.target.checked)}
              className="rounded"
            />
            <span>خريطة حرارية توضيحية (لا تحليل خطورة)</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={showSpotlight}
              onChange={e => setShowSpotlight(e.target.checked)}
              className="rounded"
            />
            <span>تأثير إضاءة توضيحي</span>
          </label>
          <label className="flex items-center gap-2 text-[#cfdcec] cursor-pointer">
            <input
              type="checkbox"
              checked={showScoreboard}
              onChange={e => setShowScoreboard(e.target.checked)}
              className="rounded"
            />
            <span>لوحة نتيجة توضيحية (لا تعكس مباراة حقيقية)</span>
          </label>
        </div>

        <div className="space-y-2">
          <span className="block font-bold text-white mb-1.5">بؤرة المعاينة:</span>
          <div className="rounded-lg border border-[#664c30] bg-[#282114] px-2.5 py-2 text-[10px] leading-relaxed text-[#e5c99a]">
            محرّكات YOLO والتتبّع غير متصلة بهذه الواجهة.
          </div>
          <div>
            <select
              value={subjectFocus}
              onChange={e => setSubjectFocus(e.target.value as any)}
              className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-lg px-2.5 py-1.5 text-white"
            >
              <option value="action">🎯 تتبّع مجرى اللعب كلياً (Action)</option>
              <option value="ball">⚽ تتبّع الكرة حصراً (Ball Focus)</option>
              <option value="player">🏃 تتبّع اللاعب الأبرز (Player)</option>
            </select>
          </div>
        </div>

        {/* Action Button & Resilience Spec */}
        <div className="flex flex-col justify-between">
          <div className="p-2.5 rounded-xl border border-[#664c30] bg-[#282114] text-[11px] leading-relaxed text-[#e5c99a]">
            لا يوجد رندر أو تتبّع خادمي في هذا النموذج. علامات المصدر لا تُزال.
          </div>

          <button
            onClick={applyCropToReel}
            className="w-full mt-2 px-4 py-2.5 rounded-xl font-bold text-xs text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 transition flex items-center justify-center gap-2 shadow"
          >
            <Sparkles className="w-4 h-4 text-[#36d1dc]" />
            <span>حفظ تفضيلات المعاينة المحلية</span>
          </button>
        </div>
      </div>
    </div>
  );
};
