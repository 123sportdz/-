import { GoogleGenAI } from '@google/genai';
import { storage } from './storage';

export const SCRIPT_WORD_LIMITS: Record<string, number> = {
  short: 22,
  medium: 40,
  long: 65,
};

export const CONTENT_MODES: Record<string, { label: string; icon: string; promptDesc: string }> = {
  script: {
    label: 'تعليق صوتي',
    icon: '▶',
    promptDesc: 'تعليق صوتي حماسي ومضبوط بدقة للريل العمودي، مع احترام صارم لعدد الكلمات المحدد.',
  },
  poem: {
    label: 'تعليق شعري',
    icon: '❋',
    promptDesc: 'أبيات شعرية رياضية موزونة وجميلة تتغنى بروعة الهدف واللقطة الكروية.',
  },
  title: {
    label: 'عناوين قصيرة',
    icon: '↗',
    promptDesc: 'قائمة من 4-6 عناوين خاطفة ومحفزة للفضول مناسبة لمنصات Reels و Shorts.',
  },
  hook: {
    label: 'افتتاحية جذابة',
    icon: '✦',
    promptDesc: 'أول 3 ثوانٍ في الفيديو تجذب عين وأذن المشاهد وتمنع التمرير.',
  },
  caption: {
    label: 'كابشن',
    icon: '⌁',
    promptDesc: 'نص كابشن موجز مع إيموجي رياضي وسؤال تفاعلي للمشجعين.',
  },
  description: {
    label: 'وصف ووسوم',
    icon: '▤',
    promptDesc: 'وصف متكامل يتضمن تفاصيل اللقطة مع مجموعة وسوم #هاشتاق متوافقة مع الخوارزمية.',
  },
  recap: {
    label: 'ملخص اللقطة',
    icon: '◉',
    promptDesc: 'تلخيص صحفي مكثف للحدث وأهميته في مجريات المباراة.',
  },
  ideas: {
    label: 'أفكار للريل',
    icon: '✧',
    promptDesc: '3 أفكار إبداعية للمونتاج (زوايا، موسيقى مقترحة، ومؤثرات بصرية).',
  },
  rewrite: {
    label: 'تنقيح نص رياضي',
    icon: '⤾',
    promptDesc: 'إعادة صياغة النص الأصلي بلغة رياضية أكثر احترافية وجاذبية.',
  },
  social: {
    label: 'منشور للمنصة',
    icon: '◎',
    promptDesc: 'منشور اجتماعي جاهز للنشر على قنوات تيليجرام وتويتر/X.',
  },
  article: {
    label: 'وصف موسّع',
    icon: '▣',
    promptDesc: 'فقرة تحليلية موسعة تصف اللقطة من حيث التكنيك وتأثيرها المعنوي.',
  },
  story: {
    label: 'سرد تسلسل الحركة',
    icon: '⌁',
    promptDesc: 'سرد دقيق للحركة خطوة بخطوة من استلام الكرة حتى معانقتها للشباك.',
  },
  custom: {
    label: 'نص رياضي مخصص',
    icon: '✎',
    promptDesc: 'كتابة رياضية مخصصة حسب التوجيه الإضافي المدخل.',
  },
};

