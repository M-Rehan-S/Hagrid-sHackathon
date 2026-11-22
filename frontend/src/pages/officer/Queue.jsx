import { useState } from "react";
import { get, post } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err, Json } from "../../ui";
// Readable summary; field names are best guesses, missing ones are skipped.
function Trace({ d }) {
  const c = d.case || d, dec = (d.decisions || c.decisions || [])[0] || d.decision || {};
  const tr = dec.trace || d.trace || {};
  const rows = [
    ["Status", c.status], ["Route", c.route || dec.route], ["Confidence", dec.confidence ?? c.confidence],
    ["Identity match", tr.identity_match ?? tr.identity?.match ?? tr.identity_status],
    ["Rule", tr.rule_id || tr.rule?.name || dec.rule_id || dec.rule_version], ["Reason", dec.reason_en],
  ].filter(([, v]) => v != null && v !== "");
  return <table><tbody>{rows.map(([k, v]) => <tr key={k}><th>{k}</th><td>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td></tr>)}</tbody></table>;
}
export default function Queue() {
  const { t } = useT();
  const { data, err, reload } = useLoad(() => get("/cases"));
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(null);
  const [note, setNote] = useState("");
  const [e2, setE2] = useState(null);
  async function view(id) {
    setE2(null); setOpen(id);
    try { setDetail(await get(`/cases/${id}`)); } catch (x) { setE2(x); setDetail(null); }
  }
  async function decide(outcome) {
    setE2(null);
    try { await post(`/cases/${open}/decision`, { outcome, note }); setOpen(null); setNote(""); reload(); } catch (x) { setE2(x); }
  }
  return (
    <>
      <h2>{t("queue")}</h2>
      <Err e={err} />
      {data?.map((c) => (
        <div className="card" key={c.id}>
          <span className="tag">{c.status}</span> <span className="tag">{c.route || "-"}</span>
          <span className="tag">P{c.priority}</span> {c.confidence != null && <span className="tag">{c.confidence}</span>}
          <button className="alt" onClick={() => view(c.id)}>{c.id.slice(0, 8)}</button>
          {open === c.id && (
            <>
              <Err e={e2} />
              {detail && <>
                <Trace d={detail} />
                <details><summary>JSON</summary><Json v={detail} /></details>
              </>}
              <textarea rows={2} placeholder={t("note")} value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="row">
                <button disabled={!note} onClick={() => decide("approved")}>{t("approve")}</button>
                <button disabled={!note} className="alt" onClick={() => decide("rejected")}>{t("reject")}</button>
                <button disabled={!note} className="alt" onClick={() => decide("needs_more_proof")}>{t("needs_proof")}</button>
                <button disabled={!note} className="alt" onClick={() => post(`/cases/${c.id}/escalate`, { note }).then(reload).catch(setE2)}>↑</button>
              </div>
            </>
          )}
        </div>
      ))}
      {data?.length === 0 && <p>{t("empty")}</p>}
    </>
  );
}
