import { useState, type FormEvent } from "react";
import api from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { Shield, Key } from "lucide-react";

export default function Profile() {
  const { user } = useAuth();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");

    if (newPassword !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    if (newPassword.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }

    try {
      await api.post("/auth/change-password/", {
        old_password: oldPassword,
        new_password: newPassword,
      });
      setMessage("Password changed successfully.");
      setOldPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch {
      setError("Failed to change password. Check your current password.");
    }
  }

  return (
    <div className="space-y-6 max-w-lg">
      <h2 className="text-2xl font-bold">Profile</h2>

      {/* User Info */}
      <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-6">
        <div className="flex items-center gap-4 mb-4">
          <div className="w-14 h-14 rounded-full bg-blue-600 flex items-center justify-center text-xl font-bold">
            {user?.username?.charAt(0).toUpperCase()}
          </div>
          <div>
            <p className="text-lg font-semibold">{user?.username}</p>
            <p className="text-sm text-gray-400">{user?.email}</p>
            <span className="inline-block mt-1 px-2 py-0.5 bg-blue-900/50 text-blue-400 text-xs rounded-full capitalize">
              {user?.profile.role}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 text-sm text-gray-400">
          <Shield size={14} />
          2FA: {user?.profile.two_factor_enabled ? "Enabled" : "Disabled"}
        </div>
      </div>

      {/* Change Password */}
      <form
        onSubmit={handleChangePassword}
        className="bg-gray-800/50 border border-gray-700 rounded-xl p-6 space-y-4"
      >
        <h3 className="font-semibold flex items-center gap-2">
          <Key size={16} /> Change Password
        </h3>

        {message && (
          <div className="bg-green-900/30 border border-green-800 text-green-400 text-sm p-3 rounded-lg">
            {message}
          </div>
        )}
        {error && (
          <div className="bg-red-900/30 border border-red-800 text-red-400 text-sm p-3 rounded-lg">
            {error}
          </div>
        )}

        <div>
          <label className="block text-sm text-gray-400 mb-1">
            Current Password
          </label>
          <input
            type="password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            required
          />
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            New Password
          </label>
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            required
            minLength={12}
          />
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            Confirm New Password
          </label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            required
          />
        </div>

        <button
          type="submit"
          className="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm font-medium"
        >
          Update Password
        </button>
      </form>
    </div>
  );
}
