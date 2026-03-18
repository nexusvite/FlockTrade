interface SRLevel {
  price: number;
  strength: number;
  direction: string;
  timeframes: string[];
  session_touches: number;
  traded: boolean;
}

interface SRMapProps {
  levels: SRLevel[];
  currentPrice?: number;
}

export function SRMap({ levels, currentPrice }: SRMapProps) {
  if (levels.length === 0) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4 text-center text-gray-500 text-sm">
        No S/R levels detected
      </div>
    );
  }

  const sorted = [...levels].sort((a, b) => b.price - a.price);
  const maxStrength = Math.max(...levels.map((l) => l.strength), 1);

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4">
      <h3 className="text-sm font-semibold mb-3 text-gray-300">S/R Map</h3>
      <div className="space-y-1.5">
        {sorted.map((level, i) => {
          const widthPct = (level.strength / maxStrength) * 100;
          const isResistance = level.direction === "resistance";
          const isNearPrice =
            currentPrice &&
            Math.abs(level.price - currentPrice) / currentPrice < 0.001;

          return (
            <div
              key={i}
              className={`flex items-center gap-3 text-xs ${
                isNearPrice ? "ring-1 ring-blue-500 rounded-lg p-1" : "p-1"
              }`}
            >
              <span className="w-20 font-mono text-right text-gray-300">
                {level.price.toFixed(5)}
              </span>
              <div className="flex-1 h-4 bg-gray-700/50 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${
                    isResistance
                      ? "bg-gradient-to-r from-red-600 to-red-400"
                      : "bg-gradient-to-r from-green-600 to-green-400"
                  }`}
                  style={{ width: `${widthPct}%` }}
                />
              </div>
              <span className="w-6 text-center font-bold">
                {level.strength}
              </span>
              <div className="flex gap-0.5">
                {level.timeframes.map((tf) => (
                  <span
                    key={tf}
                    className="px-1 py-0.5 bg-gray-700 rounded text-[10px]"
                  >
                    {tf}
                  </span>
                ))}
              </div>
              {level.traded && (
                <span className="text-yellow-500 text-[10px]">TRADED</span>
              )}
            </div>
          );
        })}
      </div>
      {currentPrice && (
        <div className="mt-3 text-xs text-gray-500 text-center">
          Current price:{" "}
          <span className="text-white font-mono">
            {currentPrice.toFixed(5)}
          </span>
        </div>
      )}
    </div>
  );
}
