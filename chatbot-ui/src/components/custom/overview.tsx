import { motion } from 'framer-motion';
import { MessageCircle, BotIcon } from 'lucide-react';

export const Overview = () => {
  return (
    <motion.div
      key="overview"
      className="max-w-2xl mx-auto mt-20 px-6 text-center"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ delay: 0.75 }}
    >
      <div className="bg-zinc-900 rounded-2xl py-10 px-6 flex flex-col items-center gap-6 shadow-lg">
        <div className="flex items-center gap-3 text-white">
          <BotIcon size={40} />
          <span className="text-2xl font-semibold">+</span>
          <MessageCircle size={40} />
        </div>

        <h1 className="text-2xl font-bold text-white">Welcome to <span className="text-blue-400">DBplus</span></h1>

        <p className="text-base text-gray-300 leading-relaxed">
          <strong className="text-white">
            Để hỗ trợ bạn tốt hơn, vui lòng cung cấp cho mình
          </strong>
        </p>
        <p className="text-base text-gray-300 leading-relaxed">
          <strong className="text-white">
            thông tin về phòng ban của bạn nhé.
          </strong>
        </p>
      </div>
    </motion.div>
  );
};

