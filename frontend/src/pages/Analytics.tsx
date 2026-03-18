import { useEffect, useState } from "react";
import api from "../lib/api";
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

interface PerformanceData {
  win_rate: number;
  total_pnl: number;
  total_trades: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
  by_symbol: Record<string, { wins: number; losses: number; pnl: number }>;
}

export default function Analytics() {
  const [perf, setPerf] = useState<PerformanceData | null>(null);
  const [dailyStats, setDailyStats] = useState<never[]>([]);

  useEffect(() => {
    api.get("/performance/").then((r) => setPerf(r.data));
    api
      .get("/performance/daily/")
      .then((r) => setDailyStats(r.data))
      .catch(() => {});
  }, []);

  const symbolData = perf
    ? Object.entries(perf.by_symbol).map(([symbol, data]) => ({
        symbol,
        ...data,
      }))
    : [];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Analytics</h2>

      {/* Key metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        {[
          { label: "Win Rate", value: `${perf?.win_rate?.toFixed(1) ?? "—"}%` },
          { label: "Total P&L", value: `$${perf?.total_pnl?.toFixed(2) ?? "—"}` },
          { label: "Total Trades", value: perf?.total_trades ?? "—" },
          { label: "Avg P&L", value: `$${perf?.avg_pnl?.toFixed(2) ?? "—"}` },
          { label: "Best Trade", value: `$${perf?.best_trade?.toFixed(2) ?? "—"}` },
          { label: "Worst Trade", value: `$${perf?.worst_trade?.toFixed(2) ?? "—"}` },
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
