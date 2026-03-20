import { TrendingUp, TrendingDown } from "lucide-react";

interface Trade {
  id: string;
  symbol: string;
  type: string;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  entry_time: string;
  exit_time: string | null;
  level_strength: number;
  scout_action: string;
  scout_confidence: number;
  confirmer_action: string;
  confirmer_confidence: number;
  account_type?: string;
  binance_order_id?: string;
}

export function TradeCard({ trade }: { trade: Trade }) {
  const isBuy = trade.type === "BUY";
  const isOpen = !trade.exit_price;
  const pnl = Number(trade.pnl ?? 0);

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4 hover:border-gray-600 transition-colors">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isBuy ? (
            <TrendingUp className="text-profit" size={18} />
          ) : (
            <TrendingDown className="text-loss" size={18} />
          )}
          <span className="font-semibold">{trade.symbol}</span>
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              isBuy
                ? "bg-emerald-900/50 text-emerald-400"
                : "bg-red-900/50 text-red-400"
            }`}
          >
            {trade.type}
          </span>
        </div>
        {isOpen ? (
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-900/50 text-blue-400">
            OPEN
          </span>
        ) : (
          <span
            className={`font-bold ${pnl >= 0 ? "text-profit" : "text-loss"}`}
          >
            {pnl >= 0 ? "+" : ""}
            {pnl.toFixed(2)}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs text-gray-400">
        <div>
          Entry: <span className="text-white">{trade.entry_price}</span>
        </div>
        <div>
          S/R Str:{" "}
          <span className="text-white">{trade.level_strength}</span>
        </div>
        <div>
          Scout:{" "}
          <span className="text-white">
            {trade.scout_confidence}%
          </span>
        </div>
        <div>
          Confirm:{" "}
          <span className="text-white">
            {trade.confirmer_confidence}%
          </span>
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
        <span>{new Date(trade.entry_time).toLocaleString()}</span>
        {trade.binance_order_id && (
          <span className="font-mono text-gray-600 truncate ml-2" title={trade.binance_order_id}>
            #{trade.binance_order_id.slice(-8)}
          </span>
        )}
      </div>
    </div>
  );
}
