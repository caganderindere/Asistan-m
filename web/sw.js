// Makes Cuba installable on the phone's home screen. Nothing is cached: Cuba only works
// while it can reach the computer, so every request goes to the network as usual.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});
