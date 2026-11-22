import { useState } from "react";
import { get } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err, Json } from "../../ui";
export default function Audit() {
  const { t } = useT();
  const [action, setAction] = useState("");
  const [fx, setFx] = useState({ entity_type: "", actor_id: "", from: "", to: "" });
  const [page, setPage] = useState(1);
  const q = `?page=${page}&page_size=20${action ? `&action=${encodeURIComponent(action)}` : ""}${Object.entries(fx).filter(([, v]) => v).map(([k, v]) => `&${k === "from" ? "date_from" : k === "to" ? "date_to" : k}=${encodeURIComponent(v)}`).join("")}`;
  const { data, err } = useLoad(() => get("/audit-logs" + q), [q]);
  const [v, setV] = useState(null);
  const [e2, setE2] = useState(null);
  return (
    <>
      <h2>{t("audit")}</h2>
      <div className="card row">
        <input style={{ width: 200 }} placeholder="action" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} />
        {["entity_type", "actor_id"].map((k) => <input key={k} style={{ width: 160 }} placeholder={k} value={fx[k]} onChange={(e) => { setFx({ ...fx, [k]: e.target.value }); setPage(1); }} />)}
        {["from", "to"].map((k) => <input key={k} type="date" style={{ width: 150 }} title={k} value={fx[k]} onChange={(e) => { setFx({ ...fx, [k]: e.target.value }); setPage(1); }} />)}
        <button onClick={() => get("/audit-logs/verify").then(setV).catch(setE2)}>{t("verify")}</button>
        {v && <span className="tag">{v.valid ? "✓ valid" : "✗ broken at " + v.broken_at}</span>}
      </div>
      <Err e={err || e2} />
      {data && (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr><th>#</th><th>time</th><th>actor</th><th>action</th><th>entity</th></tr></thead>
            <tbody>{data.items.map((r) => (
              <tr key={r.id}><td>{r.id}</td><td>{r.ts}</td><td>{r.actor_type}</td><td>{r.action}</td><td>{r.entity_type}</td></tr>
            ))}</tbody>
          </table>
          <div className="row">
            <button className="alt" disabled={page === 1} onClick={() => setPage(page - 1)}>‹</button>
            <span>{page} / {Math.max(1, Math.ceil(data.total / data.page_size))}</span>
            <button className="alt" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>›</button>
          </div>
        </div>
      )}
    </>
  );
}
export function Eval() {
  const { t } = useT();
  const { data, err } = useLoad(() => get("/eval/summary"));
  return <><h2>{t("eval")}</h2><Err e={err} />{data && <Json v={data} />}</>;
}
