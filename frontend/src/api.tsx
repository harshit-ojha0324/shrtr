// API client, app state and formatting. The API key lives in localStorage
// (memory if storage is blocked) and goes out as X-API-Key to /api on the
// same origin (Vite proxies it in dev, nginx in compose).
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

export interface Link {
  short_code: string;
  short_url: string;
  long_url: string;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
}
export type Gran = "hour" | "day";
export interface Point { bucket_start: string; clicks: number }
export interface Stats { total_clicks: number; series: Point[] }
export interface NewLink { long_url: string; custom_alias?: string; expires_at?: string }
export interface BulkResult { index: number; ok: boolean; link: Link | null; error: string | null }

let key = (() => {
  try { return localStorage.getItem("apiKey") ?? ""; } catch { return ""; }
})();
export const getApiKey = () => key;
export function setApiKey(value: string) {
  key = value;
  try {
    if (value) localStorage.setItem("apiKey", value);
    else localStorage.removeItem("apiKey");
  } catch { /* blocked storage: kept in memory for this page load */ }
  window.dispatchEvent(new Event("apikey"));
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-API-Key": key },
  });
  if (res.ok) return res.status === 204 ? (undefined as T) : res.json();
  let msg = res.statusText;
  if (res.status === 401) msg = "Invalid API key. Check Settings.";
  else if (res.status === 429) msg = `Rate limit hit. Try again in ${res.headers.get("Retry-After") ?? "a few "}s.`;
  else {
    try {
      const d = (await res.json()).detail;
      msg = typeof d === "string" ? d : d?.[0]?.msg?.replace(/^Value error, /, "") ?? msg;
    } catch { /* not JSON */ }
  }
  throw new Error(msg);
}

const ago = (hours: number) => encodeURIComponent(new Date(Date.now() - hours * 3_600_000).toISOString());
const enc = encodeURIComponent;

export const api = {
  createLink: (body: NewLink) => request<Link>("/links", { method: "POST", body: JSON.stringify(body) }),
  createBulk: (links: NewLink[]) =>
    request<{ results: BulkResult[] }>("/links/bulk", { method: "POST", body: JSON.stringify({ links }) }),
  listLinks: (limit = 200) => request<Link[]>(`/links?limit=${limit}`),
  getLink: (code: string) => request<Link>(`/links/${enc(code)}`),
  deleteLink: (code: string) => request<void>(`/links/${enc(code)}`, { method: "DELETE" }),
  stats: (code: string, gran: Gran, hoursBack: number) =>
    request<Stats>(`/links/${enc(code)}/stats?granularity=${gran}&from=${ago(hoursBack)}`),
  activity: () => request<Record<string, Point[]>>("/activity?hours=24"),
  checkAlias: (alias: string) =>
    request<{ available: boolean; reason: string | null }>(`/aliases/${enc(alias)}`),
};

/* ---- app state ---- */

interface Store {
  links: Link[];
  activity: Record<string, Point[]>; // last 24h hourly clicks per code, for the list sparklines
  loading: boolean;
  error: string;
  hasKey: boolean;
  upsert: (link: Link) => void;
  refresh: () => void;
  composer: boolean;
  setComposer: (open: boolean) => void;
}

const Ctx = createContext<Store | null>(null);
export const REFRESH_MS = 10_000;

export function StoreProvider({ children }: { children: ReactNode }) {
  const [links, setLinks] = useState<Link[]>([]);
  const [activity, setActivity] = useState<Record<string, Point[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [hasKey, setHasKey] = useState(!!key);
  const [composer, setComposer] = useState(false);

  const refresh = useCallback(async () => {
    setHasKey(!!key);
    if (!key) return void (setLinks([]), setActivity({}), setLoading(false));
    setLoading(true);
    setError("");
    try {
      const [l, a] = await Promise.all([api.listLinks(), api.activity()]);
      setLinks(l);
      setActivity(a);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    window.addEventListener("apikey", refresh);
    // every sparkline in one request, every 30 s while the tab is visible
    const id = setInterval(() => key && !document.hidden && api.activity().then(setActivity, () => {}), 30_000);
    return () => {
      window.removeEventListener("apikey", refresh);
      clearInterval(id);
    };
  }, [refresh]);

  const upsert = useCallback((link: Link) => {
    setLinks((ls) =>
      ls.some((l) => l.short_code === link.short_code)
        ? ls.map((l) => (l.short_code === link.short_code ? link : l))
        : [link, ...ls],
    );
  }, []);

  return (
    <Ctx.Provider value={{ links, activity, loading, error, hasKey, upsert, refresh, composer, setComposer }}>
      {children}
    </Ctx.Provider>
  );
}

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside StoreProvider");
  return s;
}

/* One link's stats: 48 hourly buckets (24h chart + day-over-day KPI) and 30
   daily ones. Two requests, refetched every 10 s while the tab is visible. */
export function useLinkStats(code: string) {
  const [data, setData] = useState<{ hour: Stats; day: Stats } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = () =>
      Promise.all([api.stats(code, "hour", 48), api.stats(code, "day", 24 * 30)]).then(
        ([hour, day]) => alive && (setData({ hour, day }), setError("")),
        (e: Error) => alive && setError(e.message),
      );
    load();
    const tick = () => !document.hidden && load();
    const id = setInterval(tick, REFRESH_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      alive = false;
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [code]);
  return { data, error };
}

/* The last `count` hour/day buckets ending now, zero-filled for a continuous axis.
   Buckets are UTC-aligned, and so is the Unix epoch, so flooring the timestamp works. */
export function series(points: Point[] = [], gran: Gran, count: number) {
  const step = gran === "hour" ? 3_600_000 : 86_400_000;
  const end = Math.floor(Date.now() / step) * step;
  const by = new Map(points.map((p) => [Date.parse(p.bucket_start), p.clicks]));
  return Array.from({ length: count }, (_, i) => {
    const t = end - (count - 1 - i) * step;
    return { t, clicks: by.get(t) ?? 0 };
  });
}

/* ---- formatting ---- */

export type LinkStatus = "active" | "expired" | "deleted";

export function statusOf(link: Link): LinkStatus {
  if (!link.is_active) return "deleted";
  if (link.expires_at && new Date(link.expires_at) <= new Date()) return "expired";
  return "active";
}

export function splitUrl(url: string): { host: string; rest: string } {
  try {
    const u = new URL(url);
    return { host: u.host, rest: u.pathname + u.search + u.hash };
  } catch {
    return { host: url, rest: "" };
  }
}

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
export const n = (x: number) => x.toLocaleString("en-US");
export const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
