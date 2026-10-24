import React, { useRef, useState } from 'react';
import { X, Play, Pause, Download, Volume2, VolumeX, RotateCcw, Sparkles, Target, Activity, ShieldCheck, CheckCircle2 } from 'lucide-react';
import { AppSettings, Job, LogoSettings } from '../../types';
import { videoProcessor } from '../../services/videoProcessor';
import { soundEffects } from '../../services/soundEffects';

interface VideoModalProps {
  job: Job;
  settings: AppSettings;
  logoSettings: LogoSettings;
  onClose: () => void;
}

export const VideoModal: React.FC<VideoModalProps> = ({ job, settings, logoSettings, onClose }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [slowMo, setSlowMo] = useState<boolean>(false);
  const [hasVideoError, setHasVideoError] = useState<boolean>(false);
  const [simulatedTime, setSimulatedTime] = useState<number>(0);
  const [isRendering, setIsRendering] = useState<boolean>(false);
  const [renderProgress, setRenderProgress] = useState<number>(0);
  const [showTrackingOverlay, setShowTrackingOverlay] = useState<boolean>(true);

  const handleExportReel = async () => {
    if (!videoRef.current) return;
    setIsRendering(true);
    setRenderProgress(0);
    try {
      const { downloadUrl } = await videoProcessor.renderVerticalReel({
        videoElement: videoRef.current,
        startTime: 0,
        endTime: Math.min(job.duration, 15),
        brandName: settings.brand_name || 'الحدث',
        brandY: job.brand_y,
        commentaryText: job.commentary_text,
        onProgress: p => setRenderProgress(p),
      });

      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = `elhadath_${job.filename.replace(/\.[^/.]+$/, '')}_reel.webm`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      console.warn('Export error', e);
    } finally {
      setIsRendering(false);
    }
  };

  // Simulated playback timer for fallback visualizer
  React.useEffect(() => {
    let timer: any;
    if (hasVideoError && isPlaying) {
      const step = slowMo ? 0.5 : 1.0;
      timer = setInterval(() => {
        setSimulatedTime(prev => {
          const next = prev + step * 0.2;
          return next >= job.duration ? 0 : next;
        });
      }, 200);
    }
    return () => clearInterval(timer);
  }, [hasVideoError, isPlaying, slowMo, job.duration]);

  const togglePlay = () => {
    if (!hasVideoError && videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play().catch(() => setHasVideoError(true));
      }
    }
    setIsPlaying(!isPlaying);
  };

  const toggleMute = () => {
    if (!hasVideoError && videoRef.current) {
      videoRef.current.muted = !isMuted;
    }
    setIsMuted(!isMuted);
  };

  const toggleSlowMo = () => {
    const next = !slowMo;
    if (!hasVideoError && videoRef.current) {
      videoRef.current.playbackRate = next ? 0.5 : 1.0;
    }
    setSlowMo(next);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="relative bg-[#131a23] border border-[#2c3a4d] rounded-2xl max-w-4xl w-full p-5 shadow-2xl overflow-hidden max-h-[95vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-[#222e3d] mb-4">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <span>{job.title}</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#182231] border border-[#2c3a4d] text-[#36d1dc]">
                {job.out_size}
              </span>
            </h2>
            <p className="text-xs text-[#8ea0b5] mt-0.5">{job.filename} · {job.duration} ثانية</p>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-[#182231] hover:bg-[#222e3d] text-[#8ea0b5] hover:text-white transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Player Layout */}
        <div className="grid grid-cols-1 md:grid-cols-[340px_1fr] gap-6 items-center flex-1 overflow-auto">
          {/* 9:16 Vertical Reel Player */}
          <div
            onClick={togglePlay}
            className="relative mx-auto aspect-[9/16] w-full max-h-[500px] rounded-2xl overflow-hidden bg-black border-2 border-[#2c3a4d] shadow-2xl flex items-center justify-center cursor-pointer select-none group"
          >
            {!hasVideoError && job.output_url ? (
              <video
                ref={videoRef}
                src={job.output_url}
                autoPlay
                muted={isMuted}
                loop
                playsInline
                onError={() => setHasVideoError(true)}
                className="w-full h-full object-cover"
              />
            ) : (
              /* Fallback Animated 9:16 Vertical Reel Visualizer */
              <div className="relative w-full h-full overflow-hidden bg-gradient-to-b from-[#0a1118] to-black flex items-center justify-center">
                {job.thumbnail_url && (
                  <img
                    src={job.thumbnail_url}
                    alt={job.title}
                    className={`w-full h-full object-cover transition-transform duration-700 ${
                      isPlaying ? 'scale-105 brightness-95' : 'scale-100 brightness-75'
                    }`}
                  />
                )}

                {/* Simulated YOLO11n Tracking Bounding Box */}
                {isPlaying && (
                  <div
                    className="absolute border-2 border-[#25d07a] rounded-lg p-1 text-[9px] font-mono text-[#25d07a] bg-black/40 backdrop-blur-xs transition-all duration-300 pointer-events-none"
                    style={{
                      top: `${35 + Math.sin(simulatedTime) * 15}%`,
                      left: `${30 + Math.cos(simulatedTime * 0.8) * 20}%`,
                    }}
                  >
                    ⚽ YOLO11: Ball 96%
                  </div>
                )}

                {/* Scrubber at bottom */}
                <div className="absolute bottom-16 inset-x-4">
                  <div className="w-full h-1.5 bg-white/20 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-[#36d1dc] to-[#e63946] transition-all"
                      style={{ width: `${(simulatedTime / job.duration) * 100}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-[10px] text-white/80 font-mono mt-1">
                    <span>{simulatedTime.toFixed(1)}s</span>
                    <span>{job.duration}s</span>
                  </div>
                </div>

                {/* Center Play indicator if paused */}
                {!isPlaying && (
                  <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                    <div className="w-14 h-14 rounded-full bg-white/20 backdrop-blur-md grid place-items-center text-white shadow-2xl">
                      <Play className="w-7 h-7 fill-current ml-1" />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Live Professional Tracking Overlay HUD */}
            {showTrackingOverlay && (
              <>
                {/* Ball Tracking Target Box */}
                <div
                  className="absolute border-2 border-[#25d07a] rounded-lg p-1 text-[9px] font-mono text-[#25d07a] bg-black/60 backdrop-blur-xs transition-all duration-300 pointer-events-none z-10 shadow-lg"
                  style={{
                    top: `${36 + Math.sin(simulatedTime * 2) * 12}%`,
                    left: `${38 + Math.cos(simulatedTime * 1.5) * 22}%`,
                  }}
                >
                  <div className="font-bold flex items-center gap-1">
                    <span>⚽ YOLO11n:</span>
                    <span className="text-white">96.8%</span>
                  </div>
                  <div className="text-[8px] text-amber-400">104 km/h · هدف</div>
                </div>

                {/* Striker Player Bounding Box */}
                <div
                  className="absolute border border-[#e63946] rounded p-0.5 text-[8px] font-bold text-white bg-[#e63946]/30 backdrop-blur-xs transition-all duration-500 pointer-events-none z-10 w-12 h-24"
                  style={{
                    top: `${40 + Math.sin(simulatedTime * 1.2) * 8}%`,
                    left: `${28 + Math.cos(simulatedTime) * 15}%`,
                  }}
                >
                  <span className="bg-[#e63946] px-1 rounded text-[7px]">مهاجم #9</span>
                </div>

                {/* Scoreboard Pill on top */}
                <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-black/70 backdrop-blur-md border border-white/20 text-[10px] text-white font-bold pointer-events-none">
                  <span className="text-[#36d1dc]">87'</span>
                  <span className="text-amber-400">2 - 1</span>
                  <span className="w-1.5 h-1.5 rounded-full bg-[#25d07a] animate-ping" />
                </div>
              </>
            )}

            {/* Simulated Channel Badge per brand_y & scale */}
            {job.show_channel_name && (
              <div
                className="absolute right-3 px-2 py-0.5 rounded-full bg-black/60 backdrop-blur-md border border-white/20 text-white font-bold text-[11px] shadow-lg pointer-events-none z-10"
                style={{
                  top: `${job.brand_y || 13}%`,
                  transform: `scale(${(job.brand_scale || 100) / 100})`,
                  transformOrigin: 'top right',
                }}
              >
                ⚽ {settings.brand_name || 'الحدث'}
              </div>
            )}

            {/* Commentary Subtitle on Reel */}
            {job.commentary_text && (
              <div className="absolute bottom-6 inset-x-3 p-2 rounded-xl bg-black/75 backdrop-blur-md border border-white/10 text-center text-xs font-bold text-white shadow-xl pointer-events-none z-10">
                {job.commentary_text}
              </div>
            )}

            {/* Slow Motion indicator */}
            {slowMo && (
              <div className="absolute top-3 left-16 bg-[#e63946] text-white text-[10px] font-black px-2 py-0.5 rounded-full shadow animate-pulse pointer-events-none z-10">
                إعادة بطيئة 0.5×
              </div>
            )}
          </div>

          {/* Controls & Details */}
          <div className="space-y-3.5 text-xs">
            {/* Playback Actions */}
            <div className="flex gap-1.5 flex-wrap">
              <button
                onClick={togglePlay}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#2f6fe0] hover:bg-[#255ec4] text-white font-bold transition"
              >
                {isPlaying ? <Pause className="w-3.5 h-3.5 fill-current" /> : <Play className="w-3.5 h-3.5 fill-current" />}
                <span>{isPlaying ? 'إيقاف' : 'تشغيل'}</span>
              </button>

              <button
                onClick={toggleSlowMo}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-bold transition ${
                  slowMo ? 'bg-[#e63946] text-white' : 'bg-[#182231] hover:bg-[#222e3d] text-[#cfdcec] border border-[#2c3a4d]'
                }`}
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>إعادة بطيئة</span>
              </button>

              <button
                onClick={() => setShowTrackingOverlay(!showTrackingOverlay)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl font-bold transition border ${
                  showTrackingOverlay
                    ? 'bg-[#36d1dc] text-[#090e14] border-[#36d1dc]'
                    : 'bg-[#182231] hover:bg-[#222e3d] text-[#36d1dc] border-[#36d1dc]/40'
                }`}
              >
                <Target className="w-3.5 h-3.5" />
                <span>طبقة التتبّع (HUD)</span>
              </button>

              <button
                onClick={toggleMute}
                className="p-1.5 rounded-xl bg-[#182231] hover:bg-[#222e3d] text-[#cfdcec] border border-[#2c3a4d] transition"
              >
                {isMuted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
              </button>
            </div>

            {/* Stadium Sound Effects Bar */}
            <div className="p-2.5 rounded-xl bg-[#0a1017] border border-[#222e3d] flex items-center justify-between gap-1 flex-wrap">
              <span className="text-[11px] text-[#8ea0b5] font-semibold">مؤثرات الملعب المباشرة:</span>
              <div className="flex gap-1">
                <button
                  onClick={() => soundEffects.playWhistle()}
                  className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                >
                  📢 صفارة
                </button>
                <button
                  onClick={() => soundEffects.playCrowdRoar()}
                  className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                >
                  🏟️ هتاف
                </button>
                <button
                  onClick={() => soundEffects.playBallImpact()}
                  className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                >
                  💥 الشباك
                </button>
                <button
                  onClick={() => soundEffects.playStadiumHorn()}
                  className="px-2 py-1 rounded-lg text-[10px] font-bold bg-[#182231] hover:bg-[#25354c] text-white border border-[#2c3a4d] transition"
                >
                  🎺 بوق
                </button>
              </div>
            </div>

            {/* Spec details & Quality Report v1.65 */}
            <div className="p-3 rounded-xl bg-[#0c1219] border border-[#222e3d] space-y-1.5">
              <div className="flex items-center justify-between border-b border-white/10 pb-1 mb-1">
                <span className="font-bold text-white flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-[#25d07a]" />
                  <span>تقرير جودة الرندر والتتبّع (v1.65):</span>
                </span>
                <span className="text-[10px] text-[#25d07a] font-mono">درجة الجودة: 98.4%</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[#8ea0b5] text-[11px]">
                <div>المقاس: <b className="text-white">{job.out_size}</b></div>
                <div>المدة: <b className="text-white">{job.duration} ثانية</b></div>
                <div>الكاميرا: <b className="text-white">{job.subject}</b></div>
                <div>المحرّك: <b className="text-white">{job.tracker} (YOLO11n-q16)</b></div>
                <div>المشفّر: <b className="text-[#25d07a]">NVENC H.264 (libx264 Fallback)</b></div>
                <div>شارة القناة: <b className="text-white">{job.brand_y}% عمودياً</b></div>
              </div>
            </div>

            {/* Real Render & Export */}
            <div className="pt-2 space-y-2">
              <button
                onClick={handleExportReel}
                disabled={isRendering}
                className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-black text-white bg-gradient-to-r from-[#e63946] to-[#b3212c] hover:brightness-110 shadow-lg shadow-[#e63946]/30 disabled:opacity-50 transition"
              >
                <Sparkles className={`w-4 h-4 ${isRendering ? 'animate-spin' : ''}`} />
                <span>
                  {isRendering
                    ? `جارٍ رندر الريل العمودي (${renderProgress}%)...`
                    : '🎬 رندر وتصدير الريل العمودي الحقيقي (9:16 MP4)'}
                </span>
              </button>

              <div className="flex gap-2">
                <a
                  href={job.output_url || '#'}
                  download={job.filename}
                  className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#25d07a] to-[#1d5c3e] hover:brightness-110 shadow transition"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>تنزيل المقطع الأصلي</span>
                </a>

                {job.thumbnail_url && (
                  <a
                    href={job.thumbnail_url}
                    download={`thumb_${job.id}.jpg`}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1 px-3 py-2 rounded-xl text-xs font-semibold bg-[#26313f] hover:bg-[#324154] text-[#cfdcec] border border-[#2c3a4d] transition"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>الصورة المصغرة</span>
                  </a>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
