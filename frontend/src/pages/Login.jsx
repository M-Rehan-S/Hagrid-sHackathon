import { useState } from "react";
import { useAuth } from "../auth";
import { useT } from "../i18n";
import { Err, ConnBadge } from "../ui";
export default function Login() {
  const { login, signup } = useAuth();
  const { t, lang } = useT();
  const [mode, setMode] = useState("login");
  const [f, setF] = useState({ email: "", password: "", name: "" });
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  async function go(e) {
    e.preventDefault(); setErr(null);
    try { mode === "login" ? await login(f.email, f.password) : await signup(f.email, f.password, f.name, lang); }
    catch (x) { setErr(x); }
  }
  return (
    <main>
      <h1>{t("app")}</h1>
      <ConnBadge full />
      <form className="card" onSubmit={go}>
        {mode === "signup" && <><label>{t("name")}</label><input value={f.name} onChange={set("name")} required /></>}
        <label>{t("email")}</label><input type="email" value={f.email} onChange={set("email")} required />
        <label>{t("password")}</label><input type="password" value={f.password} onChange={set("password")} required minLength={6} />
        <Err e={err} />
        <button className="big">{t(mode)}</button>
        <button type="button" className="alt big" onClick={() => setMode(mode === "login" ? "signup" : "login")}>{t(mode === "login" ? "signup" : "login")}</button>
      </form>
    </main>
  );
}
