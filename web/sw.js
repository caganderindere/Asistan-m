// Makes Cuba installable on the phone's home screen. Nothing is cached: Cuba only works
// while it can reach the computer, so every request goes to the network as usual.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});

// "Cuba arıyor": the server rings the phone with a push until Çağan opens it.
self.addEventListener('push', (event) => {
  let call = {};
  try { call = event.data.json(); } catch { call = { body: event.data?.text() ?? '' }; }
  event.waitUntil(self.registration.showNotification(call.title || '📞 Cuba arıyor', {
    body: call.body || 'Cuba seninle konuşmak istiyor.',
    tag: 'cuba-ara',
    renotify: true,
    requireInteraction: true,
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    vibrate: [400, 200, 400, 200, 400],
    data: { id: call.id || '' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const id = event.notification.data?.id || '';
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of open) {
      if ('focus' in client) {
        client.postMessage({ type: 'ara', id });
        return client.focus();
      }
    }
    return self.clients.openWindow(`/?ara=${encodeURIComponent(id)}`);
  })());
});
