const CACHE = 'relief-app-shell-v1'
const SHELL = ['/', '/index.html']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))))
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok && (url.pathname === '/' || url.pathname.endsWith('.js') || url.pathname.endsWith('.css') || url.pathname.endsWith('.svg'))) {
      const copy = response.clone()
      caches.open(CACHE).then((cache) => cache.put(event.request, copy))
    }
    return response
  }).catch(async () => (await caches.match(event.request)) || (await caches.match('/index.html'))))
})
