import { useWebSocket } from "../hooks/useWebSocket";
import { Brain, TrendingUp, AlertCircle } from "lucide-react";

interface FeedItem {
  type: string;
  message?: string;
  symbol?: string;
  action?: string;
  timestamp?: string;
}

const icons: Record<string, React.ReactNode> = {
  trade_update: <TrendingUp size={14} className="text-blue-400" />,
  ai_decision: <Brain size={14} className="text-purple-400" />,
  status_update: <AlertCircle size={14} className="text-yellow-400" />,
};

export function LiveFeed() {
  const { messages } = useWebSocket<FeedItem>("*");

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
      <h3 className="text-sm font-semibold mb-3 text-gray-300">Live Feed</h3>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {messages.length === 0 && (
          <p className="text-xs text-gray-500">Waiting for events...</p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className="flex items-start gap-2 text-xs text-gray-400 animate-fadeIn"
          >
            {icons[msg.type] ?? <AlertCircle size={14} />}
            <span>
              {msg.symbol && (
                <span className="text-white font-medium">{msg.symbol} </span>
              )}
              {msg.action && (
                <span
                  className={
                    msg.action === "BUY"
                      ? "text-profit"
                      : msg.action === "SELL"
                        ? "text-loss"
                        : ""
                  }
                >
                  {msg.action}{" "}
                </span>
              )}
              {msg.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
