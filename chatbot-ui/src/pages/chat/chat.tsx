import { ChatInput } from "@/components/custom/chatinput";
import { PreviewMessage, ThinkingMessage } from "../../components/custom/message";
import { useScrollToBottom } from '@/components/custom/use-scroll-to-bottom';
import { useState, useRef, useEffect } from "react";
import { message } from "../../interfaces/interfaces"
import { Overview } from "@/components/custom/overview";
import { Header } from "@/components/custom/header";
import {v4 as uuidv4} from 'uuid';
import { Button } from "@/components/ui/button";
import { BrainCircuit } from "lucide-react";
import { toast } from "sonner";

// Tạo WebSocket kết nối
// Tự động sử dụng hostname của trang web hiện tại để tạo URL WebSocket
const getWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const hostname = window.location.hostname;
  const port = window.location.port;
  
  // Nếu đang chạy trong Docker, sử dụng cùng cổng mà user đang truy cập
  if (port) {
    // Sử dụng cùng cổng với trang web hiện tại
    return `${protocol}//${hostname}:${port}/ws`;
  } else {
    // Nếu không có cổng (sử dụng cổng mặc định 80/443), giữ nguyên
    return `${protocol}//${hostname}/ws`;
  }
};

// const socket = new WebSocket(API_WS_URL);


