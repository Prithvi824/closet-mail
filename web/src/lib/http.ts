import axios, { isAxiosError } from "axios";

/** Paths that are reachable without a session; a 401 there must not bounce to /login. */
const PUBLIC_PATH_PREFIXES = ["/login", "/totp", "/invite", "/reset"];

/** The single HTTP client for the API (cookie session + CSRF header). */
export const http = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
  headers: { "X-Requested-With": "mailalias" },
});

http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    const path = window.location.pathname;
    const isSessionProbe = isAxiosError(error) && error.config?.url === "/me";
    const isPublicPage = PUBLIC_PATH_PREFIXES.some((prefix) => path.startsWith(prefix));
    // RequireAuth handles the /me probe itself; any other 401 means the session expired.
    if (isAxiosError(error) && error.response?.status === 401 && !isSessionProbe && !isPublicPage) {
      const next = encodeURIComponent(path + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
    return Promise.reject(error);
  },
);

interface ApiErrorBody {
  error?: { code?: string; message?: string };
  detail?: unknown;
}

/** Human-readable message from an API error ({"error": {"message"}}), else the fallback. */
export function errorMessage(error: unknown, fallback = "Something went wrong"): string {
  if (isAxiosError<ApiErrorBody>(error)) {
    const message = error.response?.data?.error?.message;
    if (message) return message;
    if (!error.response) return "Cannot reach the server";
  }
  return fallback;
}

/** HTTP status of an API error, if any. */
export function errorStatus(error: unknown): number | undefined {
  return isAxiosError(error) ? error.response?.status : undefined;
}
