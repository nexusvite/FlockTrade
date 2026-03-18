import { useEffect, useState } from "react";
import api from "../lib/api";
import { Brain } from "lucide-react";

interface AIDecision {
  id: string;
  timestamp: string;
  symbol: string;
  role: string;
  model: string;
  action: string;
  confidence: number;
  reason: string;
  latency_ms: number;
  cost_usd: number;
}

export default function AILog() {
  const [decisions, setDecisions] = useState<AIDecision[]>([]);
  const [role, setRole] = useState<string>("");
  const [costs, setCosts] = useState<{
    total: number;
    by_model: Record<string, number>;
  } | null>(null);

  useEffect(() => {
    const params = role ? { role } : {};
    api.get("/ai/decisions/", { params }).then((r) => {
      setDecisions(r.data.results ?? r.data);
    });
    api.get("/ai/costs/").then((r) => setCosts(r.data)).catch(() => {});
  }, [role]);

  const actionColor = (action: string) => {
    switch (action) {
      case "BUY":
        return "text-profit";
      case "SELL":
        return "text-loss";
      case "CONFIRM":
        return "text-profit";
      case "REJECT":
        return "text-loss";
      default:
        return "text-gray-400";
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Brain className="text-purple-400" /> AI Decision Log
        </h2>
        <div className="flex gap-2">
          {["", "scout", "confirmer"].map((r) => (
            <button
              key={r}
              onClick={() => setRole(r)}
              className={`px-3 py-1.5 text-xs rounded-lg capitalize ${
                role === r
                  ? "bg-purple-600 text-white"
                  : "bg-gray-800 text-gray-400"
              }`}
            >
              {r || "All"}
            </button>
          ))}
        </div>
      </div>

      {costs && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
            <p className="text-xs text-gray-500">Total AI Cost</p>
            <p className="text-lg font-bold text-purple-400">
              ${Number(costs.total).toFixed(4)}
            </p>
          </div>
          {Object.entries(costs.by_model).map(([model, cost]) => (
            <div
              key={model}
              className="bg-gray-800/50 border border-gray-700 rounded-xl p-4"
            >
              <p className="text-xs text-gray-500 truncate">{model}</p>
              <p className="text-lg font-bold">${Number(cost).toFixed(4)}</p>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-3">
        {decisions.map((d) => (
          <div
            key={d.id}
            className="bg-gray-800/50 border border-gray-700 rounded-xl p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <span className="text-xs px-2 py-0.5 rounded-full bg-purple-900/50 text-purple-400 capitalize">
                  {d.role}
                </span>
                <span className="font-medium">{d.symbol}</span>
                <span className={`font-bold ${actionColor(d.action)}`}>
                  {d.action}
                </span>
                <span className="text-sm text-gray-400">
                  {d.confidence}% confidence
                </span>
              </div>
              <div className="text-xs text-gray-500">
                {d.latency_ms}ms · ${Number(d.cost_usd).toFixed(5)}
              </div>
            </div>
            <p className="text-sm text-gray-300">{d.reason}</p>
            <p className="text-xs text-gray-500 mt-2">
              {new Date(d.timestamp).toLocaleString()} · {d.model}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
