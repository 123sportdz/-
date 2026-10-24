import { VoiceSettings } from '../types';

let audioContext: AudioContext | null = null;
let crowdSourceNode: AudioBufferSourceNode | null = null;

export const voiceSynth = {
  getSampleCommentary(style: VoiceSettings['commentary_style'], customScript?: string): string {
    if (customScript && customScript.trim()) {
      return customScript.trim();
    }
    switch (style) {
      case 'algerian':
        return 'يا سلاااام على هذي اللقطة! شوف التسديدة المباغتة كيفاش سكنت الشبكة يا خويا! جنون وفرحة في كل مكان!';
      case 'analyst':
        return 'قراءة تكتيكية ممتازة للمساحة خلف المدافعين؛ التمركز والتحرك بدون كرة هما مفتاح هذا الهدف المحقق.';
      case 'cinematic':
        return 'في الثواني الأخيرة... حبست الأنفاس، وارتفعت الهتافات، وصنع الأبطال لحظة ستخلد في الذاكرة.';
      case 'calm':
        return 'نهاية الهجمة بتسديدة دقيقة في الزاوية البعيدة، ليضيف الفريق هدف التقدم بأريحية تامة.';
      case 'broadcast':
      default:
        return 'يا الله على القوة والإثارة! انطلاقة سريعة، مراوغة ذكية، وقذيفة لا تصد ولا ترد في شباك المرمى!';
    }
  },

  async playPreview(settings: VoiceSettings, onEnd?: () => void): Promise<void> {
    const text = this.getSampleCommentary(settings.commentary_style, settings.commentary_script);

    // Stop any existing speech
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    try {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) {
        if (!audioContext || audioContext.state === 'closed') {
          audioContext = new AudioCtx();
        }
        if (audioContext.state === 'suspended') {
          await audioContext.resume();
        }

        // Simulate crowd cheering background with ducking
        this.playCrowdAmbience(audioContext, settings.voice_duck);
      }
    } catch {
      // AudioContext might be blocked until user interaction
    }

    if (!('speechSynthesis' in window)) {
      if (onEnd) onEnd();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'ar-SA';

    // Map rate (-20 to +50 -> 0.8 to 1.5)
    utterance.rate = Math.max(0.7, Math.min(1.6, 1 + settings.voice_rate / 100));

    // Map pitch (-12 to +12 -> 0.7 to 1.4)
    utterance.pitch = Math.max(0.6, Math.min(1.5, 1 + settings.voice_pitch / 24));

    // Look for Arabic voice
    const voices = window.speechSynthesis.getVoices();
    const arabicVoice = voices.find(v => v.lang.startsWith('ar')) || null;
    if (arabicVoice) {
      utterance.voice = arabicVoice;
    }

    utterance.onend = () => {
      this.stopCrowdAmbience();
      if (onEnd) onEnd();
    };

    utterance.onerror = () => {
      this.stopCrowdAmbience();
      if (onEnd) onEnd();
    };

    window.speechSynthesis.speak(utterance);
  },

  playCrowdAmbience(ctx: AudioContext, duckLevel: number) {
    try {
      this.stopCrowdAmbience();

      const sampleRate = ctx.sampleRate;
      const buffer = ctx.createBuffer(1, sampleRate * 4, sampleRate);
      const data = buffer.getChannelData(0);

      // Low-frequency rumble simulating distant roaring stadium
      let last = 0;
      for (let i = 0; i < buffer.length; i++) {
        const white = Math.random() * 2 - 1;
        last = last * 0.95 + white * 0.05;
        data[i] = last * 0.15;
      }

      crowdSourceNode = ctx.createBufferSource();
      crowdSourceNode.buffer = buffer;
      crowdSourceNode.loop = true;

      const gainNode = ctx.createGain();
      gainNode.gain.value = Math.max(0.02, Math.min(0.2, duckLevel * 0.25));

      crowdSourceNode.connect(gainNode);
      gainNode.connect(ctx.destination);
      crowdSourceNode.start();
    } catch {
      // Ignore audio synthesis errors
    }
  },

  stopCrowdAmbience() {
    try {
      if (crowdSourceNode) {
        crowdSourceNode.stop();
        crowdSourceNode.disconnect();
        crowdSourceNode = null;
      }
    } catch {
      crowdSourceNode = null;
    }
  },

  stop() {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    this.stopCrowdAmbience();
  },
};
