import axios from "axios";

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

/** Get the current account type from localStorage (default DEMO). */
export function getAccountType(): "DEMO" | "REAL" {
  return (localStorage.getItem("account_type") as "DEMO" | "REAL") || "DEMO";
}

/** Set account type and persist to localStorage. */
export function setAccountType(t: "DEMO" | "REAL") {
  localStorage.setItem("account_type", t);
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // Automatically append account_type to all GET requests
  const acct = getAccountType();
  if (config.method === "get" || config.method === "GET") {
    config.params = { ...config.params, account_type: acct };
  } else {
    // For POST/PATCH/PUT, add to data if it's an object
    if (config.data && typeof config.data === "object" && !Array.isArray(config.data)) {
      config.data = { ...config.data, account_type: acct };
    } else if (!config.data) {
      config.data = { account_type: acct };
    }
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const refresh = localStorage.getItem("refresh_token");
      if (refresh) {
        try {
          const { data } = await axios.post("/api/auth/refresh/", {
            refresh,
          });
          localStorage.setItem("access_token", data.access);
          if (data.refresh) localStorage.setItem("refresh_token", data.refresh);
          original.headers.Authorization = `Bearer ${data.access}`;
          return api(original);
        } catch {
          localStorage.removeItem("access_token");
          localStorage.removeItem("refresh_token");
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

export default api;
