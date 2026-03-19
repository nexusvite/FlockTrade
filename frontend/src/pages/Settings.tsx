import { useEffect, useState, type FormEvent } from "react";
import api from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { Play, Pause, Save } from "lucide-react";

export default function Settings() {
  const { user } = useAuth();
  const [config, setConfig] = useState({
    symbols: "USDJPYm,EURUSDm",
    lot_size_forex: "1.0",
    lot_size_gold: "0.1",
    tp_pips_forex: "2",
    sl_pips_forex: "5",
    max_daily_losses: "3",
    max_daily_loss_usd: "100",
    scout_model: "anthropic/claude-haiku-4.5",
    confirmer_model: "anthropic/claude-sonnet-4-6",
  });
  const [status, setStatus] = useState<{
    is_paused: boolean;
    is_running: boolean;
  } | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api
      .get("/status/")
      .then((r) => setStatus(r.data))
      .catch(() => {});
    api
      .get("/config/")
      .then((r) => {
        const d = r.data;
        setConfig({
          symbols: Array.isArray(d.symbols) ? d.symbols.join(",") : d.symbols ?? "",
          lot_size_forex: String(d.lot_size_forex ?? "1.0"),
          lot_size_gold: String(d.lot_size_gold ?? "0.1"),
          tp_pips_forex: String(d.tp_pips_forex ?? "2"),
          sl_pips_forex: String(d.sl_pips_forex ?? "5"),
          max_daily_losses: String(d.max_daily_losses ?? "3"),
          max_daily_loss_usd: String(d.max_daily_loss_usd ?? "100"),
          scout_model: d.scout_model ?? "",
          confirmer_model: d.confirmer_model ?? "",
        });
      })
      .catch(() => {});
  }, []);

  if (user?.profile.role !== "admin") {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <p className="text-gray-500">Admin access required.</p>
      </div>
    );
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/config/", {
        symbols: config.symbols.split(",").map((s) => s.trim()),
        lot_size_forex: parseFloat(config.lot_size_forex),
        lot_size_gold: parseFloat(config.lot_size_gold),
        tp_pips_forex: parseInt(config.tp_pips_forex),
        sl_pips_forex: parseInt(config.sl_pips_forex),
        max_daily_losses: parseInt(config.max_daily_losses),
        max_daily_loss_usd: parseFloat(config.max_daily_loss_usd),
        scout_model: config.scout_model,
        confirmer_model: config.confirmer_model,
      });
      setMessage("Settings saved successfully.");
    } catch {
      setMessage("Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  async function togglePause() {
    const action = status?.is_paused ? "resume" : "pause";
    await api.post("/control/", { action });
    setStatus((s) => (s ? { ...s, is_paused: !s.is_paused } : s));
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-2xl font-bold">Bot Settings</h2>

      {/* Bot Control */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4 flex items-center justify-between">
        <div>
          <p className="font-medium">Bot Status</p>
          <p className="text-sm text-gray-400">
            {status?.is_paused ? "Trading paused" : "Trading active"}
          </p>
        </div>
        <button
          onClick={togglePause}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium ${
            status?.is_paused
              ? "bg-green-600 hover:bg-green-700"
              : "bg-yellow-600 hover:bg-yellow-700"
          }`}
        >
          {status?.is_paused ? (
            <>
              <Play size={16} /> Resume
            </>
          ) : (
            <>
              <Pause size={16} /> Pause
            </>
          )}
        </button>
      </div>

      {/* Config Form */}
      <form
        onSubmit={handleSave}
        className="bg-gray-800/50 border border-gray-700 rounded-xl p-6 space-y-4"
      >
        {message && (
          <div className="bg-blue-900/30 border border-blue-800 text-blue-400 text-sm p-3 rounded-lg">
            {message}
          </div>
        )}

        {Object.entries(config).map(([key, value]) => (
          <div key={key}>
            <label className="block text-sm text-gray-400 mb-1 capitalize">
              {key.replace(/_/g, " ")}
            </label>
            <input
              type="text"
              value={value}
              onChange={(e) =>
                setConfig((c) => ({ ...c, [key]: e.target.value }))
              }
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
        ))}

        <button
          type="submit"
          disabled={saving}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-4 py-2 rounded-lg text-sm font-medium"
        >
          <Save size={16} />
          {saving ? "Saving..." : "Save Settings"}
        </button>
      </form>
    </div>
  );
}
