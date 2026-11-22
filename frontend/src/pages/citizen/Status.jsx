import { useEffect } from "react";
import { get } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err } from "../../ui";
export default function Status() {
  const { t, lang } = useT();
  const { data, err, reload } = useLoad(() => get("/cases"));
  useEffect(() => { const i = setInterval(reload, 15000); return () => clearInterval(i); }, []);
  if (err) return <Err e={err} />;
  if (!data) return <p>{t("loading")}</p>;
  if (!data.length) return <p>{t("empty")}</p>;
  return data.map((c) => (
    <div className="card" key={c.id}>
      <span className="tag">{c.status}</span> <span className="tag">{c.route || "-"}</span>
      <p>{c.id.slice(0, 8)}</p>
      {c.decisions?.length > 0 && <p>{lang === "ur" ? c.decisions.at(-1).reason_ur : c.decisions.at(-1).reason_en}</p>}
    </div>
  ));
}
