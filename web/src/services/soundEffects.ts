// Web Audio API based stadium and broadcast sound effect engine
// 100% client-side, zero external asset latency, instant response

let audioCtx: AudioContext | null = null;

const getAudioContext = (): AudioContext => {
  if (!audioCtx || audioCtx.state === 'closed') {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    audioCtx = new AudioContextClass();
  }
  if (audioCtx.state === 'suspended') {
    audioCtx.resume();
  }
  return audioCtx;
};

export const soundEffects = {
  // 📢 Referee Whistle (صفارة الحكم)
  playWhistle() {
    try {
      const ctx = getAudioContext();
      const now = ctx.currentTime;

      // Two dual-frequency sine tones for realistic pea whistle fluttering
      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      const gain = ctx.createGain();

      osc1.type = 'sine';
      osc2.type = 'sine';
      osc1.frequency.setValueAtTime(2850, now);
      osc2.frequency.setValueAtTime(3100, now);

      // Tremolo / flutter (simulate whistle ball)
      const lfo = ctx.createOscillator();
      const lfoGain = ctx.createGain();
      lfo.frequency.setValueAtTime(28, now);
      lfoGain.gain.setValueAtTime(150, now);
      lfo.connect(osc1.frequency);
      lfo.connect(osc2.frequency);

      // Envelope
      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.35, now + 0.05);
      gain.gain.setValueAtTime(0.35, now + 0.28);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);

      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(ctx.destination);

      lfo.start(now);
      osc1.start(now);
      osc2.start(now);

      lfo.stop(now + 0.5);
      osc1.stop(now + 0.5);
      osc2.stop(now + 0.5);
    } catch (e) {
      console.warn('Whistle audio error', e);
    }
  },

  // 🏟️ Stadium Crowd Roar / Goal Cheer (هتاف الجماهير والملعب)
  playCrowdRoar(durationSeconds = 2.5) {
    try {
      const ctx = getAudioContext();
      const now = ctx.currentTime;
      const bufferSize = ctx.sampleRate * durationSeconds;
      const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const data = buffer.getChannelData(0);

      // Filtered pink/brown noise
      let b0 = 0, b1 = 0, b2 = 0;
      for (let i = 0; i < bufferSize; i++) {
        const white = Math.random() * 2 - 1;
        b0 = 0.99 * b0 + white * 0.05;
        b1 = 0.95 * b1 + white * 0.1;
        b2 = 0.85 * b2 + white * 0.2;
        data[i] = (b0 + b1 + b2) * 0.4;
      }

      const noise = ctx.createBufferSource();
      noise.buffer = buffer;

      const filter = ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.frequency.setValueAtTime(600, now);
      filter.frequency.exponentialRampToValueAtTime(1200, now + 0.8);
      filter.Q.setValueAtTime(1.5, now);

      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.01, now);
      gain.gain.linearRampToValueAtTime(0.4, now + 0.6);
      gain.gain.exponentialRampToValueAtTime(0.001, now + durationSeconds);

      noise.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);

      noise.start(now);
      noise.stop(now + durationSeconds);
    } catch (e) {
      console.warn('Crowd roar audio error', e);
    }
  },

  // 💥 Goal Impact / Ball Post Hit (صدمة الكرة بالعارضة أو الشباك)
  playBallImpact() {
    try {
      const ctx = getAudioContext();
      const now = ctx.currentTime;

      // Heavy low thud
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'triangle';
      osc.frequency.setValueAtTime(160, now);
      osc.frequency.exponentialRampToValueAtTime(45, now + 0.18);

      gain.gain.setValueAtTime(0.6, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(now);
      osc.stop(now + 0.28);
    } catch (e) {
      console.warn('Ball impact audio error', e);
    }
  },

  // 🎬 Cinematic Whoosh / Rise (انتقال سينمائي للحظات الحاسمة)
  playCinematicWhoosh() {
    try {
      const ctx = getAudioContext();
      const now = ctx.currentTime;
      const duration = 0.8;

      const bufferSize = ctx.sampleRate * duration;
      const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) {
        data[i] = Math.random() * 2 - 1;
      }

      const noise = ctx.createBufferSource();
      noise.buffer = buffer;

      const filter = ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.frequency.setValueAtTime(200, now);
      filter.frequency.exponentialRampToValueAtTime(3200, now + duration * 0.7);
      filter.Q.setValueAtTime(3, now);

      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.01, now);
      gain.gain.linearRampToValueAtTime(0.3, now + duration * 0.6);
      gain.gain.exponentialRampToValueAtTime(0.001, now + duration);

      noise.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);

      noise.start(now);
      noise.stop(now + duration);
    } catch (e) {
      console.warn('Cinematic whoosh audio error', e);
    }
  },

  // 🎺 Stadium Horn / Celebration (بوق التشجيع الاحتفالي)
  playStadiumHorn() {
    try {
      const ctx = getAudioContext();
      const now = ctx.currentTime;
      const notes = [440, 554.37, 659.25]; // A major chord

      notes.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(freq, now);

        gain.gain.setValueAtTime(0.001, now);
        gain.gain.linearRampToValueAtTime(0.12, now + 0.05);
        gain.gain.setValueAtTime(0.12, now + 0.45);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start(now);
        osc.stop(now + 0.65);
      });
    } catch (e) {
      console.warn('Horn audio error', e);
    }
  },
};