export const geminiService = {
  async generateContent(params: {
    mode: string;
    topic: string;
    source: string;
    platform: string;
    language: string;
    length: 'short' | 'medium' | 'long';
    tone: string;
    audience: string;
    instructions: string;
    jobTitle?: string;
  }): Promise<{ text: string; title: string }> {
    const settings = storage.getSettings();
    const apiKey = String(settings.gemini_api_key || '').trim();
    const model = settings.gemini_model || 'gemini-2.5-flash';

    const wordCap = params.mode === 'script' ? SCRIPT_WORD_LIMITS[params.length] || 22 : undefined;

    // If API key is available, call Gemini API
    if (apiKey) {
      try {
        const ai = new GoogleGenAI({ apiKey });
        const systemPrompt = `أنت محرر محتوى رياضي متخصص في كرة القدم لريلز "الحدث" (elhadath-reels).
مهمتك: توليد نصوص باللغة الرياضية المتقنة والممتعة حصراً لكرة القدم.
الوضع المطلوب: ${CONTENT_MODES[params.mode]?.label || params.mode}
المنصة: ${params.platform}
اللغة: ${params.language === 'dz' ? 'الدارجة الجزائرية العفوية' : params.language === 'fr' ? 'الفرنسية' : params.language === 'en' ? 'الإنجليزية' : 'العربية الفصحى الرياضية'}
النبرة: ${params.tone}
الجمهور المستهدف: ${params.audience}
${wordCap ? `تنبيه حاسم: هذا تعليق صوتي ريل، يجب ألا يتجاوز إطلاقاً ${wordCap} كلمة!` : ''}
${params.instructions ? `توجيه إضافي: ${params.instructions}` : ''}
الموضوع: ${params.topic || params.jobTitle || 'لقطة كروية مميزة'}
تفاصيل مؤكدة: ${params.source || 'هدف استثنائي في مباراة قمة'}`;

        const response = await ai.models.generateContent({
          model,
          contents: systemPrompt,
        });

        let generated = response.text || '';
        // If script, enforce post-generation word cap strictly per AGENTS.md
        if (wordCap) {
          const words = generated.trim().split(/\s+/);
          if (words.length > wordCap) {
            generated = words.slice(0, wordCap).join(' ') + '...';
          }
        }

        const draftTitle = params.topic ? `${CONTENT_MODES[params.mode]?.label || 'نص'} — ${params.topic.slice(0, 40)}` : `مسودة ريل ${new Date().toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' })}`;

        return { text: generated, title: draftTitle };
      } catch (err) {
        console.warn('Gemini call failed or rate limited, falling back to smart sports template generator', err);
      }
    }

    // High quality offline fallback sports generator conforming to the rule
    return this.generateSmartFallback(params, wordCap);
  },

  generateSmartFallback(params: {
    mode: string;
    topic: string;
    source: string;
    platform: string;
    language: string;
    length: 'short' | 'medium' | 'long';
    tone: string;
    audience: string;
    instructions: string;
    jobTitle?: string;
  }, wordCap?: number): { text: string; title: string } {
    const subject = params.topic || params.jobTitle || 'لقطة المباراة التاريخية';
    const sourceInfo = params.source || 'تسديدة خرافية ولمسة حاسمة قلبت الموازين';
    let outputText = '';

    if (params.mode === 'script') {
      if (params.language === 'dz') {
        outputText = `شوف التسديدة الخيالية هذي! في آخر الدقائق حطها في الزاوية التسعين وفجر فرحة الجماهير، لقطة ولا أروع!`;
      } else {
        outputText = `يا إلهي على هذا الهدف التاريخي! تسديدة صاروخية تسكن المقص الأيمن للمرمى، وفرحة جنونية تهز أرجاء الملعب!`;
      }
      if (wordCap) {
        const words = outputText.trim().split(/\s+/);
        if (words.length > wordCap) {
          outputText = words.slice(0, wordCap).join(' ') + '...';
        }
      }
    } else if (params.mode === 'poem') {
      outputText = `رسمتَ الفن في المستطيل الأخضرِ ** وسرتَ بنور الإبداع لا تتعثرِ\nقذيفةٌ لا تصدّ بالعين ترى ** كأنها شهابٌ في الملاعب يظفرِ ⚽🔥`;
    } else if (params.mode === 'title') {
      outputText = `1. هدف الموسم في الزاوية المستحيلة! 🚀🔥\n2. هل هذه أفضل لقطة في الجولة؟ 🤯⚽\n3. عندما يتحول اللاعب إلى ساحر في الملعب! ✨\n4. تصويبة دمرت كل حسابات الحارس! 🧤🚫`;
    } else if (params.mode === 'hook') {
      outputText = `انتظر حتى ترى أين ذهبت هذه الكرة في الثانية الأخيرة... مستحيل ما فعله! 👀👇`;
    } else if (params.mode === 'caption') {
      outputText = `من زاوية مستحيلة لا يتخيلها أحد... فعلها مجدداً! ⚽🇩🇿\n\nما هو تقييمك لهذا الهدف من 10؟ شاركنا في التعليقات! 👇🔥`;
    } else if (params.mode === 'description') {
      outputText = `ملخص وأبرز لحظات اللقطة الكروية الأروع لهذا الأسبوع.\nتفاصيل: ${sourceInfo}\n\n#ريلز_رياضية #الحدث #دوري #كرة_قدم #أهداف_عالمية #shorts #football`;
    } else if (params.mode === 'recap') {
      outputText = `في لقطة حبست الأنفاس، نجح الفريق في كسر التعادل عبر عمل جماعي انتهى بإنهاء متقن داخل الشباك، ليمنح جماهيره ثلاث نقاط غالية.`;
    } else if (params.mode === 'ideas') {
      outputText = `1. حركة بطيئة (Slow-Mo) من زاوية الشبكة مع صوت ضرب الكرة.\n2. إبراز نظرة الحارس العاجز قبل دخول الكرة مباشرة.\n3. إضافة مقياس سرعة الكرة وتأثير الوميض عند لحظة التسديد.`;
    } else {
      outputText = `لحظة استثنائية تجسد روح كرة القدم وجمال اللعبة. ${subject} — ${sourceInfo}.`;
    }

    const title = `${CONTENT_MODES[params.mode]?.label || 'نص'} — ${subject.slice(0, 36)}`;
    return { text: outputText, title };
  },
};
