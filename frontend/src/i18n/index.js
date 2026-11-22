import en from './en.json'
import ur from './ur.json'

export const dictionaries = { en, ur }
export function translate(language, key, values = {}) {
  const template = dictionaries[language]?.[key] ?? en[key] ?? key
  return Object.entries(values).reduce((text, [name, value]) => text.replaceAll(`{${name}}`, String(value)), template)
}
