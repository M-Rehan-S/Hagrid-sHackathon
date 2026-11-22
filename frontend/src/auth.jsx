import { createContext, useContext, useEffect, useState } from "react";
import { supabase, get, post } from "./api/client";
const Ctx = createContext();
export const useAuth = () => useContext(Ctx);
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  async function load() {
    try { setUser((await get("/auth/me")).user); } catch { setUser(null); }
    setReady(true);
  }
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => (data.session ? load() : setReady(true)));
    const { data: sub } = supabase.auth.onAuthStateChange((e) => { if (e === "SIGNED_OUT") setUser(null); });
    return () => sub.subscription.unsubscribe();
  }, []);
  async function login(email, password) {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    const d = await post("/auth/session"); setUser(d.user);
  }
  async function signup(email, password, full_name, language) {
    const { data, error } = await supabase.auth.signUp({ email, password, options: { data: { full_name, language } } });
    if (error) throw error;
    if (data.session) { const d = await post("/auth/session"); setUser(d.user); }
    else throw new Error("Check your email to confirm, then log in.");
  }
  const logout = async () => { await supabase.auth.signOut(); setUser(null); };
  return <Ctx.Provider value={{ user, ready, login, signup, logout }}>{children}</Ctx.Provider>;
}
