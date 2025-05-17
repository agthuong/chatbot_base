import React, { useState, useEffect } from 'react';
import { Session, WebSocketAction } from '../../interfaces/interfaces';
import { Button } from '@/components/ui/button';
import { Plus, Trash2, Edit, Check, X } from 'lucide-react';
import { Input } from '@/components/ui/input';

interface SessionManagerProps {
  socket: WebSocket;
  onSessionChange: (sessionId: string) => void;
}

export function SessionManager({ socket, onSessionChange }: SessionManagerProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState<string>('');
  const [newSessionName, setNewSessionName] = useState<string>('');
  const [creatingSession, setCreatingSession] = useState<boolean>(false);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.action === 'get_sessions_response' && data.status === 'success') {
          setSessions(data.sessions || []);
          setCurrentSessionId(data.current_session_id || '');
          setLoading(false);
        } 
        else if (data.action === 'create_session_response' && data.status === 'success') {
          // Refresh session list after creating a new session
          const action: WebSocketAction = { action: 'get_sessions' };
          socket.send(JSON.stringify(action));
          setCurrentSessionId(data.session_id);
          onSessionChange(data.session_id);
          setCreatingSession(false);
          setNewSessionName('');
        }
        else if (data.action === 'delete_session_response' && data.status === 'success') {
          // Refresh session list after deleting a session
          const action: WebSocketAction = { action: 'get_sessions' };
          socket.send(JSON.stringify(action));
          if (data.new_session_id) {
            setCurrentSessionId(data.new_session_id);
            onSessionChange(data.new_session_id);
          }
        }
        else if (data.action === 'rename_session_response' && data.status === 'success') {
          // Refresh session list after renaming a session
          const action: WebSocketAction = { action: 'get_sessions' };
          socket.send(JSON.stringify(action));
          setEditingSessionId(null);
        }
        else if (data.action === 'switch_session_response' && data.status === 'success') {
          setCurrentSessionId(data.session_id);
        }
        // Xử lý thông điệp init_session_data
        else if (data.action === 'init_session_data' && data.status === 'success') {
          console.log("SessionManager: Nhận dữ liệu khởi tạo phiên", data);
          setSessions(data.sessions || []);
          setCurrentSessionId(data.current_session_id || '');
          setLoading(false);
          // Thông báo thay đổi phiên hiện tại cho component cha
          onSessionChange(data.current_session_id);
        }
        // Xử lý thông điệp sessions_updated
        else if (data.action === 'sessions_updated' && data.status === 'success') {
          console.log("SessionManager: Cập nhật danh sách phiên", data);
          setSessions(data.sessions || []);
          setCurrentSessionId(data.current_session_id || '');
        }
      } catch (error) {
        // Ignore non-JSON messages
      }
    };

    socket.addEventListener('message', handleMessage);

    // Initial fetch of sessions if socket is open
    if (socket.readyState === WebSocket.OPEN) {
      const action: WebSocketAction = { action: 'get_sessions' };
      socket.send(JSON.stringify(action));
    }

    return () => {
      socket.removeEventListener('message', handleMessage);
    };
  }, [socket, onSessionChange]);

  const handleCreateSession = () => {
    setCreatingSession(true);
  };

  const confirmCreateSession = () => {
    const action: WebSocketAction = { 
      action: 'create_session',
      session_name: newSessionName.trim() || undefined
    };
    socket.send(JSON.stringify(action));
  };

  const handleSwitchSession = (sessionId: string) => {
    if (sessionId === currentSessionId) return;
    const action: WebSocketAction = { 
      action: 'switch_session',
      session_id: sessionId
    };
    socket.send(JSON.stringify(action));
    onSessionChange(sessionId);
  };

  const handleDeleteSession = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    if (window.confirm('Bạn có chắc chắn muốn xóa cuộc hội thoại này?')) {
      const action: WebSocketAction = { 
        action: 'delete_session',
        session_id: sessionId
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
      const action: WebSocketAction = { 
        action: 'rename_session',
        session_id: sessionId,
        new_name: editingName.trim()
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
        minute: '2-digit'
      });
    } catch (e) {
      return dateString;
    }
  };

  if (loading) {
    return <div className="p-4 text-center">Đang tải...</div>;
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b">
        <h2 className="text-lg font-bold mb-2">Quản lý hội thoại</h2>
        {creatingSession ? (
          <div className="flex flex-col gap-2">
            <Input
              value={newSessionName}
              onChange={(e) => setNewSessionName(e.target.value)}
              placeholder="Tên hội thoại mới"
              className="w-full"
            />
            <div className="flex gap-2">
              <Button onClick={confirmCreateSession} size="sm" className="flex-1">
                <Check className="h-4 w-4 mr-1" />
                Tạo mới
              </Button>
              <Button 
                onClick={() => setCreatingSession(false)} 
                size="sm" 
                variant="outline" 
                className="flex-1"
              >
                <X className="h-4 w-4 mr-1" />
                Hủy
              </Button>
            </div>
          </div>
        ) : (
          <Button onClick={handleCreateSession} className="w-full">
            <Plus className="h-4 w-4 mr-1" />
            Tạo hội thoại mới
          </Button>
        )}
      </div>
      
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
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
                      >
                        <Check className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8"
                        onClick={handleCancelRename}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 text-slate-500 hover:text-slate-900"
                        onClick={(e) => handleStartRename(session.id, session.name, e)}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-8 w-8 text-red-500 hover:text-red-700"
                        onClick={(e) => handleDeleteSession(session.id, e)}
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