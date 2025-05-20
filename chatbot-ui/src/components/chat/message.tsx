import React, { FC, memo, useCallback, useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"
import { User2, Bot, X } from "lucide-react"
import { Button } from "@/components/ui/button"

import "./message.css"

// Icons
const ThinkingIcon = (props: any) => (
  <svg {...props} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v3" />
    <path d="M18.4 5.6 16.3 7.7" />
    <path d="M21 12h-3" />
    <path d="M18.4 18.4l-2.1-2.1" />
    <path d="M12 21v-3" />
    <path d="M5.6 18.4l2.1-2.1" />
    <path d="M3 12h3" />
    <path d="M5.6 5.6l2.1 2.1" />
  </svg>
)

const BotIcon = (props: any) => (
  <svg {...props} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 8V4H8" />
    <rect width="16" height="12" x="4" y="8" rx="2" />
    <path d="M2 14h2" />
    <path d="M20 14h2" />
    <path d="M15 13v2" />
    <path d="M9 13v2" />
  </svg>
)

// Danh sách từ khóa đặc biệt cần được định dạng
const SPECIAL_KEYWORDS = [
  "MKT-SALES",
  "PROPOSAL",
  "CONSTRUCTION",
  "DEFECT-HANDOVER",
  "AFTERSALE-MAINTENANCE"
];

// MemoizedReactMarkdown để hiển thị các từ khóa đặc biệt đẹp hơn
const MemoizedReactMarkdown: FC<{ children: string; className?: string }> = memo(
  ({ children, className }) => {
    // Xử lý nội dung trước khi hiển thị
    const processContent = (content: string) => {
      // Nếu nội dung rỗng hoặc không phải chuỗi, trả về nguyên bản
      if (!content || typeof content !== 'string') return content;

      // Kiểm tra nếu nội dung có chứa HTML
      const containsHTML = /<[a-z][\s\S]*>/i.test(content);

      if (containsHTML) {
        // Xử lý HTML một cách an toàn
        return content.replace(
          new RegExp(`(${SPECIAL_KEYWORDS.join('|')})`, 'g'),
          '<span class="highlight-keyword" data-keyword="$1">$1</span>'
        );
      }

      // Xử lý các từ khóa đặc biệt trong markdown
      let processedContent = content;

      // Xử lý từ khóa có dấu ** (trong markdown)
      SPECIAL_KEYWORDS.forEach(keyword => {
        const pattern = new RegExp(`\\*\\*(${keyword})\\*\\*`, 'g');
        processedContent = processedContent.replace(pattern, `<span class="highlight-keyword" data-keyword="$1">$1</span>`);
      });

      // Xử lý từ khóa không có dấu **
      SPECIAL_KEYWORDS.forEach(keyword => {
        const pattern = new RegExp(`(?<!\\*|\\w)(${keyword})(?!\\*|\\w)`, 'g');
        processedContent = processedContent.replace(pattern, `<span class="highlight-keyword" data-keyword="$1">$1</span>`);
      });

      // Xử lý các số được nhấn mạnh (**24**)
      processedContent = processedContent.replace(/\*\*(\d+)\*\*/g, '<strong>$1</strong>');

      return processedContent;
    };

    // Xử lý nội dung trước khi hiển thị
    const processedContent = processContent(children);

    // Nếu nội dung chứa HTML, sử dụng dangerouslySetInnerHTML
    if (/<[a-z][\s\S]*>/i.test(processedContent)) {
      return (
        <div 
          className={className}
          dangerouslySetInnerHTML={{ __html: processedContent }}
        />
      );
    }

    // Sử dụng ReactMarkdown cho nội dung không có HTML
    return (
      <ReactMarkdown
        className={className}
        remarkPlugins={[remarkGfm]}
        components={{
          pre({ node, className, children, ...props }) {
            return <pre className={className} {...props}>{children}</pre>
          },
          code({ node, className, children, ...props }: any) {
            if (props.inline) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              )
            }

            const match = /language-(\w+)/.exec(className || "")

            return (
              <pre 
                className={`language-${match ? match[1] : 'text'} rounded-md bg-muted p-4`}
              >
                <code>{String(children || "").replace(/\n$/, "")}</code>
              </pre>
            )
          },
          p({ children }) {
            if (typeof children === 'string' && /<[a-z][\s\S]*>/i.test(children)) {
              return <div dangerouslySetInnerHTML={{ __html: children }} />;
            }
            return <p>{children}</p>;
          },
          strong({ children }) {
            // Kiểm tra xem nội dung có phải là từ khóa đặc biệt không
            const content = typeof children === 'string' ? children : 
                          (Array.isArray(children) && children.length > 0 && typeof children[0] === 'string') 
                          ? children[0] 
                          : '';
                          
            const isSpecialKeyword = SPECIAL_KEYWORDS.some(
              keyword => content.toUpperCase() === keyword.toUpperCase()
            );
            
            if (isSpecialKeyword) {
              return (
                <span 
                  className="highlight-keyword" 
                  data-keyword={content}
                >
                  {content}
                </span>
              );
            }
            
            return <strong>{children}</strong>;
          }
        }}
      >
        {processedContent}
      </ReactMarkdown>
    )
  }
)

