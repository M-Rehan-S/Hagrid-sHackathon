import { useState } from "react";
import { get, post } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err } from "../../ui";
import Consent from "../citizen/Consent";
import Wizard from "../citizen/Wizard";
export default function People() {
  const { t } = useT();
  const { data, err, reload } = useLoad(() => get("/helper/citizens"));
  const [active, setActive] = useState(localStorage.getItem("citizen_id"));
  const [name, setName] = useState("");
  const [e2, setE2] = useState(null);
  const pick = (id) => { if (confirm(t("sure"))) { localStorage.setItem("citizen_id", id); localStorage.removeItem("draft"); setActive(id); } };
  async function add() {
    setE2(null);
    try { await post("/citizens", { full_name: name }); setName(""); reload(); } catch (x) { setE2(x); }
  }
  return (
    <>
      <h2>{t("people")}</h2>
      <Err e={err || e2} />
      {data?.map((p) => (
        <div className="card" key={p.citizen_id || p.id}>
          {p.full_name || (p.citizen_id || p.id).slice(0, 8)}
          {active === (p.citizen_id || p.id) ? <span className="tag">✓</span>
            : <button className="alt" onClick={() => pick(p.citizen_id || p.id)}>{t("switch")}</button>}
        </div>
      ))}
      <div className="card row">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("name")} />
        <button disabled={!name} onClick={add}>{t("add_person")}</button>
      </div>
      {active && <><h3>{t("consent")}</h3><Consent key={"c" + active} /><Wizard key={active} /></>}
    </>
  );
}
