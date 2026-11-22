import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post, patch, api } from "../../api/client";
import { useT } from "../../i18n";
import { Speak, Err, Progress } from "../../ui";
import { enqueue } from "../../offline/queue";

const STEPS = [
  { k: "full_name", type: "text" },
  { k: "father_name", type: "text" },
  { k: "cnic", type: "text" },
  { k: "dob", type: "date" },
  { k: "district", type: "text" },
  { k: "household_size", type: "number" },
  { k: "monthly_income", type: "number" },
  { k: "is_widow", type: "bool" },
  { k: "phone", type: "text" },
];
const clean = (k, v) => {
  if (v === "" || v == null) return undefined;
  if (k === "cnic") return String(v).replace(/-/g, "");
  if (k === "household_size" || k === "monthly_income") return Number(v);
  return v;
};

const RULES = {
  cnic: (v) => /^\d{13}$/.test(String(v).replace(/-/g, "")) || "CNIC must be 13 digits",
  phone: (v) => /^03\d{9}$/.test(String(v)) || "Phone must look like 03xxxxxxxxx",
  household_size: (v) => Number(v) >= 1 || "Must be at least 1",
  monthly_income: (v) => Number(v) >= 0 || "Cannot be negative",
};
export default function Wizard() {
  const { t, lang } = useT();
  const nav = useNavigate();
  const [cid, setCid] = useState(localStorage.getItem("citizen_id"));
  const [caseId, setCaseId] = useState(null);
  const [form, setForm] = useState(() => JSON.parse(localStorage.getItem("draft") || "{}"));
  const [i, setI] = useState(0);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [file, setFile] = useState(null);
  const total = STEPS.length + 1; // last step = document + submit
  const s = STEPS[i];

  useEffect(() => { localStorage.setItem("draft", JSON.stringify(form)); }, [form]);

  async function ensureCase() {
    if (caseId) return caseId;
    let id = cid;
    if (!id) { // recover citizen id from an existing case (no "get my citizen" endpoint)
      try { const cs = await get("/cases"); id = cs?.find((x) => x.citizen_id)?.citizen_id || null;
        if (id) { localStorage.setItem("citizen_id", id); setCid(id); } } catch {}
    }
    if (!id) {
      const c = await post("/citizens", { full_name: form.full_name });
      id = c.id; localStorage.setItem("citizen_id", id); setCid(id);
    }
    const c = await post("/cases", { citizen_id: id, case_type: "relief_claim" });
    setCaseId(c.id); return c.id;
  }
  async function next() {
    setErr(null); setBusy(true);
    try {
      const v = clean(s.k, form[s.k]);
      const step = s.k;
      if (v !== undefined && RULES[s.k]) { const ok = RULES[s.k](v); if (ok !== true) throw new Error(ok); }
      if (v !== undefined) {
        if (navigator.onLine) {
          const id = await ensureCase();
          await patch(`/cases/${id}/form`, { form_data_partial: { [s.k]: v }, last_step: step });
        } else if (caseId) {
          enqueue({ type: "patch_form", case_id: caseId, payload: { form_data_partial: { [s.k]: v }, last_step: step } });
        }
      }
      setI(i + 1);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function submit() {
    setErr(null); setBusy(true);
    try {
      const id = await ensureCase();
      if (file) {
        const fd = new FormData(); fd.append("file", file); fd.append("kind", "cnic_photo");
        await api(`/cases/${id}/documents`, { method: "POST", form: fd });
      }
      const r = await post(`/cases/${id}/submit`);
      localStorage.removeItem("draft");
      setResult(r);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }

  if (result) {
    const d = result.decision;
    return (
      <div className="card">
        {d ? <>
          <h2>{t("status")}: {result.case?.status}</h2>
          <p>{lang === "ur" ? d.reason_ur : d.reason_en}</p>
          <Speak text={lang === "ur" ? d.reason_ur : d.reason_en} />
        </> : <>
          <h2>{result.case?.status}</h2>
          <p>Missing: {(result.missing_fields || []).join(", ")}</p>
          <button onClick={() => { setResult(null); setI(0); }}>{t("back")}</button>
        </>}
        <button onClick={() => nav("/status")}>{t("status")}</button>
      </div>
    );
  }

  return (
    <div className="card">
      <Progress step={i} total={total} />
      {s ? (
        <>
          <h2>{t(s.k === "full_name" ? "name" : s.k)}</h2>
          <Speak text={t(s.k === "full_name" ? "name" : s.k)} />
          {s.type === "bool" ? (
            <div className="row">
              <button className={form[s.k] === true ? "" : "alt"} onClick={() => setForm({ ...form, [s.k]: true })}>{t("yes")}</button>
              <button className={form[s.k] === false ? "" : "alt"} onClick={() => setForm({ ...form, [s.k]: false })}>{t("no")}</button>
            </div>
          ) : (
            <input type={s.type} value={form[s.k] ?? ""} onChange={(e) => setForm({ ...form, [s.k]: e.target.value })} />
          )}
        </>
      ) : (
        <>
          <h2>{t("submit")}</h2>
          <label>CNIC photo</label>
          <input type="file" accept="image/*" onChange={(e) => setFile(e.target.files[0])} />
        </>
      )}
      <Err e={err} />
      <div className="row">
        {i > 0 && <button className="alt" onClick={() => setI(i - 1)}>{t("back")}</button>}
        {s ? <button disabled={busy || (i === 0 && !form.full_name)} onClick={next}>{t("next")}</button>
           : <button disabled={busy} onClick={submit}>{t("submit")}</button>}
      </div>
    </div>
  );
}
