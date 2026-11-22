import { useState } from "react";
import { get, post } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err } from "../../ui";
export default function Keys() {
  const { t } = useT();
  const { data, err, reload } = useLoad(() => get("/api-keys"));
  const [label, setLabel] = useState("");
  const [full, setFull] = useState(null);
  const [e2, setE2] = useState(null);
  const run = async (fn) => { setE2(null); try { await fn(); reload(); } catch (x) { setE2(x); } };
  return (
    <>
      <h2>{t("admin_keys")}</h2>
      <Err e={err || e2} />
      <div className="card row">
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="label" />
        <button disabled={!label} onClick={() => run(async () => { const k = await post("/api-keys", { label }); setFull(k.api_key); setLabel(""); })}>+</button>
      </div>
      {full && <div className="card"><b>Copy now (shown once):</b><pre>{full}</pre></div>}
      {data?.map((k) => (
        <div className="card" key={k.id}>
          {k.label} · {k.key_prefix}… {k.revoked_at ? <span className="tag">revoked</span>
            : <button className="alt" onClick={() => run(() => post(`/api-keys/${k.id}/revoke`))}>{t("withdraw")}</button>}
        </div>
      ))}
    </>
  );
}
