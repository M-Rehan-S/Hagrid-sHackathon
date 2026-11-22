import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { I18n, useT } from "./i18n";
import { NetBadge, ConnBadge } from "./ui";
import Login from "./pages/Login";
import Home from "./pages/citizen/Home";
import Status from "./pages/citizen/Status";
import Scam from "./pages/citizen/Scam";
import Consent from "./pages/citizen/Consent";
import Ask from "./pages/citizen/Ask";
import Export from "./pages/citizen/Export";
import People from "./pages/helper/People";
import Queue from "./pages/officer/Queue";
import Rules from "./pages/admin/Rules";
import Keys from "./pages/admin/Keys";
import Browse from "./pages/Browse";
import Audit, { Eval } from "./pages/auditor/Audit";

const citizen = [["/", "home", Home], ["/status", "status", Status], ["/scam", "scam", Scam], ["/consent", "consent", Consent], ["/ask", "ask", Ask], ["/export", "export", Export]];
const NAV = {
  citizen,
  helper: [["/", "people", People], ["/status", "status", Status], ["/scam", "scam", Scam], ["/ask", "ask", Ask]],
  officer: [["/", "queue", Queue], ["/eval", "eval", Eval]],
  admin: [["/", "admin_rules", Rules], ["/keys", "admin_keys", Keys], ["/users", "users", () => <Browse path="/admin/users" title="Users" />], ["/analytics", "analytics", () => <Browse path="/analytics" title="Analytics" />], ["/audit", "audit", Audit], ["/eval", "eval", Eval]],
  auditor: [["/", "audit", Audit], ["/consents", "consent", () => <Browse path="/consents" title="Consents" />], ["/decisions", "decisions", () => <Browse path="/ai/decisions" title="AI decisions" />], ["/eval", "eval", Eval]],
};

function Shell() {
  const { user, ready, logout } = useAuth();
  const { t, toggle } = useT();
  if (!ready) return <p style={{ padding: 16 }}>{t("loading")}</p>;
  const routes = user && NAV[user.role];
  return (
    <>
      <div className="banner">{t("banner")}</div>
      <header className="nav">
        <b>{t("app")}</b>
        {routes?.map(([p, k]) => <NavLink key={p} to={p} end className={({ isActive }) => (isActive ? "on" : "")}>{t(k)}</NavLink>)}
        <NetBadge />
        <button className="alt" onClick={toggle}>{t("language")}</button>
        {user && <button className="alt" onClick={logout}>{t("logout")}</button>}
      </header>
      <main>
        {user && <ConnBadge />}
        {!user ? <Login /> : (
          <Routes>
            {routes.map(([p, , C]) => <Route key={p} path={p} element={<C />} />)}
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        )}
      </main>
    </>
  );
}
export default function App() {
  return <I18n><AuthProvider><BrowserRouter><Shell /></BrowserRouter></AuthProvider></I18n>;
}
