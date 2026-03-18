import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  TrendingUp,
  BarChart3,
  Brain,
  Settings,
  LineChart,
  User,
  LogOut,
} from "lucide-react";
import { useAuth } from "../hooks/useAuth";

const links = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/trades", icon: TrendingUp, label: "Trades" },
  { to: "/levels", icon: BarChart3, label: "S/R Levels" },
  { to: "/ai-log", icon: Brain, label: "AI Log" },
  { to: "/analytics", icon: LineChart, label: "Analytics" },
  { to: "/settings", icon: Settings, label: "Settings", adminOnly: true },
  { to: "/profile", icon: User, label: "Profile" },
];

export function Sidebar() {
  const { user, logout } = useAuth();

  return (
    <aside className="fixed left-0 top-0 h-full w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div className="p-6 border-b border-gray-800">
        <h1 className="text-xl font-bold text-blue-400">FlockTrade</h1>
        <p className="text-xs text-gray-500 mt-1">AI Trading Platform</p>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        {links.map((link) => {
          if (link.adminOnly && user?.profile.role !== "admin") return null;
          return (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-gray-400 hover:text-white hover:bg-gray-800"
                }`
              }
            >
              <link.icon size={18} />
              {link.label}
            </NavLink>
          );
        })}
      </nav>

      <div className="p-4 border-t border-gray-800">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-xs font-bold">
            {user?.username?.charAt(0).toUpperCase()}
          </div>
          <div>
            <p className="text-sm font-medium">{user?.username}</p>
            <p className="text-xs text-gray-500 capitalize">
              {user?.profile.role}
            </p>
          </div>
        </div>
        <button
          onClick={logout}
          className="flex items-center gap-2 text-sm text-gray-400 hover:text-red-400 transition-colors w-full"
        >
          <LogOut size={16} />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
