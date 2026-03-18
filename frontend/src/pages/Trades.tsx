import { useEffect, useState } from "react";
import api from "../lib/api";
import { TradeCard } from "../components/TradeCard";

export default function Trades() {
  const [trades, setTrades] = useState<never[]>([]);
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);

  useEffect(() => {
    const params: Record<string, string | number> = { page };
    if (filter === "open") params.is_open = "true";
    if (filter === "closed") params.is_open = "false";

    api.get("/trades/", { params }).then((r) => {
      setTrades(r.data.results ?? r.data);
      setHasNext(!!r.data.next);
    });
  }, [filter, page]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Trade History</h2>
        <div className="flex gap-2">
          {(["all", "open", "closed"] as const).map((f) => (
            <button
              key={f}
              onClick={() => {
                setFilter(f);
                setPage(1);
              }}
              className={`px-3 py-1.5 text-xs rounded-lg capitalize ${
                filter === f
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:text-white"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {trades.map((trade: { id: string }) => (
          <TradeCard key={trade.id} trade={trade as never} />
        ))}
      </div>

      {trades.length === 0 && (
        <p className="text-center text-gray-500 py-12">No trades found.</p>
      )}

      <div className="flex justify-center gap-3">
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page === 1}
          className="px-4 py-2 text-sm bg-gray-800 rounded-lg disabled:opacity-30"
        >
          Previous
        </button>
        <span className="px-4 py-2 text-sm text-gray-400">Page {page}</span>
        <button
          onClick={() => setPage((p) => p + 1)}
          disabled={!hasNext}
          className="px-4 py-2 text-sm bg-gray-800 rounded-lg disabled:opacity-30"
        >
          Next
        </button>
      </div>
    </div>
  );
}
