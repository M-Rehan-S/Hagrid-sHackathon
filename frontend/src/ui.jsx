import { useEffect, useState } from "react";
import { useT } from "./i18n";
import { pending, flush } from "./offline/queue";
import { checkConnection, envOk } from "./api/client";

export function Speak({ text }) {
  const { t, lang } = useT();
  if (!("speechSynthesis" in window)) return null;
  const go = () => {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang === "ur" ? "ur-PK" : "en-US";
    speechSynthesis.speak(u);
  };
  return <button className="alt" onClick={go} aria-label={t("speak")} title={t("speak")}>🔊</button>;
}
export function Err({ e }) { return e ? <div className="err">{e.message || String(e)}</div> : null; }
export function Progress({ step, total }) {
  return <div className="bar">{Array.from({ length: total }, (_, i) => <span key={i} className={i <= step ? "f" : ""} />)}</div>;
}
export function NetBadge() {
  const { t } = useT();
  const [on, setOn] = useState(navigator.onLine);
  const [q, setQ] = useState(pending());
  useEffect(() => {
    const up = () => { setOn(true); flush().catch(() => {}).finally(() => setQ(pending())); };
    const down = () => setOn(false);
    addEventListener("online", up); addEventListener("offline", down);
    const i = setInterval(() => setQ(pending()), 3000);
    return () => { removeEventListener("online", up); removeEventListener("offline", down); clearInterval(i); };
  }, []);
  return <span><span className={"dot" + (on ? "" : " off")} />{on ? t("online") : t("offline")}{q ? ` (${q})` : ""}</span>;
}
export function useLoad(fn, deps = []) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [n, setN] = useState(0);
  useEffect(() => { setErr(null); fn().then(setData).catch(setErr); }, [...deps, n]);
  return { data, err, reload: () => setN((x) => x + 1) };
}
export const Json = ({ v }) => <pre>{JSON.stringify(v, null, 2)}</pre>;

export function ConnBadge({ full }) {
  const [c, setC] = useState(null);
  useEffect(() => { checkConnection().then(setC); }, []);
  const mark = (ok) => (ok ? "✓" : "✗");
  if (!envOk()) return <div className="err">Missing .env: set VITE_API_BASE_URL, VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, then restart npm run dev.</div>;
  if (!c) return null;
  if (!full && c.supabaseOk && c.apiOk) return null;
  return <div className={c.supabaseOk && c.apiOk ? "card" : "err"}>
    Database/Auth (Supabase) {mark(c.supabaseOk)} · Backend API {mark(c.apiOk)}
    {!c.apiOk && " — start the backend and check VITE_API_BASE_URL / CORS."}
    {!c.supabaseOk && " — check VITE_SUPABASE_URL and anon key."}
  </div>;
}
