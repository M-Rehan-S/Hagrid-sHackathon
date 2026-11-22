import { useState } from "react";
import { get, post } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err } from "../../ui";
export default function Consent() {
  const { t } = useT();
  const cid = localStorage.getItem("citizen_id");
  const { data, err, reload } = useLoad(() => (cid ? get(`/consents?citizen_id=${cid}`) : Promise.resolve([])));
  const [role, setRole] = useState("officer");
  const [scope, setScope] = useState("claim_data");
  const [e2, setE2] = useState(null);
  const act = async (fn) => { setE2(null); try { await fn(); reload(); } catch (x) { setE2(x); } };
  if (!cid) return <p>{t("empty")}</p>;
  return (
    <>
      <div className="card">
        <div className="row">
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="officer">officer</option><option value="helper">helper</option>
          </select>
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="claim_data">claim_data</option><option value="identity">identity</option>
          </select>
          <button onClick={() => act(() => post("/consents", { citizen_id: cid, grantee_role: role, scope }))}>{t("grant")}</button>
        </div>
        <Err e={e2} />
      </div>
      <Err e={err} />
      {data?.map((c) => (
        <div className="card" key={c.id}>
          <b>{c.grantee_role || c.grantee_user_id}</b> · {c.scope} · <span className="tag">{c.status}</span>
          {c.status === "active" && <button className="alt" onClick={() => act(() => post(`/consents/${c.id}/withdraw`))}>{t("withdraw")}</button>}
        </div>
      ))}
    </>
  );
}
