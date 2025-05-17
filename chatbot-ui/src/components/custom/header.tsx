import { useState } from "react";
import { ThemeToggle } from "./theme-toggle";
import { Menu, X, MessageSquare } from "lucide-react";
import { Button } from "../ui/button";
import { SessionManager } from "./SessionManager";
import { AnimatePresence, motion } from "framer-motion";

interface HeaderProps {
  socket: WebSocket;
  onSessionChange: (sessionId: string) => void;
}

export const Header: React.FC<HeaderProps> = ({ socket, onSessionChange }) => {
  const [showSidebar, setShowSidebar] = useState(false);

  return (
    <>
      <header className="flex items-center justify-between px-2 sm:px-4 py-2 bg-background text-black dark:text-white w-full border-b">
        <div className="flex items-center space-x-1 sm:space-x-2">
          <Button 
            variant="ghost" 
            size="icon" 
            onClick={() => setShowSidebar(!showSidebar)}
            aria-label="Toggle menu"
          >
            <Menu className="h-5 w-5" />
          </Button>
          <div className="flex items-center space-x-2">
            <MessageSquare className="h-5 w-5" />
            <span className="font-medium">Chat Sessions</span>
          </div>
        </div>
        <div className="flex items-center">
          <ThemeToggle />
        </div>
      </header>

      {/* Sidebar overlay */}
      <AnimatePresence>
        {showSidebar && (
          <motion.div 
            className="fixed inset-0 bg-black/40 z-40 lg:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setShowSidebar(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <AnimatePresence>
        {showSidebar && (
          <motion.div 
            className="fixed inset-y-0 left-0 w-80 bg-background border-r z-50 p-4 overflow-y-auto"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ type: "spring", damping: 20 }}
          >
            <div className="flex justify-between items-center mb-6">
              <h2 className="text-xl font-bold">Menu</h2>
              <Button 
                variant="ghost" 
                size="icon" 
                onClick={() => setShowSidebar(false)}
                aria-label="Close menu"
              >
                <X className="h-5 w-5" />
              </Button>
            </div>

            <SessionManager 
              socket={socket} 
              onSessionChange={(sessionId) => {
                onSessionChange(sessionId);
                setShowSidebar(false);
              }} 
            />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};