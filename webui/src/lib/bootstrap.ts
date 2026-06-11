import type { BootstrapResponse } from "./types";

const SECRET_STORAGE_KEY = "kxbot-webui.bootstrap-secret";
const ACCESS_TPOKEN_STORAGE_KEY = "kxbot-webui.access_token"
const REFRESH_TPOKEN_STORAGE_KEY = "kxbot-webui.refresh_token"

/** Read a previously saved bootstrap secret from localStorage. */
export function loadSavedSecret(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(SECRET_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

/** Persist the bootstrap secret so page reloads don't re-prompt. */
export function saveSecret(secret: string): void {
  try {
    window.localStorage.setItem(SECRET_STORAGE_KEY, secret);
  } catch {
    // ignore storage errors (private mode, etc.)
  }
}

/** Clear the saved bootstrap secret (sign out). */
export function clearSavedSecret(): void {
  try {
    window.localStorage.removeItem(SECRET_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function loadAccessToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(ACCESS_TPOKEN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function loadRefreshToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(REFRESH_TPOKEN_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveTokens(access_token: string, refresh_token: string): void {
    try {
        window.localStorage.setItem(ACCESS_TPOKEN_STORAGE_KEY, access_token)
        window.localStorage.setItem(REFRESH_TPOKEN_STORAGE_KEY, refresh_token)
    } catch {
        // ignore
    }
}

export function clearTokens(): void {
    try {
        window.localStorage.removeItem(ACCESS_TPOKEN_STORAGE_KEY)
        window.localStorage.removeItem(REFRESH_TPOKEN_STORAGE_KEY)
    } catch {
        // ignore
    }
}

/**
 * Fetch a short-lived token + the WebSocket path from the gateway's
 * ``/webui/bootstrap`` endpoint.
 */
export async function fetchBootstrap(
  baseUrl: string = "",
  access_token: string = "",
  refresh_token: string = ""
): Promise<BootstrapResponse> {
  const headers: Record<string, string> = {};
  if (access_token && refresh_token) {
    headers["X-Kxbot-Auth"] = refresh_token;
  }
  const res = await fetch(`${baseUrl}/webui/bootstrap`, {
    method: "GET",
    credentials: "same-origin",
    headers,
  });
  if (!res.ok) {
    throw new Error(`bootstrap failed: HTTP ${res.status}`);
  }
  const body = (await res.json()) as BootstrapResponse;
  if (!body.access_token || !body.refresh_token || !body.ws_path) {
    throw new Error("login response missing access_token or refresh_token or ws_path");
  }
  return body;
}

/**
 * Authenticate with username/password via ``/api/login`` and return a
 * bootstrap-style response with a short-lived token + WebSocket path.
 */
export async function fetchLogin(
  baseUrl: string = "",
  username: string,
  password: string,
): Promise<BootstrapResponse> {
  const params = new URLSearchParams({ username, password });
  const res = await fetch(`${baseUrl}/api/login?${params}`, {
    method: "GET",
    credentials: "same-origin",
  });
  if (!res.ok) {
    throw new Error(`login failed: HTTP ${res.status}`);
  }
  const body = (await res.json()) as BootstrapResponse;
  if (!body.access_token || !body.refresh_token || !body.ws_path) {
    throw new Error("login response missing access_token or refresh_token or ws_path");
  }
  return body;
}

/** Derive a WebSocket URL from the current window location and the server-provided path.
 *
 * Keeps the path segment exactly as the server registered it: the root ``/``
 * stays ``/`` and non-root paths are not given an extra trailing slash. This
 * matters because some WS servers dispatch handshakes based on the literal
 * path, not a normalised form.
 */
export function deriveWsUrl(wsPath: string, token: string): string {
  const path = wsPath && wsPath.startsWith("/") ? wsPath : `/${wsPath || ""}`;
  const query = `?token=${encodeURIComponent(token)}`;
  if (typeof window === "undefined") {
    return `ws://127.0.0.1:8765${path}${query}`;
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${scheme}://${host}${path}${query}`;
}

export function deriveWsUrl2(wsPath: string, access_token: string, refresh_token: string): string {
  const path = wsPath && wsPath.startsWith("/") ? wsPath : `/${wsPath || ""}`;
  const query = `?access_token=${encodeURIComponent(access_token)}&refresh_token=${encodeURIComponent(refresh_token)}`;
  if (typeof window === "undefined") {
    return `ws://127.0.0.1:8765${path}${query}`;
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${scheme}://${host}${path}${query}`;
}

