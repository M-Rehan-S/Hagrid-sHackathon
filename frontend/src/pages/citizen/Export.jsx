import { get } from "../../api/client";
import { useT } from "../../i18n";
import { useLoad, Err, Json } from "../../ui";
export default function Export() {
  const { t } = useT();
  const cid = localStorage.getItem("citizen_id");
  const { data, err } = useLoad(() => (cid ? get(`/citizens/${cid}/export`) : Promise.resolve(null)));
  if (!cid) return <p>{t("empty")}</p>;
  if (err) return <Err e={err} />;
  return data ? <Json v={data} /> : <p>{t("loading")}</p>;
}
