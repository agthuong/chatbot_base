import { ChatInput } from "@/components/custom/chatinput";
import { PreviewMessage, ThinkingMessage } from "../../components/custom/message";
import { useScrollToBottom } from '@/components/custom/use-scroll-to-bottom';
import { useState, useRef, useEffect } from "react";
import { message, WebSocketAction } from "../../interfaces/interfaces"
import { Overview } from "@/components/custom/overview";
import { Header } from "@/components/custom/header";
import {v4 as uuidv4} from 'uuid';
import { Button } from "@/components/ui/button";
import { BrainCircuit } from "lucide-react";

// Tạo WebSocket kết nối
const socket = new WebSocket("ws://10.172.4.35:8090"); //change to your websocket endpoint

// Định nghĩa kiểu dữ liệu cho lịch sử tin nhắn theo phiên
interface SessionMessagesMap {
  [sessionId: string]: message[];
}

export function Chat() {
  const [messagesContainerRef, messagesEndRef] = useScrollToBottom<HTMLDivElement>();
  const [messages, setMessages] = useState<message[]>([]);
  const [question, setQuestion] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [thinkEnabled, setThinkEnabled] = useState<boolean>(false);
  // Thêm state để lưu trữ lịch sử tin nhắn của tất cả các phiên
  const [sessionMessages, setSessionMessages] = useState<SessionMessagesMap>({});
  // Thêm state để theo dõi đã tải lịch sử của các phiên chưa
  const [loadedSessions, setLoadedSessions] = useState<Set<string>>(new Set());

  const messageHandlerRef = useRef<((event: MessageEvent) => void) | null>(null);

  // State để lưu trữ thinking cho tin nhắn hiện tại
  let thinkingContent = "";
  // Biến để theo dõi xem đã nhận được token đầu tiên hay chưa
  let receivedFirstToken = false;
  // Biến để theo dõi xem đã tạo tin nhắn assistant mới chưa
  const createdAssistantMessageRef = useRef(false);

  // Xử lý chuyển đổi session
  const handleSessionChange = (sessionId: string) => {
    if (sessionId === currentSessionId) return;
    
    // Lưu lịch sử tin nhắn của phiên hiện tại
    if (currentSessionId) {
      setSessionMessages(prev => ({
        ...prev,
        [currentSessionId]: messages
      }));
      console.log(`Lưu ${messages.length} tin nhắn của phiên ${currentSessionId}`);
    }
    
    setCurrentSessionId(sessionId);
    setIsLoading(true);
    
    // Kiểm tra xem đã có lịch sử tin nhắn của phiên mới trong state chưa
    if (sessionMessages[sessionId]) {
      console.log(`Sử dụng ${sessionMessages[sessionId].length} tin nhắn đã lưu của phiên ${sessionId}`);
      setMessages(sessionMessages[sessionId]);
      setIsLoading(false);
    } else if (loadedSessions.has(sessionId)) {
      // Nếu đã từng tải lịch sử nhưng không có tin nhắn nào
      console.log(`Phiên ${sessionId} đã từng được tải nhưng không có tin nhắn`);
      setMessages([]);
      setIsLoading(false);
    } else {
      // Tải lịch sử tin nhắn từ server nếu chưa có
      if (socket.readyState === WebSocket.OPEN) {
        const action: WebSocketAction = {
          action: "get_history",
          session_id: sessionId
        };
        socket.send(JSON.stringify(action));
        console.log(`Đang tải lịch sử tin nhắn của phiên ${sessionId} từ server`);
      }
    }
  };

  // Xử lý bật/tắt chế độ Think
  const toggleThink = () => {
    setThinkEnabled(prev => !prev);
  };

  // Load lịch sử tin nhắn khi component mount
  useEffect(() => {
    // Chỉ tải khi socket đã kết nối
    if (socket.readyState === WebSocket.OPEN) {
      const action: WebSocketAction = { action: "get_sessions" };
      socket.send(JSON.stringify(action));
    } else {
      // Đăng ký event listener khi socket mở
      const handleOpen = () => {
        const action: WebSocketAction = { action: "get_sessions" };
        socket.send(JSON.stringify(action));
      };
      socket.addEventListener('open', handleOpen);
      // Cleanup
      return () => socket.removeEventListener('open', handleOpen);
    }
  }, []);

  // Khởi tạo message handler hiệu quả hơn
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      try {
        // Kiểm tra và xử lý trường hợp có nhiều JSON trong cùng một thông điệp
        let dataStr = event.data as string;
        
        // Kiểm tra xem dataStr có chứa nhiều JSON đính kém không
        if (dataStr.indexOf('}{') > 0) {
          console.warn("Phát hiện nhiều JSON trong một thông điệp, tách ra và xử lý từng cái.");
          
          // Phân tách các chuỗi JSON
          const jsonStrings = dataStr.split('}{').map((str, i, arr) => {
            if (i === 0) return str + '}';
            if (i === arr.length - 1) return '{' + str;
            return '{' + str + '}';
          });
          
          // Xử lý từng chuỗi JSON một
          jsonStrings.forEach(jsonStr => {
            try {
              const singleData = JSON.parse(jsonStr);
              handleSingleMessage(singleData);
            } catch (e) {
              console.error("Lỗi phân tích chuỗi JSON riêng:", e);
            }
          });
          
          return; // Đã xử lý tất cả các phần, không cần xử lý tiếp
        }
        
        // Xử lý JSON duy nhất
        const data = JSON.parse(dataStr);
        handleSingleMessage(data);
        
      } catch (e) {
        console.error("Lỗi xử lý dữ liệu từ WebSocket:", e, "Data:", event.data);
      }
    };
    
    // Hàm xử lý riêng cho từng thông điệp JSON
    const handleSingleMessage = (data: any) => {
        // Xử lý response từ action get_history
        if (data.action === "get_history_response" && data.status === "success") {
          setIsLoading(false); // Tắt loading khi nhận được dữ liệu
          const history = data.history || [];
          
          // Chuyển đổi lịch sử thành định dạng tin nhắn
          const historyMessages: message[] = [];
          
          if (history && history.length > 0) {
            history.forEach((item: any) => {
              // Thêm tin nhắn người dùng
              if (item.query) {
                historyMessages.push({
                  content: item.query,
                  role: "user",
                  id: `history_${item.timestamp}_user`
                });
              }
              
              // Thêm tin nhắn từ trợ lý
              if (item.response) {
                historyMessages.push({
                  content: item.response,
                  role: "assistant",
                  id: `history_${item.timestamp}_assistant`
                });
              }
            });
            
            // Cập nhật messages và sessionMessages
            setMessages(historyMessages);
            setSessionMessages(prev => ({
              ...prev,
              [currentSessionId]: historyMessages
            }));
            
            // Đánh dấu phiên này đã được tải
            setLoadedSessions(prev => new Set(prev).add(currentSessionId));
            
            console.log(`Đã tải ${historyMessages.length} tin nhắn từ lịch sử phiên ${currentSessionId}`);
          } else {
            // Nếu không có lịch sử, đặt messages thành mảng rỗng
            setMessages([]);
            setSessionMessages(prev => ({
              ...prev,
              [currentSessionId]: []
            }));
            
            // Đánh dấu phiên này đã được tải
            setLoadedSessions(prev => new Set(prev).add(currentSessionId));
            
            console.log("Không có lịch sử tin nhắn cho phiên này");
          }
        }
        // Xử lý init_session_data từ server khi kết nối lại
        else if (data.action === "init_session_data" && data.status === "success") {
          console.log("Nhận được dữ liệu khởi tạo phiên:", data);
          
          // Cập nhật session ID hiện tại
          setCurrentSessionId(data.current_session_id);
          
          // Chuyển đổi lịch sử thành định dạng tin nhắn
          const history = data.history || [];
          const historyMessages: message[] = [];
          
          if (history && history.length > 0) {
            history.forEach((item: any) => {
              // Thêm tin nhắn người dùng
              if (item.query) {
                historyMessages.push({
                  content: item.query,
                  role: "user",
                  id: `history_${item.timestamp}_user`
                });
              }
              
              // Thêm tin nhắn từ trợ lý
              if (item.response) {
                historyMessages.push({
                  content: item.response,
                  role: "assistant",
                  id: `history_${item.timestamp}_assistant`
                });
              }
            });
            
            // Cập nhật messages và sessionMessages
            setMessages(historyMessages);
            setSessionMessages(prev => ({
              ...prev,
              [data.current_session_id]: historyMessages
            }));
            
            // Đánh dấu phiên này đã được tải
            setLoadedSessions(prev => new Set(prev).add(data.current_session_id));
            
            console.log(`Khôi phục ${historyMessages.length} tin nhắn từ phiên ${data.current_session_id}`);
          } else {
            // Không có lịch sử, đặt messages thành mảng rỗng
            setMessages([]);
            
            // Đánh dấu phiên này đã được tải
            setLoadedSessions(prev => new Set(prev).add(data.current_session_id));
          }
          
          setIsLoading(false);
        }
        // Xử lý session_updated từ server khi chuyển phiên
        else if (data.action === "session_updated" && data.status === "success") {
          console.log("Nhận được cập nhật phiên:", data);
          
          setCurrentSessionId(data.current_session_id);
          
          // Chuyển đổi lịch sử thành định dạng tin nhắn
          const history = data.history || [];
          const historyMessages: message[] = [];
          
          if (history && history.length > 0) {
            history.forEach((item: any) => {
              // Thêm tin nhắn người dùng
              if (item.query) {
                historyMessages.push({
                  content: item.query,
                  role: "user",
                  id: `history_${item.timestamp}_user`
                });
              }
              
              // Thêm tin nhắn từ trợ lý
              if (item.response) {
                historyMessages.push({
                  content: item.response,
                  role: "assistant",
                  id: `history_${item.timestamp}_assistant`
                });
              }
            });
            
            // Cập nhật messages và sessionMessages
            setMessages(historyMessages);
            setSessionMessages(prev => ({
              ...prev,
              [data.current_session_id]: historyMessages
            }));
            
            console.log(`Cập nhật ${historyMessages.length} tin nhắn cho phiên ${data.current_session_id}`);
          } else {
            // Không có lịch sử, đặt messages thành mảng rỗng
            setMessages([]);
            setSessionMessages(prev => ({
              ...prev,
              [data.current_session_id]: []
            }));
          }
          
          // Đánh dấu phiên này đã được tải
          setLoadedSessions(prev => new Set(prev).add(data.current_session_id));
          setIsLoading(false);
        }
    };

    socket.addEventListener("message", handleMessage);
    return () => socket.removeEventListener("message", handleMessage);
  }, [currentSessionId]);

  const cleanupMessageHandler = () => {
    if (messageHandlerRef.current && socket) {
      socket.removeEventListener("message", messageHandlerRef.current);
      messageHandlerRef.current = null;
    }
  };

  // Hàm gửi tin nhắn và nhận phản hồi
