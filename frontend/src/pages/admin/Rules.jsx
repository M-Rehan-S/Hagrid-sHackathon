import { useState } from "react";
import { get, post } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err, Json } from "../../ui";
export default function Rules() {
  const { t } = useT();
  const { data, err, reload } = useLoad(() => get("/rules"));
  const [key, setKey] = useState("relief_eligibility");
  const [def, setDef] = useState("{}");
  const [note, setNote] = useState("");
  const [sim, setSim] = useState(null);
  const [e2, setE2] = useState(null);
  const run = async (fn) => { setE2(null); try { await fn(); reload(); } catch (x) { setE2(x); } };
  const create = () => run(async () => post("/rules", { rule_key: key, definition: JSON.parse(def), note }));
  return (
    <>
      <h2>{t("admin_rules")}</h2>
      <Err e={err || e2} />
      <div className="card">
        <label>rule_key</label><input value={key} onChange={(e) => setKey(e.target.value)} />
        <label>definition (JSON)</label><textarea rows={8} value={def} onChange={(e) => setDef(e.target.value)} />
        <label>{t("note")}</label><input value={note} onChange={(e) => setNote(e.target.value)} />
        <button onClick={create}>{t("save")}</button>
      </div>
      {data?.map((r) => (
        <div className="card" key={r.id}>
          <b>{r.rule_key} v{r.version}</b> <span className="tag">{r.status}</span>
          <div className="row">
            {r.status === "draft" && <button onClick={() => run(() => post(`/rules/${r.id}/activate`))}>Activate</button>}
            {r.status === "draft" && <button className="alt" onClick={() => run(async () => setSim(await post("/twin/simulate", { draft_rule_id: r.id })))}>{t("admin_twin")}</button>}
            <button className="alt" onClick={() => setDef(JSON.stringify(r.definition, null, 2))}>↧</button>
          </div>
        </div>
      ))}
      {sim && <div className="card"><h3>{t("admin_twin")}</h3><Json v={{ total: sim.total, changed: sim.changed, ...sim.summary }} /></div>}
    </>
  );
}