MemoizedReactMarkdown.displayName = "MemoizedReactMarkdown"

interface PreviewMessageProps {
  message: {
    id: string;
    role: string;
    content?: string;
    thinking?: string;
    isWarning?: boolean;
    isEdited?: boolean;
    toolCalls?: any[];
  };
  toolCalls?: any[];
  messageIndex: number;
  isLast: boolean;
  onEditMessage?: (message: any) => void;
  className?: string;
}

export const PreviewMessage: FC<PreviewMessageProps> = memo(({
  message,
  toolCalls,
  messageIndex,
  isLast,
  onEditMessage,
  className = ""
}) => {
  const messageContainerRef = useRef<HTMLDivElement>(null);
  const [showThinking, setShowThinking] = useState<boolean>(false);
  
  // Sử dụng state nội bộ để theo dõi nội dung tin nhắn và thinking
  const [messageContent, setMessageContent] = useState<string | undefined>(message.content);
  const [messageThinking, setMessageThinking] = useState<string | undefined>(message.thinking);
  const [messageToolCalls, setMessageToolCalls] = useState<any[] | undefined>(message.toolCalls || toolCalls);
  const [isNew, setIsNew] = useState<boolean>(true);
  
  // Cập nhật state nội bộ khi props thay đổi
  useEffect(() => {
    if (message.content !== messageContent) {
      setMessageContent(message.content);
      // Đánh dấu tin nhắn mới để kích hoạt hiệu ứng
      setIsNew(true);
      
      // Kích hoạt hiệu ứng highlight cho từ khóa mới
      setTimeout(() => {
        if (messageContainerRef.current) {
          const keywords = messageContainerRef.current.querySelectorAll('.highlight-keyword');
          keywords.forEach(keyword => {
            keyword.classList.remove('highlight-keyword-new');
            // Force a reflow
            void document.body.offsetHeight;
            keyword.classList.add('highlight-keyword-new');
          });
        }
      }, 100);
    }
    
    if (message.thinking !== messageThinking) {
      setMessageThinking(message.thinking);
    }
    
    if ((message.toolCalls || toolCalls) !== messageToolCalls) {
      setMessageToolCalls(message.toolCalls || toolCalls);
    }
  }, [message.content, message.thinking, message.toolCalls, toolCalls]);
  
  // Tự động cuộn xuống khi tin nhắn thay đổi
  useEffect(() => {
    if (isLast && messageContainerRef.current) {
      setTimeout(() => {
        messageContainerRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      }, 100);
    }
  }, [isLast, messageContent, messageThinking]);

  // Đánh dấu tin nhắn không còn mới sau 2 giây
  useEffect(() => {
    if (isNew) {
      const timer = setTimeout(() => {
        setIsNew(false);
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [isNew]);

  // Theo dõi các thay đổi từ WebSocket và cập nhật UI
  useEffect(() => {
    // Gửi sự kiện resize để buộc re-render trong một số trường hợp
    if (messageContent && message.content !== messageContent) {
      window.dispatchEvent(new Event('resize'));
    }
  }, [messageContent, message.content]);

  const toggleThinking = useCallback(() => {
    setShowThinking(prev => !prev);
  }, []);

  if (!message.content && !message.thinking && !messageToolCalls?.length) {
    return null;
  }

  return (
    <div
      ref={messageContainerRef}
      className={cn(
        "group relative mb-4 flex flex-col message-enter", 
        isNew && "message-container-new",
        className
      )}
    >
      <div className="flex flex-row">
        <div className="mr-2 flex h-[40px] w-[40px] flex-shrink-0 flex-col items-center justify-center rounded-md border bg-background p-1 shadow-sm">
          {message.role === "user" ? <User2 className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
        </div>
        
        <div className="flex-1">
          <div className="flex flex-col gap-1 overflow-hidden">
            {messageContent ? (
              <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-semibold prose-p:whitespace-pre-wrap">
                <MemoizedReactMarkdown className="prose prose-sm dark:prose-invert prose-p:my-1">
                  {messageContent || ""}
                </MemoizedReactMarkdown>
              </div>
            ) : message.role === "assistant" ? (
              <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-semibold prose-p:whitespace-pre-wrap">
                <div className="loading-indicator">
                  Đang trả lời
                  <div className="loading-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                </div>
                <div className="progress-bar"></div>
              </div>
            ) : null}
            
            {messageThinking && messageThinking.trim() !== '' && message.role === 'assistant' && (
              <div className="mt-2">
                <button
                  className="mb-1 flex items-center gap-1 text-xs text-muted-foreground hover:underline"
                  onClick={toggleThinking}
                >
                  {showThinking ? "Ẩn phân tích" : "Hiện phân tích"}
                </button>
                
                {showThinking && (
                  <div className="animate-in fade-in-50 rounded-md bg-muted/50 p-2 text-xs">
                    <MemoizedReactMarkdown className="prose prose-sm max-w-none dark:prose-invert prose-p:my-1 prose-pre:my-0">
                      {messageThinking}
                    </MemoizedReactMarkdown>
                  </div>
                )}
              </div>
            )}
            
            {messageToolCalls && messageToolCalls.length > 0 ? (
              <div className="mt-2">
                <div className="mb-1 flex items-center text-xs text-muted-foreground">
                  Tool Calls
                </div>
                
                <div className="animate-in fade-in-50 rounded-md bg-muted/50 p-2 text-xs">
                  <div className="prose prose-sm max-w-none dark:prose-invert prose-p:my-1 prose-pre:my-0">
                    {messageToolCalls.map((toolCall, index) => {
                      return (
                        <div key={index}>
                          <p className="font-semibold">{toolCall.name}:</p>
                          <pre className="mt-1 whitespace-pre-wrap">
                            {JSON.stringify(toolCall.args, null, 2)}
                          </pre>
                          {toolCall.result && (
                            <>
                              <p className="mt-2 font-semibold">Result:</p>
                              <pre className="mt-1 whitespace-pre-wrap">
                                {typeof toolCall.result === 'string'
                                  ? toolCall.result
                                  : JSON.stringify(toolCall.result, null, 2)}
                              </pre>
                            </>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
});

// Thêm animatedKeywords cho các từ khóa mới xuất hiện
const applyKeywordAnimation = (el: HTMLElement) => {
  const keywords = el.querySelectorAll('.highlight-keyword');
  keywords.forEach(keyword => {
    keyword.classList.remove('highlight-keyword-new');
    // Cần một reflow trước khi thêm lớp mới
    void (keyword as HTMLElement).offsetWidth;
    keyword.classList.add('highlight-keyword-new');
  });
}; 