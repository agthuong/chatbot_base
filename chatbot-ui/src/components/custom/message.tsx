import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { cx } from 'classix';
import { SparklesIcon } from './icons';
import { Markdown } from './markdown';
import { message, WebSocketAction } from "@/interfaces/interfaces"
import { MessageActions } from '@/components/custom/actions';
import { Loader2, AlertTriangle, Eye, EyeOff } from 'lucide-react';
import { Button } from "@/components/ui/button";

export const PreviewMessage = ({ message, socket, sessionId }: { message: message; socket?: WebSocket; sessionId?: string; }) => {
  // Thêm state để kiểm soát hiển thị thinking
  const [showThinking, setShowThinking] = useState(false);
  // Thêm state để theo dõi trạng thái đang tải thinking
  const [isLoadingThinking, setIsLoadingThinking] = useState(false);
  const [_thinkingError, setThinkingError] = useState<string | null>(null);
  const [currentRequestId, setCurrentRequestId] = useState<string | null>(null);

  const handleGetThinking = () => {
    // Nếu đã có thinking và không đang tải, chỉ toggle hiển thị
    if (message.thinking && !isLoadingThinking) {
      setShowThinking(!showThinking);
      return;
    }
    
    if (!message.id) return;
    
    // Đảm bảo chỉ gửi yêu cầu nếu socket đã sẵn sàng
    if (socket && socket.readyState === WebSocket.OPEN) {
      setIsLoadingThinking(true);
      
      // Tạo request_id duy nhất để nhận diện phản hồi
      const requestId = `thinking_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
      
      // Lưu request_id hiện tại để kiểm tra phản hồi
      setCurrentRequestId(requestId);
      
      // Thiết lập timeout để tránh chờ vô hạn
      const timeoutId = setTimeout(() => {
        if (isLoadingThinking) {
          setIsLoadingThinking(false);
          setThinkingError("Không nhận được phản hồi từ server sau 30 giây. Vui lòng thử lại sau.");
        }
      }, 30000); // 30 giây timeout
      
      // Định nghĩa event handler cho thinking response
      const handleThinkingResponse = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          
          // Kiểm tra xem phản hồi có đúng request_id không
          if (data.request_id === requestId) {
            // Xóa timeout vì đã nhận được phản hồi
            clearTimeout(timeoutId);
            
            // Reset state
            setIsLoadingThinking(false);
            setCurrentRequestId(null);
            
            // Xử lý phản hồi thinking
            if (data.thinking) {
              message.thinking = data.thinking;
              setShowThinking(true);
            } else if (data.error) {
              setThinkingError(data.error);
            } else {
              setThinkingError("Không nhận được nội dung phân tích");
            }
            
            // Gỡ bỏ event handler này sau khi xử lý
            socket.removeEventListener('message', handleThinkingResponse);
          }
        } catch (error) {
          console.error("Lỗi khi xử lý phản hồi thinking:", error);
          
          // Chỉ xử lý lỗi nếu chúng ta vẫn đang đợi cho request này
          if (currentRequestId === requestId) {
            clearTimeout(timeoutId);
            setIsLoadingThinking(false);
            setCurrentRequestId(null);
            setThinkingError("Lỗi khi xử lý phản hồi từ server");
            
            // Gỡ bỏ event handler này sau khi xử lý
            socket.removeEventListener('message', handleThinkingResponse);
          }
        }
      };
      
      // Đăng ký event handler
      socket.addEventListener('message', handleThinkingResponse);
      
      // Gửi yêu cầu lấy thinking
      const thinkingRequest: WebSocketAction = {
        action: "get_thinking",
        query: message.content,
        session_id: sessionId,
        request_id: requestId
      };
      
      // Gửi yêu cầu
      socket.send(JSON.stringify(thinkingRequest));
    } else {
      // Socket chưa sẵn sàng
      setThinkingError("Kết nối WebSocket không khả dụng. Vui lòng làm mới trang.");
    }
  };

  // Xử lý riêng cho tin nhắn cảnh báo
  if (message.isWarning) {
    return (
      <motion.div
        className="w-full mx-auto max-w-3xl px-4 group/message"
        initial={{ y: 5, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        data-role={message.role}
      >
        <div className="flex items-center gap-3 p-3 text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 rounded-lg">
          <AlertTriangle className="h-5 w-5" />
          <div className="flex-1">
            <Markdown>{message.content}</Markdown>
          </div>
        </div>
      </motion.div>
    );
  }

  // Xử lý cho tin nhắn thông thường
  return (
    <motion.div
      className="w-full mx-auto max-w-4xl px-4 group/message"
      initial={{ y: 5, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      data-role={message.role}
    >
      <div
        className={cx(
          'group-data-[role=user]/message:bg-zinc-700 dark:group-data-[role=user]/message:bg-muted group-data-[role=user]/message:text-white flex gap-4 group-data-[role=user]/message:px-3 w-full group-data-[role=user]/message:w-fit group-data-[role=user]/message:ml-auto group-data-[role=user]/message:max-w-2xl group-data-[role=user]/message:py-2 rounded-xl',
          'group-data-[role=assistant]/message:bg-white dark:group-data-[role=assistant]/message:bg-zinc-800 group-data-[role=assistant]/message:text-gray-800 dark:group-data-[role=assistant]/message:text-gray-200 group-data-[role=assistant]/message:px-3 group-data-[role=assistant]/message:py-2 rounded-xl'
        )}
      >
        {message.role === 'assistant' && (
          <div className="size-8 flex items-center rounded-full justify-center ring-1 shrink-0 ring-border">
            <SparklesIcon size={14} />
          </div>
        )}

        <div className="flex flex-col w-full">
          {message.role === 'assistant' && (
            <div className="mb-2 flex items-center justify-between">
              <Button 
                variant="ghost" 
                size="sm" 
                className="text-xs flex items-center gap-1 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                onClick={handleGetThinking}
                disabled={isLoadingThinking}
              >
                {isLoadingThinking ? (
                  <>
                    <Loader2 className="h-3 w-3 animate-spin mr-1" />
                    Đang phân tích...
                  </>
                ) : showThinking && message.thinking ? (
                  <>
                    <EyeOff size={14} /> Ẩn phân tích
                  </>
                ) : (
                  <>
                    <Eye size={14} /> Hiện phân tích
                  </>
                )}
              </Button>
            </div>
          )}

          {message.thinking && message.thinking.trim() !== '' && message.role === 'assistant' && showThinking && (
            <motion.div 
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-3 p-3 bg-gray-100 dark:bg-zinc-800 rounded-md border border-gray-200 dark:border-zinc-700"
            >
              <div className="text-sm text-gray-700 dark:text-gray-300">
                <div className="font-semibold mb-1">💭 Phân tích:</div>
                <Markdown>{message.thinking}</Markdown>
              </div>
            </motion.div>
          )}

          {message.content && (
            <div className="flex flex-col gap-4 text-left w-full">
              <div className={message.role === 'assistant' ? 'prose prose-sm sm:prose dark:prose-invert prose-h2:mt-4 prose-h2:mb-3 max-w-none message-content' : ''}>
                <Markdown>{message.content}</Markdown>
              </div>
            </div>
          )}

          {message.role === 'assistant' && (
            <MessageActions message={message} />
          )}
        </div>
      </div>
    </motion.div>
  );
};

export const ThinkingMessage = () => {
  const role = 'assistant';
  const [dots, setDots] = useState('');
  const [loadingPhase, setLoadingPhase] = useState(0);
  const loadingMessages = [
    'Đang xử lý câu hỏi',
  ];

  // Hiệu ứng loading với dấu chấm
  useEffect(() => {
    const dotsInterval = setInterval(() => {
      setDots(prevDots => {
        if (prevDots.length >= 3) return '';
        return prevDots + '.';
      });
    }, 500);
    
    // Chuyển đổi giữa các giai đoạn loading
    const phaseInterval = setInterval(() => {
      setLoadingPhase(prev => (prev + 1) % loadingMessages.length);
    }, 3000);
    
    return () => {
      clearInterval(dotsInterval);
      clearInterval(phaseInterval);
    };
  }, []);

  // Phối màu cho các giai đoạn khác nhau
  const getPhaseColor = () => {
    const colors = [
      'text-green-600 dark:text-green-400',    // Xử lý
      'text-green-600 dark:text-green-400',  // Tìm kiếm
      'text-amber-600 dark:text-amber-400',  // Phân tích
      'text-purple-600 dark:text-purple-400' // Chuẩn bị
    ];
    return colors[loadingPhase];
  };

  // Background colors for icon container
  const getIconBgColor = () => {
    const colors = [
      'bg-blue-100 dark:bg-blue-900/30',    // Xử lý
      'bg-green-100 dark:bg-green-900/30',  // Tìm kiếm
      'bg-amber-100 dark:bg-amber-900/30',  // Phân tích
      'bg-purple-100 dark:bg-purple-900/30' // Chuẩn bị
    ];
    return colors[loadingPhase];
  };

  // Ring colors for icon container
  const getRingColor = () => {
    const colors = [
      'ring-blue-300 dark:ring-blue-700',    // Xử lý
      'ring-green-300 dark:ring-green-700',  // Tìm kiếm
      'ring-amber-300 dark:ring-amber-700',  // Phân tích
      'ring-purple-300 dark:ring-purple-700' // Chuẩn bị
    ];
    return colors[loadingPhase];
  };

  return (
    <motion.div
      className="w-full mx-auto max-w-3xl px-4 group/message"
      initial={{ y: 5, opacity: 0 }}
      animate={{ y: 0, opacity: 1, transition: { delay: 0.2 } }}
      data-role={role}
    >
      <div
        className={cx(
          'flex gap-4 items-center py-3 w-full rounded-xl',
          'bg-gray-50 dark:bg-zinc-900 border border-gray-100 dark:border-zinc-800'
        )}
      >
        <motion.div 
          className={cx(
            "size-8 flex items-center rounded-full justify-center ring-1 shrink-0 ml-4",
            getIconBgColor(),
            getRingColor()
          )}
          animate={{ 
            scale: [1, 1.08, 1]
          }}
          transition={{
            duration: 2.4,
            repeat: Infinity,
            ease: "easeInOut"
          }}
        >
          <SparklesIcon size={14} />
        </motion.div>
        
        <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 min-h-[20px]">
          <Loader2 className={cx("h-4 w-4 animate-spin", getPhaseColor())} />
          <AnimatePresence mode="wait">
            <motion.div
              key={loadingPhase}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -5 }}
              transition={{ duration: 0.3 }}
              className={cx("min-w-[200px] font-medium", getPhaseColor())}
            >
              <span className="animate-pulse inline-block mr-1">◆</span>
              {loadingMessages[loadingPhase]}{dots}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
};

