const DB_NAME = 'relief-claim-copilot'
const DB_VERSION = 1
const STORE = 'state'

function openDb() {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in globalThis)) return reject(new Error('IndexedDB unavailable'))
    const open = indexedDB.open(DB_NAME, DB_VERSION)
    open.onupgradeneeded = () => open.result.createObjectStore(STORE)
    open.onsuccess = () => resolve(open.result)
    open.onerror = () => reject(open.error)
  })
}

export async function readLocal(key, fallback = null) {
  try {
    const db = await openDb()
    return await new Promise((resolve, reject) => {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).get(key)
      request.onsuccess = () => resolve(request.result ?? fallback)
      request.onerror = () => reject(request.error)
    })
  } catch {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback } catch { return fallback }
  }
}

export async function writeLocal(key, value) {
  try {
    const db = await openDb()
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite')
      tx.objectStore(STORE).put(value, key)
      tx.oncomplete = resolve
      tx.onerror = () => reject(tx.error)
    })
  } catch {
    try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* Storage may be disabled or full. */ }
  }
}

export const queueKey = (userId) => `pending-ops:${userId}`
export const draftKey = (userId, caseId) => `draft:${userId}:${caseId}`
export function newOperationId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16)
    return (char === 'x' ? random : (random & 0x3) | 0x8).toString(16)
  })
}
