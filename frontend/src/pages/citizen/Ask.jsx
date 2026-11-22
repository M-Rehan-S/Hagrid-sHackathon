import { useState } from "react";
import { post } from "../../api/client";
import { useT } from "../../i18n";
import { Err, Speak } from "../../ui";
export default function Ask() {
  const { t, lang } = useT();
  const [q, setQ] = useState(""); const [a, setA] = useState(null);
  const [err, setErr] = useState(null); const [busy, setBusy] = useState(false);
  async function go() {
    setErr(null); setBusy(true);
    try { setA(await post("/ai/ask", { question: q, language: lang })); } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  const text = a && (typeof a === "string" ? a : (lang === "ur" ? a.answer_ur : a.answer_en) || a.answer || JSON.stringify(a));
  return (
    <div className="card">
      <h2>{t("ask")}</h2>
      <textarea rows={3} value={q} onChange={(e) => setQ(e.target.value)} />
      <Err e={err} />
      <button disabled={busy || !q.trim()} onClick={go}>{t("ask")}</button>
      {a && <><h3>{t("answer")}</h3><p>{text}</p><Speak text={String(text)} /></>}
    </div>
  );
}
