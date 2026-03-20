import { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { PnLChart } from "../components/PnLChart";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

const fmt = (v: unknown, d = 2) => v != null ? Number(v).toFixed(d) : "\u2014";

interface PerformanceData {
  win_rate: number;
  total_pnl: number;
  total_trades: number;
  avg_pnl_per_trade: number;
  best_trade: number;
  worst_trade: number;
  by_symbol: { symbol: string; wins: number; losses: number; pnl: number }[];
}

export default function Analytics() {
  const { accountType } = useAuth();
  const [perf, setPerf] = useState<PerformanceData | null>(null);
  const [dailyStats, setDailyStats] = useState<never[]>([]);

  useEffect(() => {
    api.get("/performance/").then((r) => setPerf(r.data));
    api
      .get("/daily-stats/")
      .then((r) => setDailyStats(r.data.results ?? r.data))
      .catch(() => {});
  }, [accountType]);

  const symbolData = perf?.by_symbol ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Analytics</h2>
        <span
          className={`text-xs font-bold px-2.5 py-1 rounded-full ${
            accountType === "DEMO"
              ? "bg-yellow-900/50 text-yellow-400 border border-yellow-700"
              : "bg-green-900/50 text-green-400 border border-green-700"
          }`}
        >
          {accountType}
        </span>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        {[
          { label: "Win Rate", value: `${fmt(perf?.win_rate, 1)}%` },
          { label: "Total P&L", value: `$${fmt(perf?.total_pnl)}` },
          { label: "Total Trades", value: perf?.total_trades ?? "\u2014" },
          { label: "Avg P&L", value: `$${fmt(perf?.avg_pnl_per_trade)}` },
          { label: "Best Trade", value: `$${fmt(perf?.best_trade)}` },
          { label: "Worst Trade", value: `$${fmt(perf?.worst_trade)}` },
        ].map((m) => (
          <div
            key={m.label}
            className="bg-gray-800/50 border border-gray-700 rounded-xl p-3"
          >
            <p className="text-xs text-gray-500">{m.label}</p>
            <p className="text-lg font-bold">{m.value}</p>
          </div>
        ))}
      </div>

      {/* P&L Chart */}
      <PnLChart data={dailyStats} />

      {/* Per-Symbol Performance */}
      {symbolData.length > 0 && (
        <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
          <h3 className="text-sm font-semibold mb-3 text-gray-300">
            P&L by Symbol
          </h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={symbolData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis
                dataKey="symbol"
                tick={{ fill: "#6b7280", fontSize: 11 }}
              />
              <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: 8,
                }}
              />
              <Bar dataKey="pnl" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
