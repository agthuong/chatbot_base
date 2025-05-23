import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Session, WebSocketAction } from '../../interfaces/interfaces';
import { Button } from '@/components/ui/button';
import { Plus, Trash2, Edit, Check, X, RefreshCw } from 'lucide-react';
import { Input } from '@/components/ui/input';

// Custom hook quản lý session tối ưu
function useSessions(socket: WebSocket | null) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const lastFetchRef = useRef<number>(0);

  // Lắng nghe message từ server
  useEffect(() => {
    if (!socket) return;
    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.action === 'get_sessions_response' && data.status === 'success') {
          setSessions(data.sessions || []);
          setCurrentSessionId(data.current_session_id || '');
          setLoading(false);
          lastFetchRef.current = Date.now();
        }
        // ... các action khác nếu cần
      } catch {}
    };
    socket.addEventListener('message', handleMessage);
    return () => socket.removeEventListener('message', handleMessage);
  }, [socket]);

  // Hàm refresh session, chỉ gửi nếu đã lâu không cập nhật
  const refreshSessions = useCallback(() => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    // Nếu đã lấy trong 5s gần nhất thì không gửi lại
    if (Date.now() - lastFetchRef.current < 5000) return;
    setLoading(true);
    socket.send(JSON.stringify({ action: 'get_sessions' }));
  }, [socket]);

  // Gọi refreshSessions khi socket open lần đầu
  useEffect(() => {
    if (!socket) return;
    const handleOpen = () => refreshSessions();
    socket.addEventListener('open', handleOpen);
    if (socket.readyState === WebSocket.OPEN) refreshSessions();
    return () => socket.removeEventListener('open', handleOpen);
  }, [socket, refreshSessions]);

  return {
    sessions,
    currentSessionId,
    loading,
    refreshSessions,
    setCurrentSessionId
  };
}

interface SessionManagerProps {
  socket: WebSocket;
  onSessionChange: (sessionId: string) => void;
}

