import api from "./api";

export interface User {
  id: number;
  username: string;
  email: string;
  profile: {
    role: string;
    notification_enabled: boolean;
    two_factor_enabled: boolean;
  };
}

export async function login(
  username: string,
  password: string
): Promise<User> {
  const { data } = await api.post("/auth/login/", { username, password });
  localStorage.setItem("access_token", data.access);
  localStorage.setItem("refresh_token", data.refresh);
  return data.user;
}

export async function logout(): Promise<void> {
  const refresh = localStorage.getItem("refresh_token");
  try {
    await api.post("/auth/logout/", { refresh });
  } finally {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
  }
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get("/auth/me/");
  return data;
}
