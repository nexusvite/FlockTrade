import { useEffect, useState } from "react";
import api from "../lib/api";

interface SRLevel {
  id: string;
  symbol: string;
  price: number;
  strength: number;
  timeframes: string[];
  session_touches: number;
  direction: string;
  traded: boolean;
}

export default function Levels() {
  const [levels, setLevels] = useState<SRLevel[]>([]);
  const [symbol, setSymbol] = useState("");

  useEffect(() => {
    const params = symbol ? { symbol } : {};
    api.get("/levels/", { params }).then((r) => {
      setLevels(r.data.results ?? r.data);
    });
  }, [symbol]);

  const strengthColor = (s: number) => {
    if (s >= 7) return "text-red-400 bg-red-900/30";
    if (s >= 4) return "text-yellow-400 bg-yellow-900/30";
    return "text-gray-400 bg-gray-700/50";
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">S/R Levels</h2>
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm"
        >
          <option value="">All Symbols</option>
          <option value="USDJPYm">USDJPY</option>
          <option value="EURUSDm">EURUSD</option>
        </select>
      </div>

      <div className="bg-gray-800/50 border border-gray-700 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-700 text-gray-400 text-xs">
              <th className="p-3 text-left">Symbol</th>
              <th className="p-3 text-left">Price</th>
              <th className="p-3 text-left">Strength</th>
              <th className="p-3 text-left">Timeframes</th>
              <th className="p-3 text-left">Touches</th>
              <th className="p-3 text-left">Direction</th>
              <th className="p-3 text-left">Traded</th>
            </tr>
          </thead>
          <tbody>
            {levels.map((level) => (
              <tr
                key={level.id}
                className="border-b border-gray-800 hover:bg-gray-800/50"
              >
                <td className="p-3 font-medium">{level.symbol}</td>
                <td className="p-3 font-mono">{level.price}</td>
                <td className="p-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium ${strengthColor(level.strength)}`}
                  >
                    {level.strength}
                  </span>
                </td>
                <td className="p-3">
                  <div className="flex gap-1">
                    {level.timeframes.map((tf) => (
                      <span
                        key={tf}
                        className="px-1.5 py-0.5 bg-gray-700 rounded text-xs"
                      >
                        {tf}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="p-3">{level.session_touches}</td>
                <td className="p-3 capitalize">{level.direction}</td>
                <td className="p-3">
                  {level.traded ? (
                    <span className="text-yellow-400">Yes</span>
                  ) : (
                    <span className="text-gray-500">No</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