async function handleSubmit(text?: string) {
  if (!socket || socket.readyState !== WebSocket.OPEN || isLoading) return;

    let messageText = text || question;
    
    // Kiểm tra để đảm bảo rằng messageText không rỗng
    if (!messageText || messageText.trim() === '') return;
    
    // Hiển thị tin nhắn gốc cho người dùng (không bao gồm hậu tố think)
    const displayMessage = messageText;
    
    // Thêm hậu tố think hoặc no_think vào câu hỏi
    messageText = messageText.trim();
    if (thinkEnabled) {
      messageText = `${messageText} /think`;
      console.log("Đã thêm hậu tố /think:", messageText);
    } else {
      messageText = `${messageText} /no_think`;
      console.log("Đã thêm hậu tố /no_think:", messageText); 
    }
    
  setIsLoading(true);
    // Đảm bảo dọn dẹp message handler cũ trước khi tạo mới
  cleanupMessageHandler();
  
    const messageId = uuidv4();
    
    // Thêm tin nhắn người dùng vào danh sách
    const newUserMessage: message = { 
      content: displayMessage, 
      role: "user", 
      id: messageId 
    };
    const updatedMessages = [...messages, newUserMessage];
    setMessages(updatedMessages);
    
    // Cập nhật lịch sử tin nhắn cho phiên hiện tại
    setSessionMessages(prev => ({
      ...prev,
      [currentSessionId]: updatedMessages
    }));
    
    // Gửi tin nhắn thông thường hoặc tin nhắn JSON tùy thuộc vào trường hợp
    if (displayMessage.startsWith('/')) {
      // Xử lý các lệnh đặc biệt
      if (displayMessage === '/clear') {
        // Xóa lịch sử hội thoại
        const action: WebSocketAction = {
          action: "clear_history",
          session_id: currentSessionId
        };
        socket.send(JSON.stringify(action));
        setMessages([]);
        
        // Cập nhật trong sessionMessages
        setSessionMessages(prev => ({
          ...prev,
          [currentSessionId]: []
        }));
        
        setIsLoading(false);
        return;
      }
    } else {
      // Gửi tin nhắn bình thường với session_id để đảm bảo lưu lịch sử đúng
      const message = {
        content: messageText,
        session_id: currentSessionId
      };
      // Gửi dưới dạng JSON để server có thể xử lý session_id
      socket.send(JSON.stringify(message));
    }
    
  setQuestion("");

    // Đánh dấu đã tạo tin nhắn assistant
    createdAssistantMessageRef.current = true;

  try {
    const messageHandler = (event: MessageEvent) => {
        // Log dữ liệu nhận được để debug
        console.log("WebSocket received data:", event.data);
        
        // Ẩn ThinkingMessage ngay khi nhận được token đầu tiên
        if (!receivedFirstToken) {
          receivedFirstToken = true;
      setIsLoading(false);
        }

        // Kiểm tra kết thúc tin nhắn
        if(typeof event.data === 'string' && event.data.includes("[END]")) {
          cleanupMessageHandler();
          return;
        }
        
        // Xử lý dữ liệu JSON an toàn
        processWebSocketData(event.data, messageId);
    };

    // Hàm xử lý dữ liệu từ WebSocket một cách an toàn
    const processWebSocketData = (data: any, msgId: string) => {
      try {
        // Kiểm tra nếu data là chuỗi rỗng
        if (typeof data === 'string' && !data.trim()) {
          console.warn('Nhận được dữ liệu rỗng');
          return;
        }
        
        // Xử lý trường hợp có nhiều JSON object được nối với nhau
        if (typeof data === 'string' && data.includes('}{')) {
          console.log('Phát hiện nhiều JSON object được nối liền, tách và xử lý từng object');
          
          // Sử dụng regex để tìm tất cả JSON objects trong chuỗi
          const jsonPattern = /\{(?:[^{}]|(?:\{[^{}]*\}))*\}/g;
          const jsonMatches = data.match(jsonPattern);
          
          if (jsonMatches) {
            jsonMatches.forEach(jsonStr => {
              try {
                const jsonData = JSON.parse(jsonStr);
                processJsonData(jsonData, msgId);
              } catch (jsonError) {
                console.error('Lỗi khi parse JSON riêng lẻ:', jsonError);
              }
            });
            return;
          }
        }
        
        // Cố gắng parse JSON nếu data là string
        let jsonData: any;
        if (typeof data === 'string') {
          try {
            jsonData = JSON.parse(data);
          } catch (jsonError) {
            // Nếu không phải JSON hợp lệ, cập nhật nội dung tin nhắn
            updateOrCreateAssistantMessage(msgId, data);
            return;
          }
        } else {
          jsonData = data;
        }
        
        // Xử lý dữ liệu JSON đã được phân tích
        processJsonData(jsonData, msgId);
      } catch (error) {
        console.error('Lỗi khi xử lý dữ liệu WebSocket:', error);
        
        // Trong trường hợp lỗi, vẫn cố gắng cập nhật tin nhắn nếu có dữ liệu
        if (typeof data === 'string' && data.trim()) {
          updateOrCreateAssistantMessage(msgId, data);
        }
      }
    };
    
    // Xử lý dữ liệu JSON
    const processJsonData = (jsonData: any, msgId: string) => {
          // Kiểm tra nếu jsonData là một tin nhắn hoàn chỉnh từ server (có đủ các trường cần thiết)
          if (jsonData.role === "assistant" && jsonData.content !== undefined) {
            // Xử lý trường hợp nhận được tin nhắn hoàn chỉnh từ server
            setMessages(prev => {
              // Tạo tin nhắn mới từ dữ liệu JSON
              const newMessage: message = {
                content: jsonData.content,
                role: "assistant",
            id: msgId,
                thinking: jsonData.thinking || null
              };
              
              // Kiểm tra xem đã có tin nhắn assistant cho messageId này chưa
              const assistantIndex = prev.findIndex(msg => 
            msg.role === "assistant" && msg.id === msgId && !msg.isWarning
              );
              
              let newMessages;
              if (assistantIndex >= 0) {
                // Cập nhật tin nhắn đã tồn tại
                newMessages = [
                  ...prev.slice(0, assistantIndex),
                  newMessage,
                  ...prev.slice(assistantIndex + 1)
                ];
              } else {
                // Thêm tin nhắn mới
                newMessages = [...prev, newMessage];
              }
              
              // Cập nhật sessionMessages
              setSessionMessages(prevSessions => ({
                ...prevSessions,
                [currentSessionId]: newMessages
              }));
              
              return newMessages;
            });
            
        // Đã xử lý tin nhắn hoàn chỉnh
            return;
          }
          
          // Xử lý warning message
          if (jsonData.type === "warning" && jsonData.content) {
            // Hiển thị cảnh báo cho người dùng
            console.warn("Cảnh báo từ server:", jsonData.content);
            
            // Thêm thông báo cảnh báo vào tin nhắn hệ thống
            setMessages(prev => {
              // Tìm tin nhắn cảnh báo hiện có
              const warningIndex = prev.findIndex(msg => 
                msg.role === "assistant" && msg.isWarning === true
              );
              
              if (warningIndex >= 0) {
                // Cập nhật tin nhắn cảnh báo đã tồn tại
                const updatedWarning = { 
                  ...prev[warningIndex], 
                  content: jsonData.content
                };
                
                const newMessages = [
                  ...prev.slice(0, warningIndex), 
                  updatedWarning, 
                  ...prev.slice(warningIndex + 1)
                ];
                
                // Cập nhật cả sessionMessages
                setSessionMessages(prevSessions => ({
                  ...prevSessions,
                  [currentSessionId]: newMessages
                }));
                
                return newMessages;
              } else {
                // Tạo tin nhắn cảnh báo mới
                const warningMessage: message = {
                  content: jsonData.content,
                  role: "assistant" as const,
                  id: `warning_${Date.now()}`,
                  isWarning: true
                };
                
                const newMessages = [...prev, warningMessage];
                
                // Cập nhật cả sessionMessages
                setSessionMessages(prevSessions => ({
                  ...prevSessions,
                  [currentSessionId]: newMessages
                }));
                
                return newMessages;
              }
            });
        return;
      }
      
          // Xử lý thinking mode
          if (jsonData.type === "thinking" && jsonData.content) {
            thinkingContent = jsonData.content;
            
            // Cập nhật tin nhắn với phần thinking chỉ khi chế độ Think được bật
            if (thinkEnabled) {
          updateAssistantMessageWithThinking(msgId, thinkingContent);
        }
        return;
      }
    };
    
    // Hàm cập nhật tin nhắn assistant với thinking
    const updateAssistantMessageWithThinking = (msgId: string, thinking: string) => {
      setMessages(prev => {
                // Tìm tin nhắn assistant cuối cùng liên kết với messageId
                const assistantIndex = prev.findIndex(msg => 
          msg.role === "assistant" && msg.id === msgId
                );
                
                if (assistantIndex >= 0) {
                  // Cập nhật thinking cho tin nhắn đã tồn tại
                  const updatedMessage = { 
                    ...prev[assistantIndex], 
            thinking: thinking 
                  };
                  
                  const newMessages = [
                    ...prev.slice(0, assistantIndex), 
                    updatedMessage, 
                    ...prev.slice(assistantIndex + 1)
                  ];
                  
          // Cập nhật sessionMessages
                  setSessionMessages(prevSessions => ({
                    ...prevSessions,
                    [currentSessionId]: newMessages
                  }));
                  
                  return newMessages;
        }
        
        return prev;
      });
    };
    
    // Hàm cập nhật hoặc tạo mới tin nhắn assistant
    const updateOrCreateAssistantMessage = (msgId: string, content: string) => {
        setMessages(prev => {
        // Tìm tin nhắn assistant cuối cùng liên kết với messageId
          const assistantIndex = prev.findIndex(msg => 
          msg.role === "assistant" && msg.id === msgId && !msg.isWarning
          );
          
          if (assistantIndex >= 0) {
          // Cập nhật nội dung cho tin nhắn đã tồn tại
          const currentMessage = prev[assistantIndex];
            const updatedMessage = { 
            ...currentMessage, 
            content: currentMessage.content + content 
            };
            
          const newMessages = [
              ...prev.slice(0, assistantIndex),
              updatedMessage,
              ...prev.slice(assistantIndex + 1)
            ];
          
          // Cập nhật sessionMessages
          setSessionMessages(prevSessions => ({
            ...prevSessions,
            [currentSessionId]: newMessages
          }));
          
          return newMessages;
          } else {
          // Tạo tin nhắn mới nếu chưa tồn tại
            const newMessage: message = { 
            content: content,
              role: "assistant", 
            id: msgId,
            thinking: thinkingContent || undefined
            };
            
          const newMessages = [...prev, newMessage];
          
          // Cập nhật sessionMessages
          setSessionMessages(prevSessions => ({
            ...prevSessions,
            [currentSessionId]: newMessages
          }));
          
          // Đánh dấu đã tạo tin nhắn assistant
          createdAssistantMessageRef.current = true;
          
          return newMessages;
        }
        });
      };

    // Đăng ký handler xử lý tin nhắn
    messageHandlerRef.current = messageHandler;
    socket.addEventListener("message", messageHandler);
  } catch (error) {
    console.error("WebSocket error:", error);
    setIsLoading(false);
  }
}

  return (
    <div className="flex flex-col min-w-0 h-dvh bg-background">
      <Header socket={socket} onSessionChange={handleSessionChange}/>
      <div className="flex flex-col min-w-0 gap-6 flex-1 overflow-y-scroll pt-4" ref={messagesContainerRef}>
        {messages.length == 0 && <Overview />}
        {messages.map((message, _index) => (
          <PreviewMessage
            key={message.id}
            message={message}
            socket={socket}
            sessionId={currentSessionId}
          />
        ))}
        {isLoading && <ThinkingMessage />}
        <div ref={messagesEndRef} className="shrink-0 min-w-[24px] min-h-[24px]"/>
      </div>
      <div className="flex-col mx-auto px-4 bg-background pb-4 md:pb-6 gap-2 w-full md:max-w-4xl">
        <div className="flex justify-end mb-2">
          <Button
            onClick={toggleThink}
            variant={thinkEnabled ? "default" : "outline"}
            size="sm"
            className="flex items-center gap-1.5 font-medium"
          >
            <BrainCircuit className="h-4 w-4" />
            {thinkEnabled ? "Think: Bật" : "Think: Tắt"}
          </Button>
        </div>
        <ChatInput  
          question={question}
          setQuestion={setQuestion}
          onSubmit={handleSubmit}
          isLoading={isLoading}
        />
      </div>
    </div>
  );
};