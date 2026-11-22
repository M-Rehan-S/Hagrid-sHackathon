import { createContext, useContext, useEffect, useState } from "react";
import en from "./en.json";
import ur from "./ur.json";
const D = { en, ur };
const Ctx = createContext();
export function I18n({ children }) {
  const [lang, setLang] = useState(localStorage.getItem("lang") || "ur");
  useEffect(() => {
    localStorage.setItem("lang", lang);
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ur" ? "rtl" : "ltr";
  }, [lang]);
  const t = (k) => D[lang][k] || k;
  return <Ctx.Provider value={{ t, lang, toggle: () => setLang(lang === "ur" ? "en" : "ur") }}>{children}</Ctx.Provider>;
}
export const useT = () => useContext(Ctx);
