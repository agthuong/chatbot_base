export interface message {
    content: string
    role: "user" | "assistant"
    id: string
    thinking?: string
    isWarning?: boolean
}

// Định nghĩa các loại hành động cho WebSocket
export interface WebSocketAction {
    action: string;
    session_id?: string;
    session_name?: string;
    new_name?: string;
    query?: string;
    request_id?: string;
}

// Định nghĩa cấu trúc session
export interface Session {
    id: string;
    name: string;
    created_at: string;
    message_count: number;
}

// Định nghĩa response từ server
export interface WebSocketResponse {
    action: string;
    status: string;
    session_id?: string;
    new_session_id?: string;
}

// Định nghĩa response danh sách phiên
export interface GetSessionsResponse extends WebSocketResponse {
    sessions: Session[];
    current_session_id: string;
}

// Định nghĩa response lịch sử hội thoại
export interface GetHistoryResponse extends WebSocketResponse {
    history: {
        timestamp: string;
        query: string;
        response: string;
    }[];
}