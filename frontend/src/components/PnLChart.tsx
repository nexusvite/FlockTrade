import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

interface DayStat {
  date: string;
  pnl: number;
  trades: number;
  wins: number;
}

export function PnLChart({ data }: { data: DayStat[] }) {
  const cumulative = data.reduce<(DayStat & { cumPnl: number })[]>(
    (acc, day) => {
      const prev = acc.length > 0 ? acc[acc.length - 1].cumPnl : 0;
      acc.push({ ...day, cumPnl: prev + day.pnl });
      return acc;
    },
    []
  );

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
      <h3 className="text-sm font-semibold mb-3 text-gray-300">
        Cumulative P&L
      </h3>
      <ResponsiveContainer width="100%" height={250}>
        <AreaChart data={cumulative}>
          <defs>
            <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 11 }} />
          <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #374151",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          <Area
            type="monotone"
            dataKey="cumPnl"
            stroke="#3b82f6"
            fill="url(#pnlGrad)"
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
