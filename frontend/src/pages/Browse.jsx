import { get } from "../api/client";
import { useLoad, Err, Json } from "../ui";
// Generic tolerant list viewer. Endpoint paths are GUESSED; adjust in App.jsx.
export default function Browse({ path, title }) {
  const { data, err } = useLoad(() => get(path), [path]);
  const rows = Array.isArray(data) ? data : data?.items;
  return (
    <>
      <h2>{title}</h2>
      <Err e={err} />
      {!data && !err && <p>…</p>}
      {rows?.map((r, i) => (
        <details className="card" key={r.id || i}>
          <summary>
            {[r.id && String(r.id).slice(0, 8), r.action || r.decision || r.route || r.scope || r.email || r.role, r.status, r.confidence != null && `conf ${r.confidence}`, r.created_at || r.ts].filter(Boolean).join(" · ")}
          </summary>
          <Json v={r} />
        </details>
      ))}
      {data && !rows && <Json v={data} />}
    </>
  );
}
