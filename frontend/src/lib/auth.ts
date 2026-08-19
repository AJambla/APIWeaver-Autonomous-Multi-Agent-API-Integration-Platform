import type { AuthTokens, User } from "./types";

/**
 * Client-side token storage. The backend returns tokens as JSON (it does not set
 * HttpOnly cookies), so we persist the refresh token in a cookie and the access
 * token in memory. The cookie is readable by `middleware.ts` for route gating and
 * by the refresh flow; the access token is intentionally not written to storage.
 *
 * Note: a true HttpOnly refresh cookie would require the backend to set it. Until
 * then the refresh token lives in a client-readable cookie. Keep access tokens
 * short-lived and rely on the refresh endpoint.
 */

const ACCESS_COOKIE = "aw_access";
const REFRESH_COOKIE = "aw_refresh";

function safeDocument(): Document | null {
  return typeof document !== "undefined" ? document : null;
}

function getCookie(name: string): string | null {
  const doc = safeDocument();
  if (!doc) return null;
  const match = doc.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function setCookie(name: string, value: string, days = 30): void {
  const doc = safeDocument();
  if (!doc) return;
  const expires = new Date(Date.now() + days * 864e5).toUTCString();
  doc.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
}

function deleteCookie(name: string): void {
  const doc = safeDocument();
  if (!doc) return;
  doc.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(ACCESS_COOKIE);
}

export function getRefreshToken(): string | null {
  return getCookie(REFRESH_COOKIE);
}

export function setAccessToken(token: string): void {
  if (typeof window !== "undefined") {
    sessionStorage.setItem(ACCESS_COOKIE, token);
  }
}

export function setStoredTokens(tokens: AuthTokens): void {
  setAccessToken(tokens.access_token);
  setCookie(REFRESH_COOKIE, tokens.refresh_token);
}

export function clearStoredTokens(): void {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem(ACCESS_COOKIE);
  }
  deleteCookie(REFRESH_COOKIE);
}

/**
 * Exchange a refresh token for a fresh pair. Returns null when no refresh token is
 * present or the refresh is rejected (caller should re-authenticate).
 */
export async function refreshTokens(
  baseUrl = "/api/v1",
): Promise<AuthTokens | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  const res = await fetch(`${baseUrl}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    clearStoredTokens();
    return null;
  }
  const tokens = (await res.json()) as AuthTokens;
  setStoredTokens(tokens);
  return tokens;
}

const USER_KEY = "aw_user";

export function getStoredUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as User) : null;
}

export function setStoredUser(user: User): void {
  if (typeof window !== "undefined") {
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  }
}

export function clearStoredUser(): void {
  if (typeof window !== "undefined") {
    sessionStorage.removeItem(USER_KEY);
  }
}
