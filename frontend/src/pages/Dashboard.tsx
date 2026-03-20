import { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { TradeCard } from "../components/TradeCard";
import { PnLChart } from "../components/PnLChart";
import { LiveFeed } from "../components/LiveFeed";
import {
  DollarSign,
  TrendingUp,
  Activity,
  BarChart3,
  Wifi,
  WifiOff,
} from "lucide-react";

interface BotStatus {
  is_running: boolean;
  is_paused: boolean;
  connected_to_exchange: boolean;
  account_balance: number;
  account_equity: number;
  last_scan_time: string | null;
}

const fmt = (v: unknown, d = 2) => v != null ? Number(v).toFixed(d) : "\u2014";

export default function Dashboard() {
  const { accountType } = useAuth();
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [trades, setTrades] = useState<never[]>([]);
  const [stats, setStats] = useState<never[]>([]);
  const [performance, setPerformance] = useState<{
    win_rate: number;
    total_pnl: number;
    total_trades: number;
  } | null>(null);

  useEffect(() => {
    Promise.all([
      api.get("/status/"),
      api.get("/trades/?page_size=5"),
      api.get("/performance/"),
    ]).then(([s, t, p]) => {
      setStatus(s.data);
      setTrades(t.data.results ?? t.data);
      setPerformance(p.data);
    });

    api.get("/daily-stats/").then((r) => setStats(r.data.results ?? r.data)).catch(() => {});
  }, [accountType]);

  const cards = [
    {
      label: "Balance",
      value: `$${fmt(status?.account_balance)}`,
      icon: DollarSign,
      color: "text-blue-400",
    },
    {
      label: "Total P&L",
      value: `$${fmt(performance?.total_pnl)}`,
      icon: TrendingUp,
      color: Number(performance?.total_pnl ?? 0) >= 0 ? "text-profit" : "text-loss",
    },
    {
      label: "Win Rate",
      value: `${fmt(performance?.win_rate, 1)}%`,
      icon: BarChart3,
      color: "text-purple-400",
    },
    {
      label: "Binance",
      value: status?.connected_to_exchange ? "Connected" : "Disconnected",
      icon: status?.connected_to_exchange ? Wifi : WifiOff,
      color: status?.connected_to_exchange ? "text-profit" : "text-loss",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Dashboard</h2>
        <div className="flex items-center gap-3">
          <span
            className={`text-xs font-bold px-2.5 py-1 rounded-full ${
              accountType === "DEMO"
                ? "bg-yellow-900/50 text-yellow-400 border border-yellow-700"
                : "bg-green-900/50 text-green-400 border border-green-700"
            }`}
          >
            {accountType}
          </span>
          <div className="flex items-center gap-2">
            <Activity
              size={14}
              className={
                status?.is_running && !status.is_paused
                  ? "text-profit animate-pulse"
                  : "text-gray-500"
              }
            />
            <span className="text-sm text-gray-400">
              {status?.is_paused
                ? "Paused"
                : status?.is_running
                  ? "Running"
                  : "Stopped"}
            </span>
          </div>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className="bg-gray-800/50 border border-gray-700 rounded-xl p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-500">{card.label}</span>
              <card.icon size={16} className={card.color} />
            </div>
            <p className={`text-xl font-bold ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </div>

      {/* Charts + Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <PnLChart data={stats} />
        </div>
        <LiveFeed />
      </div>

      {/* Recent Trades */}
      <div>
        <h3 className="text-lg font-semibold mb-3">Recent Trades</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {trades.map((trade: { id: string }) => (
            <TradeCard key={trade.id} trade={trade as never} />
          ))}
        </div>
      </div>
    </div>
  );
}
