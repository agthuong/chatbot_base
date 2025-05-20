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
import { toast } from "sonner";

// Tạo WebSocket kết nối
// Tự động sử dụng hostname của trang web hiện tại để tạo URL WebSocket
const getWebSocketUrl = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const hostname = window.location.hostname;
  return `${protocol}//${hostname}:8090/`;
};

// const socket = new WebSocket(API_WS_URL);

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

  const socketRef = useRef<WebSocket | null>(null);
  const messageHandlerRef = useRef<any>(null);
  const latestMessageId = useRef<string | null>(null);

  // State để lưu trữ thinking cho tin nhắn hiện tại
  let thinking = "";
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
      if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        const action: WebSocketAction = {
          action: "get_history",
          session_id: sessionId
        };
        socketRef.current.send(JSON.stringify(action));
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
    // Tạo WebSocket connection
    const socket = new WebSocket(getWebSocketUrl());
    socketRef.current = socket;
    
    // WebSocket event handlers
    socket.onopen = (event) => {
      console.log("WebSocket connection opened:", event);
      setSocketConnected(true);
      
      // Gửi yêu cầu lấy thông tin phiên hiện tại nếu đã đăng nhập
      if (isLoggedIn) {
        socket.send(JSON.stringify({
          action: "get_session",
          session_id: currentSessionId
        }));
        console.log("Đã gửi yêu cầu lấy thông tin phiên:", currentSessionId);
      }
    };
    
    socket.onclose = (event) => {
      console.log("WebSocket connection closed:", event);
      setSocketConnected(false);
    };
    
    socket.onerror = (error) => {
      console.error("WebSocket error:", error);
      toast.error("Lỗi kết nối WebSocket. Vui lòng tải lại trang.");
    };
    
    // Cleanup khi component unmount
    return () => {
      console.log("Đóng kết nối WebSocket...");
      socket.close();
    };
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
        // Xử lý thông điệp switch_session_response với lịch sử tin nhắn
        else if (data.action === "switch_session_response" && data.status === "success") {
          console.log("Đã chuyển đổi phiên thành công:", data);
          setCurrentSessionId(data.session_id);
          
          // Nếu đã tải phiên này rồi và có trong bộ nhớ, sử dụng lại
          if (loadedSessions.has(data.session_id) && sessionMessages[data.session_id]) {
            setMessages(sessionMessages[data.session_id]);
            console.log(`Sử dụng ${sessionMessages[data.session_id].length} tin nhắn đã lưu trong bộ nhớ cho phiên ${data.session_id}`);
            return;
          }
          
          // Chuyển đổi lịch sử từ server thành định dạng tin nhắn
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
              [data.session_id]: historyMessages
            }));
            
            // Đánh dấu phiên này đã được tải
            setLoadedSessions(prev => new Set(prev).add(data.session_id));
            
            console.log(`Đã tải ${historyMessages.length} tin nhắn từ server cho phiên ${data.session_id}`);
          } else {
            // Không có lịch sử, đặt messages thành mảng rỗng
            setMessages([]);
            setSessionMessages(prev => ({
              ...prev,
              [data.session_id]: []
            }));
            
            // Đánh dấu phiên này đã được tải
            setLoadedSessions(prev => new Set(prev).add(data.session_id));
            console.log(`Phiên ${data.session_id} không có lịch sử tin nhắn`);
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

    socketRef.current && socketRef.current.addEventListener("message", handleMessage);
    return () => socketRef.current && socketRef.current.removeEventListener("message", handleMessage);
  }, [currentSessionId]);

  const cleanupMessageHandler = () => {
    if (messageHandlerRef.current && socketRef.current) {
      socketRef.current.removeEventListener("message", messageHandlerRef.current);
      messageHandlerRef.current = null;
    }
  };

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
        content: ""
      };
      
      const newMessages = [...prevMessages, emptyAssistantMessage];
      
      // Cập nhật session messages
      setSessionMessages(prevSessions => ({
        ...prevSessions,
        [currentSessionId]: newMessages
      }));
      
      return newMessages;
    });
  }

  // Tiền xử lý nội dung tin nhắn
  function preprocessContent(content: string) {
    if (!content) return "";
    
    // Kiểm tra nếu nội dung đã có HTML
    if (/<[a-z][\s\S]*>/i.test(content)) {
      console.log("Nội dung đã chứa HTML, giữ nguyên định dạng");
      return content;
    }
    
    console.log("Tiền xử lý nội dung tin nhắn:", content.substring(0, 30) + "...");
    
    // Đảm bảo các từ khóa đặc biệt được định dạng đúng
    const specialKeywords = [
      "MKT-SALES", 
      "PROPOSAL", 
      "CONSTRUCTION", 
      "DEFECT-HANDOVER", 
      "AFTERSALE-MAINTENANCE"
    ];
    
    // Xử lý các mốc thời gian đặc biệt (không cần thay đổi)
    let processedContent = content;
    
    // Xử lý các từ khóa đặc biệt
    specialKeywords.forEach(keyword => {
      // Đảm bảo từ khóa giữ nguyên dạng markdown với **
      const regex = new RegExp(`(?<!\\*)\\b${keyword}\\b(?!\\*)`, 'gi');
      processedContent = processedContent.replace(regex, `**${keyword}**`);
    });

    // Xử lý các số được nhắc đến
    processedContent = processedContent.replace(/\b(là|có)\s+(\d+)\b/gi, (match, prefix, number) => {
      return `${prefix} **${number}**`;
    });
    
    return processedContent;
  }

  // Hàm xử lý thông điệp JSON từ WebSocket
  function processJsonData(data: any) {
    try {
      console.log("Đang xử lý JSON data:", data);

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
        console.log("Nhận được tin nhắn có nội dung:", data.content.substring(0, 50));

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
    
    // Dùng functional update để đảm bảo luôn có state mới nhất
    setMessages(prev => {
      // Tìm tin nhắn assistant hiện tại
      const assistantIndex = prev.findIndex(msg => 
        msg.role === "assistant" && msg.id === msgId && !msg.isWarning
      );
      
      // Log để debug
      console.log(`Tìm tin nhắn: assistantIndex=${assistantIndex}`);
      
      if (assistantIndex >= 0) {
        // Cập nhật tin nhắn đã tồn tại với nội dung mới
        const updatedMessage = { 
          ...prev[assistantIndex], 
          content
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
        // Tạo tin nhắn mới nếu không tìm thấy
        const newMessage: message = {
          content,
          role: "assistant",
          id: msgId
        };
        
        const newMessages = [...prev, newMessage];
        
        // Cập nhật sessionMessages
        setSessionMessages(prevSessions => ({
          ...prevSessions,
          [currentSessionId]: newMessages
        }));
        
        return newMessages;
      }
    });
  }

  // Cập nhật tin nhắn assistant với thinking
  function updateAssistantMessageWithThinking(msgId: string, thinking: string) {
    // Dùng functional update để đảm bảo luôn có state mới nhất
    setMessages(prev => {
      // Tìm tin nhắn assistant hiện tại
      const assistantIndex = prev.findIndex(msg => 
        msg.role === "assistant" && msg.id === msgId && !msg.isWarning
      );
      
      if (assistantIndex >= 0) {
        // Cập nhật thinking cho tin nhắn đã tồn tại
        const updatedMessage = { 
          ...prev[assistantIndex], 
          thinking
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
  }

  // Hàm gửi tin nhắn và nhận phản hồi
  async function handleSubmit(text?: string) {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || isLoading) return;

    let messageText = text || question;
    
    // Kiểm tra để đảm bảo rằng messageText không rỗng
    if (!messageText || messageText.trim() === '') return;
    
    // Reset các trạng thái
    setIsLoading(true);
    
    // Tạo và lưu ID tin nhắn mới
    const messageId = uuidv4();
    console.log("Tạo tin nhắn mới với ID:", messageId);
    
    // Lưu messageId hiện tại vào ref để sử dụng cho các tin nhắn từ WebSocket
    latestMessageId.current = messageId;
    
    // Reset các biến trạng thái khác
    receivedFirstToken = false;
    createdAssistantMessageRef.current = false;
    
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
    
    // Đảm bảo dọn dẹp message handler cũ trước khi tạo mới
    cleanupMessageHandler();
    
    // Thêm tin nhắn người dùng vào danh sách
    const newUserMessage: message = { 
      content: displayMessage, 
      role: "user", 
      id: messageId 
    };
    // Sử dụng functional update để đảm bảo luôn có state mới nhất
    setMessages(prev => {
      const updatedMessages = [...prev, newUserMessage];
      
      // Sử dụng setTimeout để tách biệt hai lần cập nhật state
      setTimeout(() => {
        // Cập nhật lịch sử tin nhắn cho phiên hiện tại
        setSessionMessages(prevSessions => ({
          ...prevSessions,
          [currentSessionId]: updatedMessages
        }));
      }, 0);
      
      return updatedMessages;
    });
    
    // Tạo tin nhắn trống của assistant để hiển thị ngay
    const emptyAssistantMessage: message = {
      content: "",
      role: "assistant",
      id: messageId
    };
    
    // Thêm tin nhắn trống của assistant vào danh sách ngay lập tức
    // Sử dụng functional update để đảm bảo luôn có state mới nhất
    setMessages(prev => {
      const updatedMessagesWithAssistant = [...prev, emptyAssistantMessage];
      
      // Sử dụng setTimeout để tách biệt hai lần cập nhật state
      setTimeout(() => {
        // Cập nhật lịch sử tin nhắn cho phiên hiện tại
        setSessionMessages(prevSessions => ({
          ...prevSessions,
          [currentSessionId]: updatedMessagesWithAssistant
        }));
      }, 0);
      
      return updatedMessagesWithAssistant;
    });
    
    createdAssistantMessageRef.current = true;
    
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
      console.log("Đã gửi tin nhắn với session_id:", currentSessionId);
    }
    
    // Thêm đoạn này vào
    setTimeout(() => {
      // Thêm tin nhắn trống cho assistant ngay sau khi gửi tin nhắn
      addEmptyAssistantMessage(messageId);
    }, 50);
    
    // Reset input và trạng thái
    setQuestion("");

    try {
      // Định nghĩa message handler
      const messageHandler = (event: MessageEvent) => {
        // Log dữ liệu nhận được để debug
        console.log("WebSocket received data:", typeof event.data, event.data.substring ? event.data.substring(0, 100) : event.data);
        
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
        
        try {
          // Parse và xử lý dữ liệu JSON từ WebSocket
          const jsonData = JSON.parse(event.data);
          console.log("Đã parse JSON thành công:", jsonData);
          
          // Xử lý dữ liệu JSON
          processJsonData(jsonData);

          // Force re-render bằng cách gửi event resize
          setTimeout(() => {
            window.dispatchEvent(new Event('resize'));
          }, 10);
        } catch (error) {
          console.error("Lỗi khi parse hoặc xử lý JSON:", error);
          
          // Nếu không phải JSON, xử lý như text thông thường
          if (typeof event.data === 'string') {
            updateAssistantMessageWithThinking(messageId, event.data);
          }
        }
      };

      // Đăng ký message handler
      messageHandlerRef.current = messageHandler;
      socket.addEventListener("message", messageHandler);
      
      // Log để kiểm tra message handler đã được đăng ký chưa
      console.log("Đã đăng ký message handler cho WebSocket");
    } catch (error) {
      console.error("WebSocket error:", error);
      setIsLoading(false);
    }
  }

  return (
    <div className="flex flex-col min-w-0 h-dvh bg-background">
      <Header socketRef={socketRef} onSessionChange={handleSessionChange}/>
      <div className="flex flex-col min-w-0 gap-6 flex-1 overflow-y-scroll pt-4" ref={messagesContainerRef}>
        {messages.length == 0 && <Overview />}
        {messages.map((message, _index) => (
          <PreviewMessage
            key={message.id}
            message={message}
            socket={socketRef.current}
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