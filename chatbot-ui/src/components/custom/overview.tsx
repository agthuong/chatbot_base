import { motion } from 'framer-motion';
import { MessageCircle, BotIcon, Briefcase } from 'lucide-react';

interface OverviewProps {
  modelType: "original" | "gemini";
}

export const Overview = ({ modelType }: OverviewProps) => {
  const isGemini = modelType === "gemini";

  return (
    <motion.div
      key="overview"
      className="max-w-2xl mx-auto mt-20 px-6 text-center"
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ delay: 0.75 }}
    >
      <div className="bg-card rounded-2xl py-10 px-6 flex flex-col items-center gap-6 shadow-lg text-card-foreground">
        <div className="flex items-center gap-3">
          {isGemini ? <Briefcase size={40} /> : <BotIcon size={40} />}
          <span className="text-2xl font-semibold">+</span>
          <MessageCircle size={40} />
        </div>

        <h1 className="text-2xl font-bold">Welcome to <span className="text-blue-500 dark:text-blue-400">DBplus</span></h1>

        {isGemini ? (
          <p className="text-base leading-relaxed">
            <strong>
              Mình là trợ lý Sale AI của DBplus. Mình có thể giúp gì cho bạn?
            </strong>
          </p>
        ) : (
          <>
            <p className="text-base leading-relaxed">
              <strong>
                Để hỗ trợ bạn tốt hơn, vui lòng cung cấp cho mình
              </strong>
            </p>
            <p className="text-base leading-relaxed">
              <strong>
                thông tin về phòng ban của bạn nhé.
              </strong>
            </p>
          </>
        )}
      </div>
    </motion.div>
  );
};