export function Chat() {
  const [messagesContainerRef, messagesEndRef] = useScrollToBottom<HTMLDivElement>();
  const [messages, setMessages] = useState<message[]>([]);
  const [question, setQuestion] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [thinkEnabled, setThinkEnabled] = useState<boolean>(false);
  const [_socketConnected, _setSocketConnected] = useState<boolean>(false);
  const [isLoggedIn, _setIsLoggedIn] = useState<boolean>(true);
  const [modelType, setModelType] = useState<"original" | "gemini">("original");

  const socketRef = useRef<WebSocket | null>(null);
  const latestMessageId = useRef<string | null>(null);
  const createdAssistantMessageRef = useRef(false);

  // State để lưu trữ thinking cho tin nhắn hiện tại

  // Biến để theo dõi xem đã nhận được token đầu tiên hay chưa
  let receivedFirstToken = false;

  // Khi chuyển phiên, chỉ gửi 1 request switch_session
  const handleSessionChange = (sessionId: string) => {
    if (sessionId === currentSessionId) return;
    setCurrentSessionId(sessionId);
    setIsLoading(true);
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({
        action: "switch_session",
        session_id: sessionId
      }));
    }
  };

  // Xử lý bật/tắt chế độ Think
  const toggleThink = () => {
    setThinkEnabled(prev => !prev);
  };

  // Xử lý đổi model_type từ dropdown
  const handleModelTypeChange = (newType: string) => {
    if (newType === modelType) return;
    setModelType(newType as "original" | "gemini");
    
    // Lưu model_type vào localStorage để giữ lại sau khi reload trang
    localStorage.setItem('preferred_model_type', newType);
    
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({
        action: "set_session_model_type",
        session_id: currentSessionId,
        model_type: newType
      }));
    }
  };

  // Load lịch sử tin nhắn khi component mount
  useEffect(() => {
    // Khôi phục model_type từ localStorage nếu có
    const savedModelType = localStorage.getItem('preferred_model_type');
    if (savedModelType && (savedModelType === 'original' || savedModelType === 'gemini')) {
      setModelType(savedModelType as "original" | "gemini");
    }

    const socket = new WebSocket(getWebSocketUrl());
    socketRef.current = socket;
    socket.onopen = () => {
      _setSocketConnected(true);
      if (isLoggedIn) {
        socket.send(JSON.stringify({
          action: "get_session",
          session_id: currentSessionId
        }));
      }
    };
    socket.onclose = () => _setSocketConnected(false);
    socket.onerror = () => toast.error("Lỗi kết nối WebSocket. Vui lòng tải lại trang.");
    return () => { socket.close(); };
  }, []);

  // Lắng nghe các event WebSocket và cập nhật đúng phiên
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      try {
        let dataStr = event.data as string;
        if (dataStr.indexOf('}{') > 0) {
          const jsonStrings = dataStr.split('}{').map((str, i, arr) => {
            if (i === 0) return str + '}';
            if (i === arr.length - 1) return '{' + str;
            return '{' + str + '}';
          });
          jsonStrings.forEach(jsonStr => {
            try { handleSingleMessage(JSON.parse(jsonStr)); } catch {}
          });
          return;
        }
        const data = JSON.parse(dataStr);
        handleSingleMessage(data);
      } catch {}
    };

    // Hàm xử lý riêng cho từng thông điệp JSON
    const handleSingleMessage = (data: any) => {
      // Xử lý phản hồi khi chuyển đổi model_type
      if (data.action === "set_session_model_type_response" && data.status === "success") {
        // Nếu đã tạo session mới, cập nhật currentSessionId
        if (data.new_session) {
          setCurrentSessionId(data.session_id);
        }
        
        // Cập nhật model_type
        setModelType(data.model_type as "original" | "gemini");
        
        // Lưu model_type vào localStorage để giữ lại sau khi reload trang
        localStorage.setItem('preferred_model_type', data.model_type);
        
        // Cập nhật lịch sử tin nhắn
        const history = data.history || [];
        const historyMessages: message[] = [];
        if (history && history.length > 0) {
          history.forEach((item: any) => {
            if (item.query) {
              historyMessages.push({
                content: item.query,
                role: "user",
                id: `history_${item.timestamp}_user`
              });
            }
            if (item.response) {
              historyMessages.push({
                content: item.response,
                role: "assistant",
                id: `history_${item.timestamp}_assistant`
              });
            }
          });
          setMessages(historyMessages);
        } else {
          setMessages([]);
        }
        
        setIsLoading(false);
        
        // Thông báo thành công
        toast.success(`Đã chuyển sang model: ${data.model_type === "gemini" ? "Gemini" : "Mô hình gốc"}`);
      }
      // Xử lý các event liên quan đến chuyển phiên/lịch sử
      else if ((data.action === "switch_session_response" || data.action === "session_updated" || data.action === "get_history_response") && data.status === "success") {
        // Ưu tiên lấy session_id từ data, nếu không có thì lấy currentSessionId
        const sessionId = data.session_id || data.current_session_id || currentSessionId;
        // Chỉ cập nhật nếu đúng phiên đang active
        if (sessionId === currentSessionId) {
          // Cập nhật model_type nếu có
          if (data.model_type) {
            setModelType(data.model_type as "original" | "gemini");
            // Lưu model_type vào localStorage để giữ lại sau khi reload trang
            localStorage.setItem('preferred_model_type', data.model_type);
          }
          
          const history = data.history || [];
          // Chuyển đổi lịch sử thành định dạng tin nhắn
          const historyMessages: message[] = [];
          if (history && history.length > 0) {
            history.forEach((item: any) => {
              if (item.query) {
                historyMessages.push({
                  content: item.query,
                  role: "user",
                  id: `history_${item.timestamp}_user`
                });
              }
              if (item.response) {
                historyMessages.push({
                  content: item.response,
                  role: "assistant",
                  id: `history_${item.timestamp}_assistant`
                });
              }
            });
            setMessages(historyMessages);
          } else {
            setMessages([]);
          }
          setIsLoading(false);
          // Scroll xuống cuối khi có dữ liệu mới
          setTimeout(() => {
            if (messagesEndRef && messagesEndRef.current) {
              messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
            }
          }, 100);
        }
      }
      // Xử lý init_session_data khi load lại trang
      else if (data.action === "init_session_data" && data.status === "success") {
        setCurrentSessionId(data.current_session_id);
        
        // Cập nhật model_type từ server, nhưng ưu tiên giá trị đã lưu trong localStorage
        if (data.model_type) {
          const savedModelType = localStorage.getItem('preferred_model_type');
          if (savedModelType && (savedModelType === 'original' || savedModelType === 'gemini')) {
            // Nếu có model_type đã lưu trong localStorage, sử dụng và gửi lệnh cập nhật nếu khác với model_type trên server
            setModelType(savedModelType as "original" | "gemini");
            
            // Chỉ gửi lệnh cập nhật nếu khác với model_type trên server
            if (savedModelType !== data.model_type && socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
              socketRef.current.send(JSON.stringify({
                action: "set_session_model_type",
                session_id: data.current_session_id,
                model_type: savedModelType
              }));
            }
          } else {
            // Nếu không có trong localStorage, sử dụng giá trị từ server
            setModelType(data.model_type as "original" | "gemini");
            localStorage.setItem('preferred_model_type', data.model_type);
          }
        }
        
        const history = data.history || [];
        const historyMessages: message[] = [];
        if (history && history.length > 0) {
          history.forEach((item: any) => {
            if (item.query) {
              historyMessages.push({
                content: item.query,
                role: "user",
                id: `history_${item.timestamp}_user`
              });
            }
            if (item.response) {
              historyMessages.push({
                content: item.response,
                role: "assistant",
                id: `history_${item.timestamp}_assistant`
              });
            }
          });
          setMessages(historyMessages);
        } else {
          setMessages([]);
        }
        setIsLoading(false);
        setTimeout(() => {
          if (messagesEndRef && messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
          }
        }, 100);
      }
      // Các event khác giữ nguyên logic cũ
    };

    socketRef.current && socketRef.current.addEventListener("message", handleMessage);
    return () => {
      if (socketRef.current) {
        socketRef.current.removeEventListener("message", handleMessage);
      }
    };
  }, [currentSessionId]);

  // Thêm một message rỗng cho assistant để hiển thị streaming
  function addEmptyAssistantMessage(messageId: string) {
    console.log("Thêm tin nhắn rỗng cho assistant với ID:", messageId);
    
    setMessages(prevMessages => {
      // Kiểm tra xem đã có tin nhắn assistant nào với ID này chưa
      const existingAssistantMessage = prevMessages.find(msg => 
        msg.role === "assistant" && msg.id === messageId
      );
      
      if (existingAssistantMessage) {
        console.log("Đã có tin nhắn assistant cho ID này");
        return prevMessages;
      }
      
      // Tạo tin nhắn mới, trống cho assistant
      const emptyAssistantMessage: message = {
        role: "assistant",
        id: messageId,
        content: "",
        model_type: modelType as "original" | "gemini"
      };
      
      const newMessages = [...prevMessages, emptyAssistantMessage];
      
      return newMessages;
    });
  }

  // Tiền xử lý nội dung tin nhắn
  function preprocessContent(content: string) {
    if (!content) return "";
    
    // Log nội dung gốc
    console.log("preprocessContent - Nội dung gốc:", content);
    
    // Chỉ làm nổi bật từ khóa đặc biệt, không động chạm gì đến \n hoặc markdown
    const specialKeywords = [
      "MKT-SALES", 
      "PROPOSAL", 
      "CONSTRUCTION", 
      "DEFECT-HANDOVER", 
      "AFTERSALE-MAINTENANCE"
    ];
    let processedContent = content;
    specialKeywords.forEach(keyword => {
      // Đảm bảo từ khóa giữ nguyên dạng markdown với **
      const regex = new RegExp(`(?<!\\*)\\b${keyword}\\b(?!\\*)`, 'gi');
      processedContent = processedContent.replace(regex, `**${keyword}**`);
    });
    processedContent = processedContent.replace(/\b(là|có)\s+(\d+)\b/gi, (prefix, number) => {
      return `${prefix} **${number}**`;
    });
    
    // Log nội dung sau khi xử lý
    console.log("preprocessContent - Nội dung sau xử lý:", processedContent);
    
    return processedContent;
  }

  // Hàm xử lý thông điệp JSON từ WebSocket
  function processJsonData(data: any) {
    try {
      console.log("Đang xử lý JSON data:", JSON.stringify(data).substring(0, 1000));

      // Xử lý các loại thông điệp khác nhau
      if (data.thinking) {
        // Mô hình đang suy nghĩ, cập nhật thinking nếu có id
        if (data.id) {
          console.log("Nhận được thinking cho tin nhắn ID:", data.id);
          // Tìm tin nhắn hiện tại và cập nhật thinking
          const processedThinking = preprocessContent(data.thinking);
          
          // Cập nhật tin nhắn với thinking mới
          updateAssistantMessageWithThinking(data.id, processedThinking);
          
          // Kích hoạt re-render
          setTimeout(() => window.dispatchEvent(new Event('resize')), 10);
        } else {
          console.warn("Nhận được thinking nhưng không có message ID");
        }
      } else if (data.error) {
        // Xử lý lỗi
        console.error("Lỗi từ API:", data.error);
        // Hiển thị thông báo lỗi cho người dùng
        toast.error(`Lỗi: ${data.error}`);
        setIsLoading(false);
      } else if (data.content !== undefined) {
        // Nếu có nội dung, xử lý như tin nhắn hoàn chỉnh
        console.log("Nhận được tin nhắn có nội dung (50 ký tự đầu):", data.content.substring(0, 50), "...");
        console.log("Toàn bộ nội dung tin nhắn (2000 ký tự đầu):", data.content.substring(0, 2000));

        // Lấy ID tin nhắn từ dữ liệu hoặc sử dụng ID mặc định
        const messageId = data.id || latestMessageId.current || "latest_message";
        
        // Kiểm tra độ dài của tin nhắn để cải thiện hiệu suất
        const content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content);
        
        // Tiền xử lý nội dung để định dạng các từ khóa đặc biệt
        const processedContent = preprocessContent(content);
        
        // Lấy thinking nếu có
        const messageThinking = data.thinking ? preprocessContent(data.thinking) : "";
        
        console.log("Cập nhật tin nhắn ID:", messageId, "với nội dung đã xử lý");
        
        // Cập nhật tin nhắn với nội dung đã xử lý
        updateOrCreateAssistantMessage(messageId, processedContent);
        
        // Nếu có thinking, cập nhật riêng
        if (messageThinking) {
          updateAssistantMessageWithThinking(messageId, messageThinking);
        }
        
        // Kích hoạt re-render bằng cách gửi event resize
        setTimeout(() => window.dispatchEvent(new Event('resize')), 10);
        
        // Đánh dấu không còn loading
        setIsLoading(false);
      } else if (data.tool_calls && data.id) {
        // Xử lý tool calls
        console.log("Nhận được tool calls cho tin nhắn ID:", data.id);
        // Tạm thời vô hiệu hóa xử lý tool calls vì chưa cần thiết
        // handleToolCalls(data.id, data.tool_calls);
      } else {
        console.warn("Nhận được loại tin nhắn không xác định:", data);
      }
    } catch (error) {
      console.error("Lỗi khi xử lý dữ liệu JSON:", error);
      toast.error("Lỗi xử lý dữ liệu từ server");
      setIsLoading(false);
    }
  }

  // Cập nhật tin nhắn assistant với nội dung
  function updateOrCreateAssistantMessage(msgId: string, content: string) {
    console.log(`Cập nhật tin nhắn ID: ${msgId}, nội dung:`, content.substring(0, 30));
    setMessages(prev => {
      const assistantIndex = prev.findIndex(msg => 
        msg.role === "assistant" && msg.id === msgId && !msg.isWarning
      );
      if (assistantIndex >= 0) {
        const updatedMessage = { 
          ...prev[assistantIndex], 
          content
        };
        const newMessages = [
          ...prev.slice(0, assistantIndex), 
          updatedMessage, 
          ...prev.slice(assistantIndex + 1)
        ];
        return newMessages;
      } else {
        const newMessage: message = {
          content,
          role: "assistant",
          id: msgId,
          model_type: modelType as "original" | "gemini"
        };
        return [...prev, newMessage];
      }
    });
  }

  // Cập nhật tin nhắn assistant với thinking
  function updateAssistantMessageWithThinking(msgId: string, thinking: string) {
    setMessages(prev => {
      const assistantIndex = prev.findIndex(msg => 
        msg.role === "assistant" && msg.id === msgId && !msg.isWarning
      );
      if (assistantIndex >= 0) {
        const updatedMessage = { 
          ...prev[assistantIndex], 
          thinking
        };
        const newMessages = [
          ...prev.slice(0, assistantIndex), 
          updatedMessage, 
          ...prev.slice(assistantIndex + 1)
        ];
        return newMessages;
      }
      return prev;
    });
  }

  // Hàm gửi tin nhắn và nhận phản hồi
  async function handleSubmit(text?: string) {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || isLoading) return;
    let messageText = text || question;
    if (!messageText || messageText.trim() === '') return;
    setIsLoading(true);
    const messageId = uuidv4();
    console.log("Tạo tin nhắn mới với ID:", messageId);
    latestMessageId.current = messageId;
    receivedFirstToken = false;
    createdAssistantMessageRef.current = false;
    const displayMessage = messageText;
    messageText = messageText.trim();
    if (thinkEnabled) {
      messageText = `${messageText} /think`;
      console.log("Đã thêm hậu tố /think:", messageText);
    } else {
      messageText = `${messageText} /no_think`;
      console.log("Đã thêm hậu tố /no_think:", messageText); 
    }
    // Thêm tin nhắn người dùng vào danh sách
    const newUserMessage: message = { 
      content: displayMessage, 
      role: "user", 
      id: messageId,
      model_type: modelType as "original" | "gemini"
    };
    setMessages(prev => {
      const updatedMessages = [...prev, newUserMessage];
      return updatedMessages;
    });
    // Tạo tin nhắn trống của assistant để hiển thị ngay
    const emptyAssistantMessage: message = {
      content: "",
      role: "assistant",
      id: messageId,
      model_type: modelType as "original" | "gemini"
    };
    setMessages(prev => {
      const updatedMessagesWithAssistant = [...prev, emptyAssistantMessage];
      return updatedMessagesWithAssistant;
    });
    createdAssistantMessageRef.current = true;
    const message = {
      content: messageText,
      session_id: currentSessionId,
      model_type: modelType as "original" | "gemini"
    };
    socket.send(JSON.stringify(message));
    console.log("Đã gửi tin nhắn với session_id:", currentSessionId);
    setTimeout(() => {
      addEmptyAssistantMessage(messageId);
    }, 50);
    setQuestion("");
    try {
      const messageHandler = (event: MessageEvent) => {
        console.log("WebSocket received data:", typeof event.data, event.data.substring ? event.data.substring(0, 100) : event.data);
        if (!receivedFirstToken) {
          receivedFirstToken = true;
          setIsLoading(false);
        }
        if(typeof event.data === 'string' && event.data.includes("[END]")) {
          return;
        }
        try {
          const jsonData = JSON.parse(event.data);
          processJsonData(jsonData);
          setTimeout(() => {
            window.dispatchEvent(new Event('resize'));
          }, 10);
        } catch (error) {
          if (typeof event.data === 'string') {
            updateAssistantMessageWithThinking(messageId, event.data);
          }
        }
      };
      socket.addEventListener("message", messageHandler);
      console.log("Đã đăng ký message handler cho WebSocket");
    } catch (error) {
      setIsLoading(false);
    }
  }

  return (
    <div className="flex flex-col min-w-0 h-dvh bg-background">
      <div className="flex flex-row items-center justify-between px-4 pt-2">
        {socketRef.current
          ? <Header socket={socketRef.current} onSessionChange={handleSessionChange} />
          : <Header onSessionChange={handleSessionChange} />
        }
        <div className="flex items-center gap-2">
          <span className="text-xs">Chọn mô hình:</span>
          <select
            value={modelType}
            onChange={e => handleModelTypeChange(e.target.value)}
            className="border rounded px-2 py-1 text-xs bg-white text-black border-gray-300 dark:bg-[#222] dark:text-white dark:border-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="original">AI-Internal</option>
            <option value="gemini">AI-External</option>
          </select>
        </div>
        <div className="text-xs text-muted-foreground italic ml-4">
          Đang sử dụng: {modelType === "gemini" ? "Gemini" : "Qwen"}
        </div>
      </div>
      <div className="flex flex-col gap-6 flex-1 overflow-y-scroll pt-4 mx-auto w-full max-w-3xl px-4" ref={messagesContainerRef}>
        {messages.length == 0 && <Overview modelType={modelType} />}
        {messages.map((message, _index) => (
          <PreviewMessage
            key={message.id}
            message={message}
            socket={socketRef.current ?? undefined}
            sessionId={currentSessionId}
          />
        ))}
        {isLoading && modelType === "original" && <ThinkingMessage />}
        <div ref={messagesEndRef} className="shrink-0 min-w-[24px] min-h-[24px]"/>
      </div>
      <div className="flex-col mx-auto px-4 bg-background pb-4 md:pb-6 gap-2 w-full max-w-3xl">
        <div className="flex justify-end mb-2">
          <Button
            onClick={toggleThink}
            variant={thinkEnabled ? "default" : "outline"}
            size="sm"
            className="flex items-center gap-1.5 font-medium"
            disabled={modelType === "gemini"}
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
          modelType={modelType}
        />
      </div>
    </div>
  );
};