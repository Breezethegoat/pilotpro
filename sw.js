/* Garde l'application et le moteur Python sur le téléphone : ouverture rapide, même avec un réseau lent.
   Les données (classeurs) ne sont jamais mises en cache : elles viennent toujours de Microsoft. */
const VERSION = "2026.11.18-128262";
const CACHE = "pilotpro-" + VERSION;

self.addEventListener("install", (e) => { self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((cles) => Promise.all(cles.filter((c) => c !== CACHE).map((c) => caches.delete(c))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.hostname === "cdn.jsdelivr.net" && url.pathname.startsWith("/pyodide/")) {
    // Moteur Python : fichiers versionnés, jamais modifiés → pris dans le cache dès qu'ils y sont.
    e.respondWith(caches.open(CACHE).then(async (c) => (await c.match(e.request)) || fetch(e.request).then((r) => {
      if (r.ok) c.put(e.request, r.clone());
      return r;
    })));
  } else if (url.origin === location.origin && !url.search.includes("code=")) {
    // Fichiers de l'application : réponse immédiate depuis le cache, mise à jour en arrière-plan.
    e.respondWith(caches.open(CACHE).then(async (c) => {
      const enCache = await c.match(e.request, { ignoreSearch: true });
      const reseau = fetch(e.request).then((r) => { if (r.ok) c.put(e.request, r.clone()); return r; })
        .catch((err) => { if (enCache) return enCache; throw err; });
      return enCache || reseau;
    }));
  }
});
