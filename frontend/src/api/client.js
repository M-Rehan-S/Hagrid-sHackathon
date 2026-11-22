import { createClient } from "@supabase/supabase-js";
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL || "http://localhost",
  import.meta.env.VITE_SUPABASE_ANON_KEY || "anon"
);
const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api/v1";

export async function api(path, { method = "GET", body, form } = {}) {
  const { data: s } = await supabase.auth.getSession();
  const headers = {};
  if (s.session) headers.Authorization = `Bearer ${s.session.access_token}`;
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(BASE + path, {
    method, headers, body: form || (body ? JSON.stringify(body) : undefined),
  });
  let json = null;
  try { json = await res.json(); } catch {}
  if (!res.ok || json?.error) {
    const e = new Error(json?.error?.message || `Error ${res.status}`);
    e.code = json?.error?.code; e.status = res.status; throw e;
  }
  return json.data;
}
export const get = (p) => api(p);
export const post = (p, body) => api(p, { method: "POST", body: body ?? {} });
export const patch = (p, body) => api(p, { method: "PATCH", body });

const SB = import.meta.env.VITE_SUPABASE_URL, KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;
export const envOk = () => Boolean(SB && KEY && import.meta.env.VITE_API_BASE_URL);
const ping = async (url, headers) => {
  const c = new AbortController(); const tm = setTimeout(() => c.abort(), 6000);
  try { const r = await fetch(url, { headers, signal: c.signal }); return r.status < 500; }
  catch { return false; } finally { clearTimeout(tm); }
};
// Checks Supabase (auth/database host) and the backend API (which talks to the DB).
export async function checkConnection() {
  const supabaseOk = SB ? await ping(`${SB}/auth/v1/health`, { apikey: KEY || "" }) : false;
  const apiOk = await ping(`${BASE}/health`).then((ok) => ok || ping(BASE.replace(/\/api\/v1\/?$/, "") + "/"));
  return { supabaseOk, apiOk };
}