export function SessionManager({ socket, onSessionChange }: SessionManagerProps) {
  const {
    sessions,
    currentSessionId,
    loading,
    refreshSessions,
    setCurrentSessionId,
  } = useSessions(socket);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState<string>('');
  const [newSessionName, setNewSessionName] = useState<string>('');
  const [creatingSession, setCreatingSession] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<boolean>(false);

  // Lắng nghe các action create/delete/rename để refresh lại session
  useEffect(() => {
    if (!socket) return;
    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if ([
          'create_session_response',
          'delete_session_response',
          'rename_session_response',
          'switch_session_response',
        ].includes(data.action) && data.status === 'success') {
          refreshSessions();
          setActionLoading(false);
          setCreatingSession(false);
          setEditingSessionId(null);
          if (data.session_id) {
            setCurrentSessionId(data.session_id);
            onSessionChange(data.session_id);
          } else if (data.new_session_id) {
            setCurrentSessionId(data.new_session_id);
            onSessionChange(data.new_session_id);
          }
        }
      } catch {}
    };
    socket.addEventListener('message', handleMessage);
    return () => socket.removeEventListener('message', handleMessage);
  }, [socket, refreshSessions, onSessionChange, setCurrentSessionId]);

  const handleCreateSession = () => {
    setCreatingSession(true);
  };

  const confirmCreateSession = () => {
    if (!newSessionName.trim()) return;
    setActionLoading(true);
    const action: WebSocketAction = {
      action: 'create_session',
      session_name: newSessionName.trim(),
    };
    socket.send(JSON.stringify(action));
    setNewSessionName('');
  };

  const handleSwitchSession = (sessionId: string) => {
    if (sessionId === currentSessionId) return;
    setActionLoading(true);
    const action: WebSocketAction = {
      action: 'switch_session',
      session_id: sessionId,
    };
    socket.send(JSON.stringify(action));
    onSessionChange(sessionId);
  };

  const handleDeleteSession = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    if (window.confirm('Bạn có chắc chắn muốn xóa cuộc hội thoại này?')) {
      setActionLoading(true);
      const action: WebSocketAction = {
        action: 'delete_session',
        session_id: sessionId,
      };
      socket.send(JSON.stringify(action));
    }
  };

  const handleStartRename = (sessionId: string, currentName: string, event: React.MouseEvent) => {
    event.stopPropagation();
    setEditingSessionId(sessionId);
    setEditingName(currentName);
  };

  const handleCancelRename = () => {
    setEditingSessionId(null);
  };

  const handleConfirmRename = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    if (editingName.trim()) {
      setActionLoading(true);
      const action: WebSocketAction = {
        action: 'rename_session',
        session_id: sessionId,
        new_name: editingName.trim(),
      };
      socket.send(JSON.stringify(action));
    } else {
      setEditingSessionId(null);
    }
  };

  const formatDate = (dateString: string) => {
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch (e) {
      return dateString;
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b flex items-center justify-between">
        <h2 className="text-lg font-bold mb-2">Quản lý hội thoại</h2>
        <Button onClick={refreshSessions} size="icon" variant="ghost" title="Làm mới danh sách" className="ml-2">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </div>
      <div className="p-4">
        {creatingSession ? (
          <div className="flex flex-col gap-2">
            <Input
              value={newSessionName}
              onChange={(e) => setNewSessionName(e.target.value)}
              placeholder="Tên hội thoại mới"
              className="w-full"
              disabled={actionLoading}
            />
            <div className="flex gap-2">
              <Button 
                onClick={confirmCreateSession} 
                size="sm" 
                className="flex-1 bg-blue-600 hover:bg-blue-700 text-white dark:bg-blue-500 dark:hover:bg-blue-400 dark:text-white" 
                disabled={actionLoading}
              >
                <Check className="h-4 w-4 mr-1" />
                Tạo mới
              </Button>
              <Button 
                onClick={() => setCreatingSession(false)} 
                size="sm" 
                variant="outline" 
                className="flex-1"
                disabled={actionLoading}
              >
                <X className="h-4 w-4 mr-1" />
                Hủy
              </Button>
            </div>
          </div>
        ) : (
          <Button 
            onClick={handleCreateSession} 
            className="w-full bg-blue-600 hover:bg-blue-700 text-white dark:bg-blue-500 dark:hover:bg-blue-400 dark:text-white" 
            disabled={actionLoading}
          >
            <Plus className="h-4 w-4 mr-1" />
            Tạo hội thoại mới
          </Button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-4 text-center text-gray-500">Đang tải...</div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-center text-slate-500">
            Không có hội thoại nào
          </div>
        ) : (
          <div className="space-y-1 p-2">
            {sessions.map((session) => (
              <div
                key={session.id}
                onClick={() => handleSwitchSession(session.id)}
                className={`p-3 rounded-md cursor-pointer flex items-center justify-between ${
                  session.id === currentSessionId 
                    ? 'bg-primary/10 border-l-4 border-primary' 
                    : 'hover:bg-muted transition-colors'
                }`}
              >
                <div className="flex-1 overflow-hidden">
                  {editingSessionId === session.id ? (
                    <Input
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      autoFocus
                      className="w-full"
                      disabled={actionLoading}
                    />
                  ) : (
                    <div>
                      <div className="font-medium text-sm truncate">{session.name}</div>
                      <div className="text-xs text-slate-500">
                        {formatDate(session.created_at)} · {session.message_count} tin nhắn
                      </div>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  {editingSessionId === session.id ? (
                    <>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8"
                        onClick={(e) => handleConfirmRename(session.id, e)}
                        disabled={actionLoading}
                      >
                        <Check className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8"
                        onClick={handleCancelRename}
                        disabled={actionLoading}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 hover:text-slate-900"
                        onClick={(e) => handleStartRename(session.id, session.name, e)}
                        disabled={actionLoading}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 hover:text-red-700"
                        onClick={(e) => handleDeleteSession(session.id, e)}
                        disabled={actionLoading}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
} 