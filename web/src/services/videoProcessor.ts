import { ScoutCandidate } from '../types';

export const videoProcessor = {
  /**
   * Extract real metadata and frame snapshot from an uploaded video file or URL
   */
  async extractVideoMetadata(
    fileOrUrl: File | string
  ): Promise<{ duration: number; width: number; height: number; thumbnail: string; thumbnailUrl: string; objectUrl: string }> {
    return new Promise((resolve, reject) => {
      const video = document.createElement('video');
      video.crossOrigin = 'anonymous';
      video.muted = true;
      video.playsInline = true;

      const isLocalFile = typeof fileOrUrl !== 'string';
      const objectUrl = isLocalFile ? URL.createObjectURL(fileOrUrl) : fileOrUrl;
      let metadataTimeout: number | undefined;
      let seekTimeout: number | undefined;
      let settled = false;

      const cleanup = () => {
        if (metadataTimeout !== undefined) window.clearTimeout(metadataTimeout);
        if (seekTimeout !== undefined) window.clearTimeout(seekTimeout);
        video.onloadedmetadata = null;
        video.onseeked = null;
        video.onerror = null;
        video.pause();
        video.removeAttribute('src');
        video.load();
      };

      const fail = (message: string) => {
        if (settled) return;
        settled = true;
        cleanup();
        if (isLocalFile) URL.revokeObjectURL(objectUrl);
        reject(new Error(message));
      };

      const finish = (duration: number, width: number, height: number, thumbnail: string) => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve({ duration, width, height, thumbnail, thumbnailUrl: thumbnail, objectUrl });
      };

      metadataTimeout = window.setTimeout(() => fail('انتهت مهلة قراءة بيانات الفيديو.'), 15000);
      video.onerror = () => fail('تعذّر فتح الفيديو في المتصفح.');
      video.onloadedmetadata = () => {
        const duration = video.duration;
        const width = video.videoWidth;
        const height = video.videoHeight;
        if (!Number.isFinite(duration) || duration <= 0 || width <= 0 || height <= 0) {
          fail('بيانات الفيديو أو أبعاده غير صالحة.');
          return;
        }

        const seekTime = Math.min(duration * 0.15, 2.0);
        seekTimeout = window.setTimeout(() => finish(duration, width, height, ''), 5000);
        video.onseeked = () => {
          let thumbnail = '';
          try {
            const canvas = document.createElement('canvas');
            canvas.width = 480;
            canvas.height = 270;
            const context = canvas.getContext('2d');
            if (context) {
              context.drawImage(video, 0, 0, canvas.width, canvas.height);
              thumbnail = canvas.toDataURL('image/jpeg', 0.85);
            }
          } catch {
            thumbnail = '';
          }
          finish(duration, width, height, thumbnail);
        };

        try {
          video.currentTime = seekTime;
        } catch {
          finish(duration, width, height, '');
        }
      };
      video.src = objectUrl;
    });
  },

  async analyzeScoutFrames(
    fileOrUrl: File | string,
    candidateCount: number,
    onProgress: (progress: number, stage: string) => void
  ): Promise<ScoutCandidate[]> {
    const meta = await this.extractVideoMetadata(fileOrUrl);
    const sourceDuration = Number(meta.duration);
    if (!Number.isFinite(sourceDuration) || sourceDuration < 3) {
      if (typeof fileOrUrl !== 'string') URL.revokeObjectURL(meta.objectUrl);
      throw new Error('يجب أن تبلغ مدة الفيديو 3 ثوانٍ على الأقل.');
    }

    const video = document.createElement('video');
    video.crossOrigin = 'anonymous';
    video.muted = true;
    video.playsInline = true;
    video.preload = 'metadata';
    video.src = meta.objectUrl;

    try {
      onProgress(15, 'فتح الفيديو محلياً لاستخراج إطارات معاينة فقط...');
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('انتهت مهلة فتح الفيديو.')), 10000);
        video.onloadedmetadata = () => {
          window.clearTimeout(timeout);
          resolve();
        };
        video.onerror = () => {
          window.clearTimeout(timeout);
          reject(new Error('تعذّر فتح الفيديو في المتصفح.'));
        };
      });

      const requestedCount = Math.max(1, Math.min(10, Math.trunc(candidateCount) || 1));
      const count = Math.min(requestedCount, Math.max(1, Math.floor(sourceDuration / 3)));
      const windowDuration = Math.min(18, sourceDuration, Math.max(3, sourceDuration / (count + 1) * 0.8));
      const canvas = document.createElement('canvas');
      canvas.width = 480;
      canvas.height = 270;
      const context = canvas.getContext('2d');
      const candidates: ScoutCandidate[] = [];

      for (let i = 0; i < count; i++) {
        const sampleTime = sourceDuration * (i + 1) / (count + 1);
        const start = Math.max(0, Math.min(sourceDuration - windowDuration, sampleTime - windowDuration / 2));
        const end = start + windowDuration;
        onProgress(20 + Math.round((i / count) * 70), `استخراج إطار محلي ${i + 1} من ${count}؛ لا يوجد كشف كروي أو تقييم للمشهد.`);

        await new Promise<void>((resolve, reject) => {
          const timeout = window.setTimeout(() => reject(new Error('انتهت مهلة استخراج إطار المعاينة.')), 5000);
          video.onseeked = () => {
            window.clearTimeout(timeout);
            resolve();
          };
          video.onerror = () => {
            window.clearTimeout(timeout);
            reject(new Error('تعذّر قراءة إطار المعاينة.'));
          };
          video.currentTime = sampleTime;
        });

        let thumb = '';
        if (context) {
          try {
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            thumb = canvas.toDataURL('image/jpeg', 0.85);
          } catch {
            thumb = '';
          }
        }

        candidates.push({
          id: `sample-${Date.now()}-${i}`,
          index: i,
          dur: Number((end - start).toFixed(1)),
          start: Number(start.toFixed(1)),
          end: Number(end.toFixed(1)),
          sample_t: Number(sampleTime.toFixed(1)),
          source_duration: sourceDuration,
          thumb,
        });
      }

      onProgress(100, 'اكتمل استخراج إطارات المعاينة المحلية؛ لم يُحلّل الحدث الرياضي.');
      return candidates;
    } finally {
      video.pause();
      video.removeAttribute('src');
      video.load();
      if (typeof fileOrUrl !== 'string') URL.revokeObjectURL(meta.objectUrl);
    }
  },

  /**
   * Real Canvas-based 9:16 Video Renderer & Exporter
   * Takes a video, crops horizontally to 9:16, draws brand logo and captions, and returns a recorded video Blob.
   */
  async renderVerticalReel(params: {
    videoElement: HTMLVideoElement;
    startTime: number;
    endTime: number;
    logoUrl?: string;
    logoScale?: number;
    logoOpacity?: number;
    logoPosition?: string;
    brandName?: string;
    brandY?: number;
    commentaryText?: string;
    onProgress?: (progress: number) => void;
  }): Promise<{ blob: Blob; downloadUrl: string }> {
    const { videoElement, startTime, endTime, logoUrl, brandName, brandY, commentaryText, onProgress } = params;

    const canvas = document.createElement('canvas');
    canvas.width = 720;
    canvas.height = 1280; // 9:16 standard vertical HD
    const ctx = canvas.getContext('2d')!;

    // Preload logo image if provided
    let logoImg: HTMLImageElement | null = null;
    if (logoUrl) {
      logoImg = new Image();
      logoImg.crossOrigin = 'anonymous';
      logoImg.src = logoUrl;
      await new Promise(r => {
        logoImg!.onload = r;
        logoImg!.onerror = r;
      });
    }

    const stream = canvas.captureStream(30);

    // Prefer video/webm;codecs=vp9 or video/mp4
    let mimeType = 'video/webm;codecs=vp9';
    if (!MediaRecorder.isTypeSupported(mimeType)) {
      mimeType = 'video/webm';
    }
    if (MediaRecorder.isTypeSupported('video/mp4')) {
      mimeType = 'video/mp4';
    }

    const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 3_500_000 });
    const chunks: Blob[] = [];

    recorder.ondataavailable = e => {
      if (e.data && e.data.size > 0) {
        chunks.push(e.data);
      }
    };

    videoElement.currentTime = startTime;
    await new Promise(r => {
      videoElement.onseeked = () => r(true);
      setTimeout(r, 600);
    });

    recorder.start(100);
    videoElement.muted = true;
    await videoElement.play().catch(() => {});

    const totalDuration = Math.max(1, endTime - startTime);

    return new Promise((resolve) => {
      const renderLoop = () => {
        const current = videoElement.currentTime;

        if (current >= endTime || videoElement.paused || videoElement.ended) {
          recorder.stop();
          videoElement.pause();
          return;
        }

        const progress = Math.min(100, Math.round(((current - startTime) / totalDuration) * 100));
        if (onProgress) onProgress(progress);

        // Calculate 9:16 center crop
        const vw = videoElement.videoWidth || 1920;
        const vh = videoElement.videoHeight || 1080;
        const targetRatio = 720 / 1280;
        const currentRatio = vw / vh;

        let srcX = 0, srcY = 0, srcW = vw, srcH = vh;
        if (currentRatio > targetRatio) {
          // Crop width horizontally from center
          srcW = vh * targetRatio;
          srcX = (vw - srcW) / 2;
        } else {
          // Crop height vertically from center
          srcH = vw / targetRatio;
          srcY = (vh - srcH) / 2;
        }

        ctx.drawImage(videoElement, srcX, srcY, srcW, srcH, 0, 0, canvas.width, canvas.height);

        // Draw Channel Badge Overlay
        if (brandName) {
          ctx.save();
          const badgeY = canvas.height * ((brandY || 13) / 100);
          ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
          ctx.beginPath();
          ctx.roundRect(canvas.width - 230, badgeY, 210, 44, 22);
          ctx.fill();
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
          ctx.lineWidth = 1.5;
          ctx.stroke();

          ctx.font = 'bold 20px Cairo, sans-serif';
          ctx.fillStyle = '#ffffff';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(`⚽ ${brandName}`, canvas.width - 125, badgeY + 22);
          ctx.restore();
        }

        // Draw Brand Logo if loaded
        if (logoImg && logoImg.complete && logoImg.naturalWidth > 0) {
          ctx.save();
          ctx.globalAlpha = (params.logoOpacity || 95) / 100;
          const logoW = canvas.width * ((params.logoScale || 16) / 100) * 1.5;
          const logoH = (logoImg.naturalHeight / logoImg.naturalWidth) * logoW;
          ctx.drawImage(logoImg, canvas.width - logoW - 20, 30, logoW, logoH);
          ctx.restore();
        }

        // Draw Commentary Text Overlay
        if (commentaryText) {
          ctx.save();
          const padding = 20;
          const boxW = canvas.width - padding * 2;
          ctx.fillStyle = 'rgba(10, 16, 24, 0.85)';
          ctx.beginPath();
          ctx.roundRect(padding, canvas.height - 180, boxW, 110, 18);
          ctx.fill();
          ctx.strokeStyle = 'rgba(54, 209, 220, 0.4)';
          ctx.lineWidth = 2;
          ctx.stroke();

          ctx.font = 'bold 22px Cairo, sans-serif';
          ctx.fillStyle = '#ffffff';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText(commentaryText.slice(0, 45), canvas.width / 2, canvas.height - 125);
          ctx.restore();
        }

        requestAnimationFrame(renderLoop);
      };

      recorder.onstop = () => {
        const finalBlob = new Blob(chunks, { type: mimeType });
        const downloadUrl = URL.createObjectURL(finalBlob);
        resolve({ blob: finalBlob, downloadUrl });
      };

      requestAnimationFrame(renderLoop);
    });
  },
};
