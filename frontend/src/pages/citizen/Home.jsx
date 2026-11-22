import { Link } from "react-router-dom";
import { useT } from "../../i18n";
import Wizard from "./Wizard";
export default function Home() {
  const { t } = useT();
  return (
    <>
      <div className="row">
        <Link className="btn" to="/status">{t("status")}</Link>
        <Link className="btn" to="/scam">{t("scam")}</Link>
        <Link className="btn" to="/consent">{t("consent")}</Link>
        <Link className="btn" to="/export">{t("export")}</Link>
      </div>
      <h2>{t("claim")}</h2>
      <Wizard />
    </>
  );
}
