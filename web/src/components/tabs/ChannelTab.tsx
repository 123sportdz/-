import React, { useState } from 'react';
import { Send, RefreshCw, Play, ArrowLeft, Eye, Clock, Film } from 'lucide-react';
import { ChannelPost } from '../../types';

interface ChannelTabProps {
  channelHandle: string;
  onConvertPostToReel: (post: ChannelPost) => void;
  onToast: (msg: string, type?: 'ok' | 'err') => void;
}

const SAMPLE_POSTS: ChannelPost[] = [
  {
    id: 'post-1',
    postId: 2984,
    title: 'هدف خرافي في اللحظات الأخيرة ⚽🔥',
    text: 'شاهد تسديدة رياض محرز العالمية التي أشعلت الملعب في الوقت بدل الضائع! دقة وقوة استثنائية.',
    date: 'منذ ساعتين',
    duration: '0:34',
    views: '42.5K',
    videoUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4',
    thumbUrl: 'https://images.unsplash.com/photo-1574629810360-7efbbe195018?w=720&auto=format&fit=crop&q=80',
  },
  {
    id: 'post-2',
    postId: 2982,
    title: 'إنقاذ الموسم على خط المرمى 🧤',
    text: 'حارس المرمى يرتقي ببراعة ويمنع كرة مستحيلة كادت أن تسكن الشباك. تصدي للتاريخ!',
    date: 'منذ 5 ساعات',
    duration: '0:28',
    views: '28.1K',
    videoUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4',
    thumbUrl: 'https://images.unsplash.com/photo-1518091043644-c1d4457512c6?w=720&auto=format&fit=crop&q=80',
  },
  {
    id: 'post-3',
    postId: 2980,
    title: 'مراوغة ميسي الساحرة وتمريرة الحسم ⚡',
    text: 'تجاوز مدافعين في خطوة واحدة وقدم تمريرة حاسمة صنعت الفارق تماماً. سحر لا ينتهي.',
    date: 'أمس',
    duration: '0:42',
    views: '95.3K',
    videoUrl: 'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyBlazes.mp4',
    thumbUrl: 'https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=720&auto=format&fit=crop&q=80',
  },
];

export const ChannelTab: React.FC<ChannelTabProps> = ({
  channelHandle,
  onConvertPostToReel,
  onToast,
}) => {
  const [handle, setHandle] = useState<string>(channelHandle || '@OffsideOffside1');
  const [limit, setLimit] = useState<number>(6);
  const [loading, setLoading] = useState<boolean>(false);
  const [posts, setPosts] = useState<ChannelPost[]>(SAMPLE_POSTS);

  const fetchPosts = () => {
    setLoading(true);
    onToast(`جارٍ الاتصال بقناة تيليجرام ${handle}...`, 'ok');
    setTimeout(() => {
      setLoading(false);
      onToast(`تم جلب ${posts.length} مقاطع فيديو كروية من القناة بنجاح`, 'ok');
    }, 1200);
  };

  return (
    <div className="bg-[#131a23] border border-[#222e3d] rounded-2xl p-6 shadow-xl max-w-4xl mx-auto">
      <h2 className="text-base font-bold text-[#cfdcec] flex items-center gap-2 mb-2">
        <Send className="w-5 h-5 text-[#36d1dc]" />
        <span>اسحب المقاطع من قناة تيليجرام</span>
      </h2>
      <p className="text-xs text-[#8ea0b5] mb-5 leading-relaxed">
        أدخل معرّف القناة العامة لتيليجرام (بدون الحاجة لبوت في القنوات العامة). يجلب النظام المقاطع الرياضية مباشرة ويسمح بتحويلها إلى ريلز عمودية بضغطة زر.
      </p>

      {/* Inputs */}
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_120px_auto] gap-3 mb-6 items-end">
        <div>
          <label className="block text-xs font-semibold text-[#8ea0b5] mb-1">معرّف القناة العامة</label>
          <input
            type="text"
            value={handle}
            onChange={e => setHandle(e.target.value)}
            placeholder="@OffsideOffside1"
            className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-xs text-white"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-[#8ea0b5] mb-1">عدد المقاطع</label>
          <input
            type="number"
            min={1}
            max={20}
            value={limit}
            onChange={e => setLimit(Number(e.target.value))}
            className="w-full bg-[#0c1219] border border-[#2c3a4d] rounded-xl p-2.5 text-xs text-white text-center"
          />
        </div>

        <button
          onClick={fetchPosts}
          disabled={loading}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-[#2f6fe0] to-[#1e4ba8] hover:brightness-110 disabled:opacity-50 transition"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          <span>{loading ? 'جارٍ السحب...' : '🔄 اجلب آخر المقاطع'}</span>
        </button>
      </div>

      {/* Posts List */}
      <div className="space-y-4">
        {posts.map(post => (
          <div
            key={post.id}
            className="bg-[#182231] border border-[#222e3d] hover:border-[#35475d] rounded-2xl p-4 transition grid grid-cols-1 sm:grid-cols-[140px_1fr_auto] gap-4 items-center"
          >
            {/* Thumbnail */}
            <div className="relative aspect-video rounded-xl overflow-hidden bg-[#090e14] border border-[#222e3d] group">
              <img src={post.thumbUrl} alt={post.title} className="w-full h-full object-cover" />
              <div className="absolute bottom-1 right-1 bg-black/80 px-1.5 py-0.5 rounded text-[10px] text-white font-mono">
                {post.duration}
              </div>
            </div>

            {/* Content */}
            <div>
              <h3 className="text-sm font-bold text-white mb-1">{post.title}</h3>
              <p className="text-xs text-[#aab8ca] line-clamp-2 mb-2 leading-relaxed">{post.text}</p>
              <div className="flex items-center gap-3 text-[11px] text-[#8ea0b5]">
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {post.date}
                </span>
                <span className="flex items-center gap-1">
                  <Eye className="w-3 h-3" />
                  {post.views} مشاهدة
                </span>
                <span className="font-mono text-[#36d1dc]">#{post.postId}</span>
              </div>
            </div>

            {/* Action */}
            <div>
              <button
                onClick={() => onConvertPostToReel(post)}
                className="w-full sm:w-auto flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl text-xs font-black text-white bg-gradient-to-r from-[#e63946] to-[#b3212c] hover:brightness-110 shadow-lg shadow-[#e63946]/20 transition"
              >
                <Film className="w-4 h-4" />
                <span>حوّل إلى ريل</span>
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
