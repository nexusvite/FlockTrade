import { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import {
  Play,
  Pause,
  Server,
  Brain,
  Shield,
  Clock,
  BarChart3,
  Plus,
  Trash2,
  Eye,
  EyeOff,
} from "lucide-react";
import { CollapsibleSection } from "../components/settings/CollapsibleSection";
import { FieldInput } from "../components/settings/FieldInput";

interface GlobalConfig {
  mt5_broker: string;
  mt5_account: string;
  mt5_password: string;
  mt5_server: string;
  mt5_host: string;
  mt5_port: number;
  openrouter_api_key: string;
  scout_model: string;
  confirmer_model: string;
  ai_timeout: number;
  max_daily_losses: number;
  max_daily_loss_usd: string;
  asia_start: number;
  asia_end: number;
  london_start: number;
  london_end: number;
  ny_start: number;
  ny_end: number;
  lot_size_forex: string;
  lot_size_gold: string;
  tp_pips_forex: number;
  sl_pips_forex: number;
  tp_pips_gold: number;
  sl_pips_gold: number;
}

interface SymbolRow {
  id: number;
  symbol: string;
  enabled: boolean;
  lot_size: string | null;
  tp_pips: number | null;
  sl_pips: number | null;
  max_spread_pips: string | null;
  instrument_type: string;
}

interface BotStatus {
  is_paused: boolean;
  is_running: boolean;
}

export default function Settings() {
  const { user } = useAuth();
  const [, setGc] = useState<GlobalConfig | null>(null);
  const [symbols, setSymbols] = useState<SymbolRow[]>([]);
  const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  // Editable copies (strings for input binding)
  const [mt5, setMt5] = useState({
    mt5_broker: "",
    mt5_account: "",
    mt5_password: "",
    mt5_server: "",
    mt5_host: "",
    mt5_port: "",
  });
  const [ai, setAi] = useState({
    openrouter_api_key: "",
    scout_model: "",
    confirmer_model: "",
    ai_timeout: "",
  });
  const [risk, setRisk] = useState({
    max_daily_losses: "",
    max_daily_loss_usd: "",
  });
  const [sessions, setSessions] = useState({
    asia_start: "",
    asia_end: "",
    london_start: "",
    london_end: "",
    ny_start: "",
    ny_end: "",
  });
  const [defaults, setDefaults] = useState({
    lot_size_forex: "",
    lot_size_gold: "",
    tp_pips_forex: "",
    sl_pips_forex: "",
    tp_pips_gold: "",
    sl_pips_gold: "",
  });

  const [showPassword, setShowPassword] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");

  useEffect(() => {
    api.get("/status/").then((r) => setBotStatus(r.data)).catch(() => {});
    api
      .get("/config/")
      .then((r) => {
        const g = r.data.global;
        setGc(g);
        setMt5({
          mt5_broker: g.mt5_broker ?? "custom",
          mt5_account: g.mt5_account ?? "",
          mt5_password: g.mt5_password ?? "",
          mt5_server: g.mt5_server ?? "",
          mt5_host: g.mt5_host ?? "",
          mt5_port: String(g.mt5_port ?? 8001),
        });
        setAi({
          openrouter_api_key: g.openrouter_api_key ?? "",
          scout_model: g.scout_model ?? "",
          confirmer_model: g.confirmer_model ?? "",
          ai_timeout: String(g.ai_timeout ?? 15),
        });
        setRisk({
          max_daily_losses: String(g.max_daily_losses ?? 3),
          max_daily_loss_usd: String(g.max_daily_loss_usd ?? 100),
        });
        setSessions({
          asia_start: String(g.asia_start ?? 1),
          asia_end: String(g.asia_end ?? 6),
          london_start: String(g.london_start ?? 8),
          london_end: String(g.london_end ?? 12),
          ny_start: String(g.ny_start ?? 13),
          ny_end: String(g.ny_end ?? 20),
        });
        setDefaults({
          lot_size_forex: String(g.lot_size_forex ?? "1.0"),
          lot_size_gold: String(g.lot_size_gold ?? "0.1"),
          tp_pips_forex: String(g.tp_pips_forex ?? 2),
          sl_pips_forex: String(g.sl_pips_forex ?? 5),
          tp_pips_gold: String(g.tp_pips_gold ?? 20),
          sl_pips_gold: String(g.sl_pips_gold ?? 50),
        });
        setSymbols(r.data.symbols ?? []);
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

  function flash(msg: string) {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  }

  async function saveSection(section: string, payload: Record<string, unknown>) {
    setSaving(section);
    try {
      await api.patch("/config/", payload);
      flash(`${section} saved.`);
    } catch {
      flash(`Failed to save ${section}.`);
    } finally {
      setSaving(null);
    }
  }

  async function togglePause() {
    const action = botStatus?.is_paused ? "resume" : "pause";
    await api.post("/control/", { action });
    setBotStatus((s) => (s ? { ...s, is_paused: !s.is_paused } : s));
  }

  // Symbol CRUD
  async function addSymbol() {
    if (!newSymbol.trim()) return;
    try {
      const r = await api.post("/config/symbols/", { symbol: newSymbol.trim() });
      setSymbols((s) => [...s, r.data]);
      setNewSymbol("");
    } catch {
      flash("Failed to add symbol.");
    }
  }

  async function updateSymbol(symbol: string, data: Partial<SymbolRow>) {
    try {
      const r = await api.patch(`/config/symbols/${symbol}/`, data);
      setSymbols((s) => s.map((row) => (row.symbol === symbol ? r.data : row)));
    } catch {
      flash(`Failed to update ${symbol}.`);
    }
  }

  async function deleteSymbol(symbol: string) {
    try {
      await api.delete(`/config/symbols/${symbol}/`);
      setSymbols((s) => s.filter((row) => row.symbol !== symbol));
    } catch {
      flash(`Failed to delete ${symbol}.`);
    }
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <h2 className="text-2xl font-bold">Bot Settings</h2>

      {message && (
        <div className="bg-blue-900/30 border border-blue-800 text-blue-400 text-sm p-3 rounded-lg">
          {message}
        </div>
      )}

      {/* Bot Control */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4 flex items-center justify-between">
        <div>
          <p className="font-medium">Bot Status</p>
          <p className="text-sm text-gray-400">
            {botStatus?.is_paused ? "Trading paused" : "Trading active"}
          </p>
        </div>
        <button
          onClick={togglePause}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium ${
            botStatus?.is_paused
              ? "bg-green-600 hover:bg-green-700"
              : "bg-yellow-600 hover:bg-yellow-700"
          }`}
        >
          {botStatus?.is_paused ? (
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

      {/* MT5 Connection */}
      <CollapsibleSection
        title="MT5 Connection"
        icon={<Server size={16} className="text-blue-400" />}
        onSave={() =>
          saveSection("MT5", {
            mt5_broker: mt5.mt5_broker,
            mt5_account: mt5.mt5_account,
            mt5_password: mt5.mt5_password,
            mt5_server: mt5.mt5_server,
            mt5_host: mt5.mt5_host,
            mt5_port: parseInt(mt5.mt5_port) || 8001,
          })
        }
        saving={saving === "MT5"}
        defaultOpen
      >
        <div>
          <label className="block text-xs text-gray-400 mb-1">Broker</label>
          <select
            value={mt5.mt5_broker}
            onChange={(e) => setMt5((s) => ({ ...s, mt5_broker: e.target.value }))}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="exness">Exness</option>
            <option value="ftmo">FTMO</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        <FieldInput
          label="Account"
          value={mt5.mt5_account}
          onChange={(v) => setMt5((s) => ({ ...s, mt5_account: v }))}
        />
        <div>
          <label className="block text-xs text-gray-400 mb-1">Password</label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={mt5.mt5_password}
              onChange={(e) => setMt5((s) => ({ ...s, mt5_password: e.target.value }))}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
            >
              {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
        <FieldInput
          label="Server"
          value={mt5.mt5_server}
          onChange={(v) => setMt5((s) => ({ ...s, mt5_server: v }))}
        />
        <FieldInput
          label="Host"
          value={mt5.mt5_host}
          onChange={(v) => setMt5((s) => ({ ...s, mt5_host: v }))}
        />
        <FieldInput
          label="Port"
          value={mt5.mt5_port}
          onChange={(v) => setMt5((s) => ({ ...s, mt5_port: v }))}
          type="number"
        />
      </CollapsibleSection>

      {/* AI Configuration */}
      <CollapsibleSection
        title="AI Configuration"
        icon={<Brain size={16} className="text-purple-400" />}
        onSave={() =>
          saveSection("AI", {
            openrouter_api_key: ai.openrouter_api_key,
            scout_model: ai.scout_model,
            confirmer_model: ai.confirmer_model,
            ai_timeout: parseInt(ai.ai_timeout) || 15,
          })
        }
        saving={saving === "AI"}
      >
        <div className="sm:col-span-2">
          <label className="block text-xs text-gray-400 mb-1">OpenRouter API Key</label>
          <div className="relative">
            <input
              type={showApiKey ? "text" : "password"}
              value={ai.openrouter_api_key}
              onChange={(e) => setAi((s) => ({ ...s, openrouter_api_key: e.target.value }))}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none pr-10"
              placeholder="sk-or-..."
            />
            <button
              type="button"
              onClick={() => setShowApiKey(!showApiKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
            >
              {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
        <FieldInput
          label="Scout Model"
          value={ai.scout_model}
          onChange={(v) => setAi((s) => ({ ...s, scout_model: v }))}
        />
        <FieldInput
          label="Confirmer Model"
          value={ai.confirmer_model}
          onChange={(v) => setAi((s) => ({ ...s, confirmer_model: v }))}
        />
        <FieldInput
          label="AI Timeout (seconds)"
          value={ai.ai_timeout}
          onChange={(v) => setAi((s) => ({ ...s, ai_timeout: v }))}
          type="number"
        />
      </CollapsibleSection>

      {/* Risk Management */}
      <CollapsibleSection
        title="Risk Management"
        icon={<Shield size={16} className="text-red-400" />}
        onSave={() =>
          saveSection("Risk", {
            max_daily_losses: parseInt(risk.max_daily_losses) || 3,
            max_daily_loss_usd: parseFloat(risk.max_daily_loss_usd) || 100,
          })
        }
        saving={saving === "Risk"}
      >
        <FieldInput
          label="Max Daily Losses"
          value={risk.max_daily_losses}
          onChange={(v) => setRisk((s) => ({ ...s, max_daily_losses: v }))}
          type="number"
        />
        <FieldInput
          label="Max Daily Loss (USD)"
          value={risk.max_daily_loss_usd}
          onChange={(v) => setRisk((s) => ({ ...s, max_daily_loss_usd: v }))}
          type="number"
        />
      </CollapsibleSection>

      {/* Session Hours */}
      <CollapsibleSection
        title="Session Hours (UTC)"
        icon={<Clock size={16} className="text-yellow-400" />}
        onSave={() =>
          saveSection("Sessions", {
            asia_start: parseInt(sessions.asia_start),
            asia_end: parseInt(sessions.asia_end),
            london_start: parseInt(sessions.london_start),
            london_end: parseInt(sessions.london_end),
            ny_start: parseInt(sessions.ny_start),
            ny_end: parseInt(sessions.ny_end),
          })
        }
        saving={saving === "Sessions"}
      >
        <FieldInput
          label="Asia Start"
          value={sessions.asia_start}
          onChange={(v) => setSessions((s) => ({ ...s, asia_start: v }))}
          type="number"
        />
        <FieldInput
          label="Asia End"
          value={sessions.asia_end}
          onChange={(v) => setSessions((s) => ({ ...s, asia_end: v }))}
          type="number"
        />
        <FieldInput
          label="London Start"
          value={sessions.london_start}
          onChange={(v) => setSessions((s) => ({ ...s, london_start: v }))}
          type="number"
        />
        <FieldInput
          label="London End"
          value={sessions.london_end}
          onChange={(v) => setSessions((s) => ({ ...s, london_end: v }))}
          type="number"
        />
        <FieldInput
          label="New York Start"
          value={sessions.ny_start}
          onChange={(v) => setSessions((s) => ({ ...s, ny_start: v }))}
          type="number"
        />
        <FieldInput
          label="New York End"
          value={sessions.ny_end}
          onChange={(v) => setSessions((s) => ({ ...s, ny_end: v }))}
          type="number"
        />
      </CollapsibleSection>

      {/* Instrument Defaults */}
      <CollapsibleSection
        title="Instrument Defaults"
        icon={<BarChart3 size={16} className="text-green-400" />}
        onSave={() =>
          saveSection("Defaults", {
            lot_size_forex: parseFloat(defaults.lot_size_forex),
            lot_size_gold: parseFloat(defaults.lot_size_gold),
            tp_pips_forex: parseInt(defaults.tp_pips_forex),
            sl_pips_forex: parseInt(defaults.sl_pips_forex),
            tp_pips_gold: parseInt(defaults.tp_pips_gold),
            sl_pips_gold: parseInt(defaults.sl_pips_gold),
          })
        }
        saving={saving === "Defaults"}
      >
        <FieldInput
          label="Forex Lot Size"
          value={defaults.lot_size_forex}
          onChange={(v) => setDefaults((s) => ({ ...s, lot_size_forex: v }))}
          type="number"
        />
        <FieldInput
          label="Gold Lot Size"
          value={defaults.lot_size_gold}
          onChange={(v) => setDefaults((s) => ({ ...s, lot_size_gold: v }))}
          type="number"
        />
        <FieldInput
          label="Forex TP (pips)"
          value={defaults.tp_pips_forex}
          onChange={(v) => setDefaults((s) => ({ ...s, tp_pips_forex: v }))}
          type="number"
        />
        <FieldInput
          label="Forex SL (pips)"
          value={defaults.sl_pips_forex}
          onChange={(v) => setDefaults((s) => ({ ...s, sl_pips_forex: v }))}
          type="number"
        />
        <FieldInput
          label="Gold TP (pips)"
          value={defaults.tp_pips_gold}
          onChange={(v) => setDefaults((s) => ({ ...s, tp_pips_gold: v }))}
          type="number"
        />
        <FieldInput
          label="Gold SL (pips)"
          value={defaults.sl_pips_gold}
          onChange={(v) => setDefaults((s) => ({ ...s, sl_pips_gold: v }))}
          type="number"
        />
      </CollapsibleSection>

      {/* Symbol Configuration Table */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-xl overflow-hidden">
        <div className="px-5 py-3 flex items-center justify-between border-b border-gray-700/50">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <BarChart3 size={16} className="text-cyan-400" />
            Per-Symbol Configuration
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-700/50">
                <th className="px-4 py-2 text-left">Symbol</th>
                <th className="px-4 py-2 text-left">Type</th>
                <th className="px-4 py-2 text-center">Enabled</th>
                <th className="px-4 py-2 text-right">Lot Size</th>
                <th className="px-4 py-2 text-right">TP Pips</th>
                <th className="px-4 py-2 text-right">SL Pips</th>
                <th className="px-4 py-2 text-right">Max Spread</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {symbols.map((row) => (
                <tr key={row.symbol} className="border-b border-gray-700/30 hover:bg-gray-700/20">
                  <td className="px-4 py-2 font-mono font-medium">{row.symbol}</td>
                  <td className="px-4 py-2">
                    <span className="px-1.5 py-0.5 rounded bg-gray-700 text-[10px]">
                      {row.instrument_type}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={row.enabled}
                      onChange={(e) => updateSymbol(row.symbol, { enabled: e.target.checked })}
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="number"
                      step="0.01"
                      value={row.lot_size ?? ""}
                      placeholder="default"
                      onChange={(e) =>
                        setSymbols((s) =>
                          s.map((r) =>
                            r.symbol === row.symbol
                              ? { ...r, lot_size: e.target.value || null }
                              : r,
                          ),
                        )
                      }
                      onBlur={() =>
                        updateSymbol(row.symbol, {
                          lot_size: row.lot_size ? row.lot_size : null,
                        })
                      }
                      className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-right text-xs focus:border-blue-500 focus:outline-none"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="number"
                      value={row.tp_pips ?? ""}
                      placeholder="default"
                      onChange={(e) =>
                        setSymbols((s) =>
                          s.map((r) =>
                            r.symbol === row.symbol
                              ? { ...r, tp_pips: e.target.value ? parseInt(e.target.value) : null }
                              : r,
                          ),
                        )
                      }
                      onBlur={() => updateSymbol(row.symbol, { tp_pips: row.tp_pips })}
                      className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-right text-xs focus:border-blue-500 focus:outline-none"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="number"
                      value={row.sl_pips ?? ""}
                      placeholder="default"
                      onChange={(e) =>
                        setSymbols((s) =>
                          s.map((r) =>
                            r.symbol === row.symbol
                              ? { ...r, sl_pips: e.target.value ? parseInt(e.target.value) : null }
                              : r,
                          ),
                        )
                      }
                      onBlur={() => updateSymbol(row.symbol, { sl_pips: row.sl_pips })}
                      className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-right text-xs focus:border-blue-500 focus:outline-none"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="number"
                      step="0.1"
                      value={row.max_spread_pips ?? ""}
                      placeholder="auto"
                      onChange={(e) =>
                        setSymbols((s) =>
                          s.map((r) =>
                            r.symbol === row.symbol
                              ? { ...r, max_spread_pips: e.target.value || null }
                              : r,
                          ),
                        )
                      }
                      onBlur={() =>
                        updateSymbol(row.symbol, {
                          max_spread_pips: row.max_spread_pips ? row.max_spread_pips : null,
                        })
                      }
                      className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-right text-xs focus:border-blue-500 focus:outline-none"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => deleteSymbol(row.symbol)}
                      className="text-red-500 hover:text-red-400"
                      title="Remove symbol"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Add symbol */}
        <div className="px-4 py-3 flex items-center gap-2 border-t border-gray-700/50">
          <input
            type="text"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
            placeholder="e.g. GBPUSDm"
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none w-40"
            onKeyDown={(e) => e.key === "Enter" && addSymbol()}
          />
          <button
            onClick={addSymbol}
            className="flex items-center gap-1 bg-cyan-700 hover:bg-cyan-600 px-3 py-1.5 rounded-lg text-xs font-medium"
          >
            <Plus size={14} /> Add Symbol
          </button>
        </div>
      </div>
    </div>
  );
}
