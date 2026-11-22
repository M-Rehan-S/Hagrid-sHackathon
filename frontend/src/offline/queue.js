// Simple offline queue in localStorage. Ops sync via POST /sync/batch when online.
import { post } from "../api/client";
const K = "opq";
const read = () => JSON.parse(localStorage.getItem(K) || "[]");
const write = (q) => localStorage.setItem(K, JSON.stringify(q));
export const pending = () => read().length;
export function enqueue(op) {
  write([...read(), { client_op_id: crypto.randomUUID(), ...op }]);
}
export async function flush() {
  const ops = read();
  if (!ops.length || !navigator.onLine) return 0;
  const { results } = await post("/sync/batch", { ops: ops.slice(0, 100) });
  const done = new Set(results.filter((r) => r.status !== "error").map((r) => r.client_op_id));
  write(ops.filter((o) => !done.has(o.client_op_id)));
  return done.size;
}
