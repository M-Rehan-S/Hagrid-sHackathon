import { useState } from "react";
import { post } from "../../api/client";
import { useT } from "../../i18n";
import { Err, Speak } from "../../ui";
export default function Scam() {
  const { t, lang } = useT();
  const [text, setText] = useState("");
  const [r, setR] = useState(null);
  const [err, setErr] = useState(null);
  async function go() { setErr(null); try { setR(await post("/ai/scam-check", { text })); } catch (e) { setErr(e); } }
  const adv = r && (lang === "ur" ? r.advice_ur : r.advice_en);
  return (
    <div className="card">
      <h2>{t("scam")}</h2>
      <textarea rows={5} placeholder={t("paste_msg")} value={text} onChange={(e) => setText(e.target.value)} />
      <button disabled={!text} onClick={go}>{t("check")}</button>
      <Err e={err} />
      {r && <>
        <h2>{t(r.label + "_label")} ({Math.round(r.confidence * 100)}%)</h2>
        <p>{adv}</p><Speak text={adv} />
        <ul>{r.reasons?.map((x, i) => <li key={i}>{x}</li>)}</ul>
      </>}
    </div>
  );
}
