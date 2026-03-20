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
  exchange: string;
  binance_api_key: string;
  binance_api_secret: string;
  binance_testnet_api_key: string;
  binance_testnet_api_secret: string;
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
  order_quantity_btc: string;
  order_quantity_eth: string;
  tp_pct_btc: string;
  sl_pct_btc: string;
  tp_pct_eth: string;
  sl_pct_eth: string;
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
  const [binance, setBinance] = useState({
    binance_api_key: "",
    binance_api_secret: "",
    binance_testnet_api_key: "",
    binance_testnet_api_secret: "",
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
    order_quantity_btc: "",
    order_quantity_eth: "",
    tp_pct_btc: "",
    sl_pct_btc: "",
    tp_pct_eth: "",
    sl_pct_eth: "",
  });

  const [showRealKey, setShowRealKey] = useState(false);
  const [showRealSecret, setShowRealSecret] = useState(false);
  const [showTestKey, setShowTestKey] = useState(false);
  const [showTestSecret, setShowTestSecret] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");

  useEffect(() => {
    api.get("/status/").then((r) => setBotStatus(r.data)).catch(() => {});
    api
      .get("/config/")
      .then((r) => {
        const g = r.data.global;
        setGc(g);
        setBinance({
          binance_api_key: g.binance_api_key ?? "",
          binance_api_secret: g.binance_api_secret ?? "",
          binance_testnet_api_key: g.binance_testnet_api_key ?? "",
          binance_testnet_api_secret: g.binance_testnet_api_secret ?? "",
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
          order_quantity_btc: String(g.order_quantity_btc ?? g.lot_size_forex ?? "0.001"),
          order_quantity_eth: String(g.order_quantity_eth ?? g.lot_size_gold ?? "0.01"),
          tp_pct_btc: String(g.tp_pct_btc ?? g.tp_pips_forex ?? "2"),
          sl_pct_btc: String(g.sl_pct_btc ?? g.sl_pips_forex ?? "1"),
          tp_pct_eth: String(g.tp_pct_eth ?? g.tp_pips_gold ?? "2"),
          sl_pct_eth: String(g.sl_pct_eth ?? g.sl_pips_gold ?? "1"),
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

  function MaskedField({
    label,
    value,
    onChange,
    show,
    onToggle,
    placeholder,
  }: {
    label: string;
    value: string;
    onChange: (v: string) => void;
    show: boolean;
    onToggle: () => void;
    placeholder?: string;
  }) {
    return (
      <div>
        <label className="block text-xs text-gray-400 mb-1">{label}</label>
        <div className="relative">
          <input
            type={show ? "text" : "password"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none pr-10"
            placeholder={placeholder}
          />
          <button
            type="button"
            onClick={onToggle}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
          >
            {show ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>
    );
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

      {/* Binance Connection */}
      <CollapsibleSection
        title="Binance Connection"
        icon={<Server size={16} className="text-blue-400" />}
        onSave={() =>
          saveSection("Binance", {
            binance_api_key: binance.binance_api_key,
            binance_api_secret: binance.binance_api_secret,
            binance_testnet_api_key: binance.binance_testnet_api_key,
            binance_testnet_api_secret: binance.binance_testnet_api_secret,
          })
        }
        saving={saving === "Binance"}
        defaultOpen
      >
        <div className="sm:col-span-2">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-semibold text-gray-300 bg-gray-700 px-2 py-0.5 rounded">Exchange</span>
            <span className="text-xs text-blue-400">Binance</span>
          </div>
        </div>
        <div className="sm:col-span-2 border-b border-gray-700/50 pb-3 mb-1">
          <p className="text-xs font-semibold text-green-400 mb-2">Real (Mainnet)</p>
        </div>
        <MaskedField
          label="API Key"
          value={binance.binance_api_key}
          onChange={(v) => setBinance((s) => ({ ...s, binance_api_key: v }))}
          show={showRealKey}
          onToggle={() => setShowRealKey(!showRealKey)}
        />
        <MaskedField
          label="API Secret"
          value={binance.binance_api_secret}
          onChange={(v) => setBinance((s) => ({ ...s, binance_api_secret: v }))}
          show={showRealSecret}
          onToggle={() => setShowRealSecret(!showRealSecret)}
        />
        <div className="sm:col-span-2 border-b border-gray-700/50 pb-3 mb-1 mt-2">
          <p className="text-xs font-semibold text-yellow-400 mb-2">Demo (Testnet)</p>
        </div>
        <MaskedField
          label="Testnet API Key"
          value={binance.binance_testnet_api_key}
          onChange={(v) => setBinance((s) => ({ ...s, binance_testnet_api_key: v }))}
          show={showTestKey}
          onToggle={() => setShowTestKey(!showTestKey)}
        />
        <MaskedField
          label="Testnet API Secret"
          value={binance.binance_testnet_api_secret}
          onChange={(v) => setBinance((s) => ({ ...s, binance_testnet_api_secret: v }))}
          show={showTestSecret}
          onToggle={() => setShowTestSecret(!showTestSecret)}
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

      {/* Trade Defaults */}
      <CollapsibleSection
        title="Trade Defaults"
        icon={<BarChart3 size={16} className="text-green-400" />}
        onSave={() =>
          saveSection("Defaults", {
            order_quantity_btc: parseFloat(defaults.order_quantity_btc),
            order_quantity_eth: parseFloat(defaults.order_quantity_eth),
            tp_pct_btc: parseFloat(defaults.tp_pct_btc),
            sl_pct_btc: parseFloat(defaults.sl_pct_btc),
            tp_pct_eth: parseFloat(defaults.tp_pct_eth),
            sl_pct_eth: parseFloat(defaults.sl_pct_eth),
          })
        }
        saving={saving === "Defaults"}
      >
        <FieldInput
          label="BTC Order Qty"
          value={defaults.order_quantity_btc}
          onChange={(v) => setDefaults((s) => ({ ...s, order_quantity_btc: v }))}
          type="number"
        />
        <FieldInput
          label="ETH Order Qty"
          value={defaults.order_quantity_eth}
          onChange={(v) => setDefaults((s) => ({ ...s, order_quantity_eth: v }))}
          type="number"
        />
        <FieldInput
          label="BTC TP (%)"
          value={defaults.tp_pct_btc}
          onChange={(v) => setDefaults((s) => ({ ...s, tp_pct_btc: v }))}
          type="number"
        />
        <FieldInput
          label="BTC SL (%)"
          value={defaults.sl_pct_btc}
          onChange={(v) => setDefaults((s) => ({ ...s, sl_pct_btc: v }))}
          type="number"
        />
        <FieldInput
          label="ETH TP (%)"
          value={defaults.tp_pct_eth}
          onChange={(v) => setDefaults((s) => ({ ...s, tp_pct_eth: v }))}
          type="number"
        />
        <FieldInput
          label="ETH SL (%)"
          value={defaults.sl_pct_eth}
          onChange={(v) => setDefaults((s) => ({ ...s, sl_pct_eth: v }))}
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
                <th className="px-4 py-2 text-right">Qty</th>
                <th className="px-4 py-2 text-right">TP %</th>
                <th className="px-4 py-2 text-right">SL %</th>
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
                      step="0.001"
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
                      step="0.1"
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
                      step="0.1"
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
            placeholder="e.g. BTCUSDT"
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
