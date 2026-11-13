// The office, an orbital station seen from a corner above. Where each person is shows their real
// state: at the desk while working, around the table while a plan awaits
// approval or the team talks over finished work, by the coffee machine just
// after finishing, on a sofa when idle for long.

const COS = Math.cos(Math.PI / 6);
const SIN = 0.5;
const VIEW = { x: -610, y: -126, w: 1635, h: 1102 }; // what the projection covers, in drawing units
const COFFEE_BREAK_S = 90;
const WALK_SPEED = 240; // plan units per second
const INK = '#E6F1FF';
const GLASS = '#B5DAEE'; // a marker: windows look out into space
const NEON = '#4FD8FF';
const HUD = 'rgb(8 14 28 / .9)';
const MIN_ZOOM = .6, MAX_ZOOM = 3.2, FIT_ZOOM = 1.1; // the station fills the view at FIT_ZOOM
const PRINT_MS = 3500;
const QUOTE_MS = 4000;
// What people say as they take on work and hand it back.
const STARTING = ['Hallediyorum!', 'Hemen bakıyorum.', 'Tamamdır, başlıyorum.', 'Bende.', 'Üstüme aldım.'];
const FINISHED = ['Bitti!', 'Teslim ettim.', 'Tamam, hazır.', 'İş tamam.', 'Raporu bıraktım.'];
const pick = (list) => list[Math.floor(Math.random() * list.length)];

/** Space through the window at this hour: the station's day side, dusk, night, dawn. */
function windowColor(hour = new Date().getHours()) {
  if (hour >= 7 && hour < 17) return '#14295A'; // the station's day side
  if (hour >= 17 && hour < 19) return '#2A1F55';
  if (hour === 6) return '#1F2A5E';
  return '#0A1330';
}

const PEOPLE = {
  lider:       { short: 'Cuba',        color: '#FFB547', hair: '#2B211B', headset: true, desk: [165, 180], meeting: [366, 140], coffee: [1000, 84],  sofa: [930, 388],  visit: [165, 180] },
  kidemli:     { short: 'Kıdemli',     color: '#FF5FA2', hair: '#4A3426', long: true, skin: '#D9A77E', desk: [120, 488], meeting: [428, 88],  coffee: [1052, 84],  sofa: [824, 465],  visit: [70, 240] },
  gelistirici: { short: 'Geliştirici', color: '#4C9BFF', hair: '#1F1B18', desk: [240, 488], meeting: [552, 88],  coffee: [1104, 84],  sofa: [824, 525],  visit: [115, 248] },
  testci:      { short: 'Testçi',      color: '#39E09B', hair: '#6B4A2E', skin: '#F1D0AE', desk: [360, 488], meeting: [428, 192], coffee: [1016, 222], sofa: [824, 585],  visit: [215, 248] },
  asistan:     { short: 'Asistan',     color: '#FF8A3D', hair: '#3A2A20', long: true, skin: '#C99470', desk: [480, 488], meeting: [552, 192], coffee: [1108, 222], sofa: [1000, 388], visit: [260, 240] },
  // The boss: not in the team's snapshots, so the office adds him itself.
  cagan:       { short: 'Çağan',       color: '#C9D6EE', hair: '#241C17', desk: [255, 110], meeting: [614, 140], coffee: [1150, 160], sofa: [1000, 465], visit: [255, 110] },
};
// The four empty desks new hires take, in order: where they sit, meet, drink coffee, rest, visit.
const HIRE_SLOTS = [
  { color: '#B07CFF', hair: '#2A1E16', long: true, desk: [120, 623], meeting: [490, 72],  coffee: [990, 130],  sofa: [960, 600],  visit: [45, 190] },
  { color: '#FFE066', hair: '#5A3A22', desk: [240, 623], meeting: [490, 210], coffee: [1045, 130], sofa: [1030, 560], visit: [280, 190] },
  { color: '#5CE1E6', hair: '#1B1612', skin: '#B9835D', desk: [360, 623], meeting: [340, 210], coffee: [1100, 140], sofa: [880, 640],  visit: [140, 262] },
  { color: '#FF6B6B', hair: '#3B2A1F', desk: [480, 623], meeting: [640, 210], coffee: [860, 120],  sofa: [1090, 500], visit: [190, 262] },
];
// Spots where one stands; everywhere else there is a seat.
const STANDING = new Set([
  '1000,84', '1052,84', '1104,84', '1150,160',
  '70,240', '115,248', '215,248', '260,240', '255,110',
  ...HIRE_SLOTS.flatMap((s) => [s.meeting, s.coffee, s.visit].map(String)),
]);
const BOSS = { id: 'cagan', name: 'Çağan', state: 'idle', activity: '', seconds: 0, log: [] };

// door: [just inside the room, the matching point in the corridor]
// sign: where the room's name is painted: high on the back wall behind it
// ('north' at x, 'west' at y), or on a clear patch of floor.
const ROOMS = [
  { name: 'Yönetim',        x: 20,  y: 20,  w: 280,  h: 250, floor: 'wood',    sign: ['north', 40],  door: [[165, 255], [165, 310]] },
  { name: 'Toplantı odası', x: 300, y: 20,  w: 400,  h: 250, floor: '#152038', sign: ['north', 318], door: [[490, 255], [490, 310]] },
  { name: 'Mutfak',         x: 700, y: 20,  w: 480,  h: 250, floor: 'tile',    sign: ['north', 718], door: [[940, 255], [940, 310]] },
  { name: '',               x: 20,  y: 270, w: 1160, h: 80,  floor: '#0F1828', sign: null,          door: null },
  // One open room: engineering desks on the left, the lounge on the right.
  { name: 'Mühendislik',    x: 20,  y: 350, w: 1160, h: 350, floor: '#131D34', sign: ['west', 684], door: [[600, 368], [600, 310]] },
  // Not a room of its own: the lounge's part of the floor, with its own colour and name.
  { name: 'Dinlenme',       x: 760, y: 350, w: 420,  h: 350, floor: '#181834', sign: ['floor', 880, 676], door: null, zone: true },
];

// [x1, y1, x2, y2, height]; the gaps between them are the doors.
const TALL = 112, LOW = 28, CUT = 9;
const WALLS = [
  [20, 20, 1180, 20, TALL], [20, 20, 20, 285, TALL], [20, 335, 20, 700, TALL],
  [1180, 20, 1180, 700, CUT], [20, 700, 1180, 700, CUT],
  [20, 270, 140, 270, LOW], [190, 270, 460, 270, LOW], [520, 270, 910, 270, LOW], [970, 270, 1180, 270, LOW],
  [20, 350, 570, 350, LOW], [630, 350, 920, 350, LOW], [980, 350, 1180, 350, LOW],
  [300, 20, 300, 270, LOW], [700, 20, 700, 270, LOW],
];

const iso = (x, y, z = 0) => [(x - y) * COS, (x + y) * SIN - z];
// [x, y, size, brightness] as fractions of the canvas, the same on every draw.
const STARS = Array.from({ length: 220 }, (_, i) => {
  const r = (n) => { const v = Math.sin(i * 12.9898 + n * 78.233) * 43758.5453; return v - Math.floor(v); };
  return [r(1), r(2), r(3) < .9 ? 1 : 2, .25 + r(4) * .65];
});

function shade(hex, factor) {
  const n = parseInt(hex.slice(1), 16);
  const part = (shift) => Math.max(0, Math.min(255, Math.round(((n >> shift) & 255) * factor)));
  return `rgb(${part(16)} ${part(8)} ${part(0)})`;
}

// ── The things in the office ────────────────────────────────

function furniture() {
  const things = [];
  const box = (x, y, w, d, h, color, extra = {}) => {
    const thing = { kind: 'box', x0: x, y0: y, x1: x + w, y1: y + d, z0: 0, h, color, ...extra };
    things.push(thing);
    return thing;
  };
  const cyl = (x, y, r, h, color, extra = {}) => {
    things.push({ kind: 'cyl', cx: x, cy: y, r, x0: x - r, y0: y - r, x1: x + r, y1: y + r, z0: 0, h, color, ...extra });
  };
  const plant = (x, y, size = 1) => {
    cyl(x, y, 8 * size, 12 * size, '#2C3A52', { leaves: 15 * size });
  };
  const chair = (x, y) => cyl(x, y, 10, 12, '#24304A');
  const desk = (owner, x, y, w, d, screens = 1) => {
    box(x, y, w, d, 26, '#33415E');
    const total = screens * 44 + (screens - 1) * 8;
    for (let i = 0; i < screens; i += 1) {
      box(x + (w - total) / 2 + i * 52, y + 9, 44, 4, 24, '#0B111C', { z0: 26, screen: owner });
    }
    box(x + w / 2 - 20, y + d - 22, 40, 12, 1.5, '#5A6B8C', { z0: 26 });   // keyboard
    cyl(x + w - 20, y + d - 18, 4.5, 7, '#9FB3D1', { z0: 26 });            // mug
    box(x + 12, y + d - 30, 22, 18, .8, '#CFE9FF', { z0: 26 });            // paper
  };
  const books = (thing, along, count) => {
    const colors = ['#FF5FA2', '#4C9BFF', '#FFB547', '#39E09B', '#FF8A3D', '#7F8DA6'];
    thing.decor = [];
    for (let row = 0; row < 2; row += 1) {
      for (let i = 0; i < count; i += 1) {
        thing.decor.push({ face: 'south', a0: 4 + i * (along - 8) / count, a1: 4 + (i + .78) * (along - 8) / count, z0: 8 + row * 26, z1: 26 + row * 26, color: colors[(i + row * 2) % colors.length] });
      }
    }
  };

  for (const [x1, y1, x2, y2, h] of WALLS) {
    const wall = x1 === x2 ? box(x1 - 3, y1, 6, y2 - y1, h, '#2A3550') : box(x1, y1 - 3, x2 - x1, 6, h, '#2A3550');
    wall.wall = true;
    if (h !== TALL) wall.color = h === CUT ? '#1C2438' : '#26314A';
  }
  const north = things[0];
  const west = [things[1], things[2]];
  const glass = GLASS;
  north.decor = [
    { face: 'south', a0: 190, a1: 262, z0: 34, z1: 78, color: glass },                       // Yönetim window
    { face: 'south', a0: 405, a1: 535, z0: 36, z1: 80, color: '#081020', lit: 'wallScreen' }, // meeting room screen
    { face: 'south', a0: 740, a1: 820, z0: 34, z1: 78, color: glass },                       // kitchen windows
    { face: 'south', a0: 840, a1: 920, z0: 34, z1: 78, color: glass },
    { face: 'south', a0: 980, a1: 1140, z0: 52, z1: 82, color: glass },                      // above the counter
  ];
  // Yönetim whiteboard: the day's plan, a few ticked rows on it.
  west[0].decor = [{ face: 'east', a0: 70, a1: 170, z0: 34, z1: 76, color: '#CFE9FF' },
    ...[0, 1, 2, 3].flatMap((i) => [
      { face: 'east', a0: 80, a1: 87, z0: 65 - i * 9, z1: 71 - i * 9, color: i < 2 ? '#39E09B' : '#7F8DA6' },
      { face: 'east', a0: 92, a1: 152 - i * 13, z0: 67 - i * 9, z1: 69 - i * 9, color: '#3A4766' },
    ])];
  west[1].decor = [
    { face: 'east', a0: 75, a1: 165, z0: 34, z1: 78, color: glass },
    { face: 'east', a0: 215, a1: 305, z0: 34, z1: 78, color: glass },
  ];

  // Yönetim
  books(box(40, 26, 130, 16, 62, '#1E2840'), 130, 10);
  plant(272, 48, 1.15);
  chair(120, 62); chair(210, 62);
  desk('lider', 85, 96, 160, 62);
  chair(165, 180);

  // Toplantı odası
  for (const person of Object.values(PEOPLE)) chair(...person.meeting);
  box(390, 105, 200, 70, 24, '#33415E', { table: true });
  plant(322, 44); plant(656, 246);

  // Mutfak
  box(948, 26, 224, 36, 30, '#2A3550');
  box(962, 32, 38, 24, 20, '#0B111C', { z0: 30 });                        // coffee machine
  for (const x of [1016, 1030, 1044]) cyl(x, 46, 4.5, 7, '#9FB3D1', { z0: 30 });
  box(1066, 34, 44, 22, 1, '#4A5A7A', { z0: 30 });                        // sink
  box(1122, 34, 40, 22, 1.5, '#141B2B', { z0: 30 });                      // hob
  box(1138, 80, 36, 54, 66, '#3A4766');                                   // fridge
  for (const [x, y] of [[1016, 222], [1108, 222], [1062, 176]]) cyl(x, y, 9, 16, '#24304A');
  cyl(1062, 222, 27, 28, '#33415E');
  cyl(1054, 216, 4.5, 7, '#9FB3D1', { z0: 28 }); cyl(1072, 228, 4.5, 7, '#9FB3D1', { z0: 28 });
  // The bigger kitchen: a standing table by the windows.
  cyl(800, 150, 24, 34, '#33415E');
  cyl(793, 146, 4.5, 7, '#9FB3D1', { z0: 34 });
  plant(722, 46, 1.1); plant(724, 248);
  plant(1120, 326);
  box(1150, 292, 22, 38, 26, '#1A2236');                                  // bin

  // Koridor
  box(880, 276, 22, 22, 34, '#3A4766');                                   // water cooler
  cyl(891, 287, 7, 16, '#4FD8FF', { z0: 34 });
  plant(560, 288, .85);

  // Mühendislik: two rows of desks side by side; the back row waits for new hires.
  books(box(40, 358, 100, 16, 46, '#1E2840'), 100, 8);
  const row = (owners, y) => owners.forEach((owner, i) => {
    desk(owner, 60 + i * 120, y, 116, 55);
    chair(120 + i * 120, y + 78);
  });
  row(['kidemli', 'gelistirici', 'testci', 'asistan'], 410);
  // A screen lights up once someone takes the desk.
  row(['slot0', 'slot1', 'slot2', 'slot3'], 545);
  // Reports come out here.
  box(582, 410, 36, 28, 30, '#3A4766', { printer: true });
  const cabinets = box(580, 560, 46, 84, 42, '#2C3A52');
  cabinets.decor = [0, 1, 2].map((i) => ({ face: 'east', a0: 4 + i * 27, a1: 26 + i * 27, z0: 6, z1: 36, color: '#3E4E6E' }));
  // Plants mark where work ends and the lounge begins.
  plant(728, 400, 1.1); plant(728, 500, 1.1); plant(728, 600, 1.1);

  // Dinlenme
  box(792, 430, 12, 190, 32, '#2B3F6B'); box(804, 430, 38, 190, 14, '#3D5A94');   // sofa by the wall
  box(895, 358, 140, 12, 32, '#2B3F6B'); box(895, 370, 140, 36, 14, '#3D5A94');   // sofa under the window
  box(900, 470, 110, 54, 13, '#33415E');                                  // coffee table
  box(916, 482, 30, 20, 2, '#FF5FA2', { z0: 13 });
  cyl(984, 508, 4.5, 7, '#9FB3D1', { z0: 13 });
  cyl(1090, 610, 18, 15, '#FFB547');                                      // pouf
  box(1146, 440, 24, 130, 20, '#1E2840');                                 // TV unit
  box(1160, 452, 4, 106, 46, '#081020', { z0: 20 });
  plant(1152, 378, 1.15); plant(1150, 676, 1.1);

  things.forEach((thing, index) => { thing.order = index; });
  return things;
}

/** Whether *a* has to be drawn before *b*, or null if it does not matter. */
function behind(a, b) {
  const aFirst = a.x1 <= b.x0 || a.y1 <= b.y0;
  const bFirst = b.x1 <= a.x0 || b.y1 <= a.y0;
  if (aFirst !== bFirst) return aFirst;
  if (aFirst) return null; // apart in both directions: they cannot cover each other
  if (a.z0 !== b.z0) return a.z0 < b.z0; // one stands on the other
  return a.order < b.order;
}

/** Order things back to front. *after* holds, for each fixed thing, the fixed things drawn after it. */
function paintOrder(fixed, after, people) {
  const all = [...fixed, ...people];
  const blockers = new Array(all.length).fill(0);
  const next = all.map((_, i) => (i < fixed.length ? [...after[i]] : []));
  for (let i = 0; i < fixed.length; i += 1) for (const j of after[i]) blockers[j] += 1;
  for (let p = fixed.length; p < all.length; p += 1) {
    for (let i = 0; i < all.length; i += 1) {
      if (i === p || (i > p && i >= fixed.length)) continue; // people pairs are handled once
      const first = behind(all[i], all[p]);
      if (first === true) { next[i].push(p); blockers[p] += 1; }
      if (first === false) { next[p].push(i); blockers[i] += 1; }
    }
  }
  const depth = (t) => t.x0 + t.x1 + t.y0 + t.y1;
  const done = new Array(all.length).fill(false);
  const order = [];
  while (order.length < all.length) {
    let pick = -1;
    for (let i = 0; i < all.length; i += 1) {
      if (!done[i] && blockers[i] <= 0 && (pick < 0 || depth(all[i]) < depth(all[pick]))) pick = i;
    }
    if (pick < 0) pick = done.indexOf(false); // a cycle: should not happen, but never stall
    done[pick] = true;
    order.push(all[pick]);
    for (const j of next[pick]) blockers[j] -= 1;
  }
  return order;
}

// ── Getting from one place to another ───────────────────────

const roomOf = ([x, y]) => ROOMS.find((r) => !r.zone && x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h);

/** The corners to walk through from *from* to *to*: out of one door, along the corridor, in at the other. */
function route(from, to) {
  const a = roomOf(from);
  const b = roomOf(to);
  if (!a || !b || a === b) return [to];
  const out = a.door ? [a.door[0], a.door[1]] : [];
  const into = b.door ? [b.door[1], b.door[0]] : [];
  return [...out, ...into, to];
}

function shorten(text, max = 30) {
  // A tool working on a long path reads better as "Edit: app.py".
  const path = text.match(/^(\w+): \S*[\\/]([^\\/\s]+)$/);
  const brief = (path ? `${path[1]}: ${path[2]}` : text).replace(/\s+/g, ' ');
  return brief.length > max ? `${brief.slice(0, max - 1)}…` : brief;
}

function describe(agent, spot, snapshot) {
  if (snapshot.places?.[agent.id]) {
    return { desk: 'Masasında', meeting: 'Toplantı odasında', coffee: 'Mutfakta', sofa: 'Dinlenme alanında',
      visit: "Cuba'nın odasında" }[spot] ?? '';
  }
  if (spot === 'meeting') {
    if (snapshot.phase !== 'review') return 'Toplantıda, plan için onayını bekliyor';
    if (snapshot.review.speaker === agent.id) return 'Toplantıda, söz onda';
    return agent.id === 'lider' ? 'Toplantıda, ekibi dinliyor' : 'Toplantıda, sonuçları tartışıyor';
  }
  if (agent.state === 'error') return 'Masasında, son işi hata verdi';
  if (agent.state === 'working') return agent.id === 'lider' ? 'Masasında, seninle ilgileniyor' : 'Masasında çalışıyor';
  if (agent.id === 'lider' && snapshot.question) return 'Odasında, kararını bekliyor';
  if (spot === 'desk') return 'Odasında, seni dinliyor';
  return spot === 'coffee' ? 'Mutfakta kahve molasında' : 'Dinlenme alanında, boşta';
}

// ── Drawing ─────────────────────────────────────────────────

// Things in the office that open something when clicked: [id, plan x, y, height, what it does].
const OBJECTS = [
  ['printer', 600, 424, 40, 'Çıktılar: ekibin raporları'],
  ['board', 470, 20, 96, 'Pano: görünümü değiştir'],
  ['clock', 282, 22, 92, 'Takvim ve hafıza'],
  ['shelf', 105, 34, 62, 'Proje belgeleri'],
  ['table', 490, 140, 30, 'Akış: kim ne dedi'],
  ['plan', 20, 140, 55, 'Günlük plan: bugün yapılacaklar'],
];
// What the board on the meeting room wall shows; clicking it moves to the next.
const BOARD_MODES = ['GÖREV PANOSU', 'AJANLAR', 'TOKEN · BUGÜN', 'SON KARARLAR'];

/** Draw the office on *canvas*; returns update(snapshot), select(id), where(agent), color(id) and more. */
export function createOffice(canvas, onSelect, onObject = () => {}) {
  const ctx = canvas.getContext('2d');
  const fixed = furniture();
  const after = fixed.map((a, i) => fixed.flatMap((b, j) => (i !== j && behind(a, b) === true ? [j] : [])));
  const calm = matchMedia('(prefers-reduced-motion: reduce)');
  const people = Object.fromEntries(Object.entries(PEOPLE).map(([id, spec]) => [id, {
    id, spec, kind: 'person', x: spec.sofa[0], y: spec.sofa[1], path: [], seated: true,
    placed: false, state: 'idle', says: '', spot: 'sofa',
  }]));
  let latest = null;
  let seenAt = 0;
  let selected = null;
  let lit = new Set();
  let scale = 1;
  let offset = [0, 0]; // where the drawing starts on the canvas, in CSS pixels
  let zoom = FIT_ZOOM; // on top of the size that fits the canvas
  let pan = [0, 0]; // how far the user has dragged the office, in CSS pixels
  let lastFrame = 0;
  let dirty = true;
  let printedAt = -Infinity;
  let boardMode = 0;
  let usage = null; // today's tokens: { claude: {input, output, cache}, gemini: {input, output} }
  let decisions = []; // what the last meeting decided
  let objectHits = []; // [id, x, y, radius] on screen, from the last draw
  let plan = null; // the day's to-do list: { done, total }
  const screens = fixed.filter((t) => t.screen);

  function spotOf(agent, snapshot) {
    // Sent somewhere by name: a person goes there and stays until sent back.
    const sent = snapshot.places?.[agent.id];
    if (sent) return sent;
    if (agent.id === 'cagan') return snapshot.phase === 'meeting' || snapshot.phase === 'review' ? 'meeting' : 'desk';
    if (snapshot.phase === 'meeting') return 'meeting';
    if (snapshot.phase === 'review' && (agent.id === 'lider' || snapshot.review.members.includes(agent.id))) {
      return 'meeting';
    }
    if (agent.state !== 'idle') return 'desk';
    if (agent.id === 'lider' && snapshot.question) return 'desk';
    const idle = agent.seconds + (Date.now() - seenAt) / 1000;
    if (idle >= COFFEE_BREAK_S) return 'sofa';
    // Cuba has just spoken to you and is waiting for your answer, not on a break.
    return agent.id === 'lider' ? 'desk' : 'coffee';
  }

  function bubbleOf(agent, spot, snapshot) {
    if (snapshot.phase === 'review' && spot === 'meeting') {
      const last = snapshot.review.lines.at(-1);
      if (last?.who === agent.id) return shorten(last.text, 160);
      return snapshot.review.speaker === agent.id ? '…' : '';
    }
    if (agent.id === 'lider' && snapshot.question) return '?';
    if (agent.state === 'error') return 'Hata';
    return agent.state === 'working' && spot === 'desk' ? shorten(agent.activity, 90) : '';
  }

  function arrange() {
    if (!latest) return;
    for (const agent of latest.agents) {
      let person = people[agent.id];
      if (!person) {
        const taken = new Set(Object.values(people).map((p) => p.slot));
        const slot = HIRE_SLOTS.findIndex((_, i) => !taken.has(i));
        if (slot < 0) continue;
        const spec = { ...HIRE_SLOTS[slot], short: agent.name };
        person = people[agent.id] = { id: agent.id, spec, kind: 'person', x: spec.sofa[0], y: spec.sofa[1], path: [],
          seated: true, placed: false, state: 'idle', says: '', spot: 'sofa', slot };
      }
      const spot = spotOf(agent, latest);
      const target = person.spec[spot];
      const goal = person.path.at(-1) ?? [person.x, person.y];
      if (goal[0] !== target[0] || goal[1] !== target[1]) {
        if (person.placed && !calm.matches) {
          person.path = route([person.x, person.y], target);
          person.seated = false;
        } else {
          [person.x, person.y] = target;
          person.path = [];
        }
      }
      person.placed = true;
      const now = performance.now();
      if (person.seen && person.state !== agent.state && agent.id !== 'cagan') {
        if (agent.state === 'working') person.quote = pick(STARTING);
        else if (person.state === 'working' && agent.state === 'idle') person.quote = pick(FINISHED);
        else person.quote = '';
        if (person.quote) {
          person.quoteUntil = now + QUOTE_MS;
          setTimeout(arrange, QUOTE_MS + 50);
        }
      }
      person.state = agent.state;
      person.seen = true; // only later changes are spoken about
      person.spot = spot;
      person.saying = person.quote && performance.now() < person.quoteUntil;
      person.says = person.saying ? person.quote : bubbleOf(agent, spot, latest);
      person.talking = latest.phase === 'review' && latest.review?.speaker === agent.id && spot === 'meeting';
      person.code = agent.state === 'working' && spot === 'desk' ? agent.code ?? '' : '';
      person.file = agent.file ?? '';
    }
    lit = new Set(latest.agents.filter((a) => a.state === 'working' && people[a.id]?.spot === 'desk')
      .map((a) => (people[a.id].slot != null ? `slot${people[a.id].slot}` : a.id)));
    if (latest.phase === 'meeting' || latest.phase === 'review') lit.add('wallScreen');
    dirty = true;
  }

  function walk(seconds) {
    let moving = false;
    for (const person of Object.values(people)) {
      let left = WALK_SPEED * seconds;
      while (person.path.length && left > 0) {
        const [tx, ty] = person.path[0];
        const distance = Math.hypot(tx - person.x, ty - person.y);
        if (distance <= left) {
          [person.x, person.y] = [tx, ty];
          person.path.shift();
          left -= distance;
        } else {
          person.x += (tx - person.x) / distance * left;
          person.y += (ty - person.y) / distance * left;
          left = 0;
        }
      }
      if (person.path.length) moving = true;
      else person.seated = !STANDING.has(`${person.x},${person.y}`);
    }
    return moving;
  }

  function poly(points, fill) {
    ctx.beginPath();
    points.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
  }

  function drawBox(t) {
    const z1 = t.z0 + t.h;
    const south = t.screen && lit.has(t.screen) ? '#5FE3FF' : shade(t.color, .84);
    poly([iso(t.x0, t.y1, z1), iso(t.x1, t.y1, z1), iso(t.x1, t.y1, t.z0), iso(t.x0, t.y1, t.z0)], south);
    if (t.screen && lit.has(t.screen)) {
      // Code scrolls up a screen someone works at.
      const roll = calm.matches ? 0 : Math.floor(performance.now() / 300);
      for (let i = 0; i < 5; i += 1) {
        const n = (roll + i) * 7 + t.x0;
        const [from, to, z] = [t.x0 + 4 + (n % 3) * 4, t.x0 + 14 + (n % 3) * 4 + (n * 13) % 22, z1 - 5 - i * 4];
        poly([iso(from, t.y1, z), iso(to, t.y1, z), iso(to, t.y1, z - 1.6), iso(from, t.y1, z - 1.6)], i % 2 ? '#0E5F7A' : '#13405E');
      }
    }
    poly([iso(t.x1, t.y0, z1), iso(t.x1, t.y1, z1), iso(t.x1, t.y1, t.z0), iso(t.x1, t.y0, t.z0)], shade(t.color, .68));
    poly([iso(t.x0, t.y0, z1), iso(t.x1, t.y0, z1), iso(t.x1, t.y1, z1), iso(t.x0, t.y1, z1)], t.color);
    if (t.wall) {
      ctx.beginPath();
      ctx.moveTo(...iso(t.x0, t.y1, z1));
      ctx.lineTo(...iso(t.x1, t.y1, z1));
      ctx.lineTo(...iso(t.x1, t.y0, z1));
      ctx.strokeStyle = t.h === TALL ? 'rgb(79 216 255 / .7)' : 'rgb(79 216 255 / .35)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
    for (const d of t.decor ?? []) {
      const color = d.lit && lit.has(d.lit) ? '#5FE3FF' : d.color === GLASS ? windowColor() : d.color;
      const z = [t.z0 + d.z0, t.z0 + d.z1];
      if (d.face === 'south') {
        poly([iso(t.x0 + d.a0, t.y1, z[1]), iso(t.x0 + d.a1, t.y1, z[1]), iso(t.x0 + d.a1, t.y1, z[0]), iso(t.x0 + d.a0, t.y1, z[0])], color);
      } else {
        poly([iso(t.x1, t.y0 + d.a0, z[1]), iso(t.x1, t.y0 + d.a1, z[1]), iso(t.x1, t.y0 + d.a1, z[0]), iso(t.x1, t.y0 + d.a0, z[0])], shade(color, .9));
      }
    }
    const printing = (performance.now() - printedAt) / PRINT_MS;
    if (t.printer && printing < 1) {
      // A sheet slides out of the front, then lies there.
      const out = Math.min(1, printing * 2) * 16;
      poly([iso(t.x0 + 7, t.y1 - 8, z1 + 1), iso(t.x1 - 7, t.y1 - 8, z1 + 1),
        iso(t.x1 - 7, t.y1 - 8 + out, z1 + 1), iso(t.x0 + 7, t.y1 - 8 + out, z1 + 1)], '#FFFFFF');
    }
    if (t.table && (latest?.phase === 'meeting' || latest?.phase === 'review')) {
      // A hologram stands over the table while the team talks or a plan awaits approval.
      const glow = .35 + .15 * Math.sin(performance.now() / 400);
      ctx.globalAlpha = glow;
      poly([iso(440, 125, z1), iso(540, 125, z1), iso(540, 155, z1), iso(440, 155, z1)], NEON);
      ctx.globalAlpha = glow * .5;
      poly([iso(450, 140, z1), iso(530, 140, z1), iso(530, 140, z1 + 70), iso(450, 140, z1 + 70)], NEON);
      ctx.globalAlpha = 1;
    }
  }

  function drawCyl(t) {
    const rx = t.r * Math.SQRT2 * COS;
    const ry = t.r * Math.SQRT2 * SIN;
    const [bx, by] = iso(t.cx, t.cy, t.z0);
    const [, ty] = iso(t.cx, t.cy, t.z0 + t.h);
    ctx.beginPath();
    ctx.ellipse(bx, by, rx, ry, 0, 0, Math.PI);
    ctx.lineTo(bx - rx, ty);
    ctx.ellipse(bx, ty, rx, ry, 0, Math.PI, 0, true);
    ctx.closePath();
    ctx.fillStyle = shade(t.color, .76);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(bx, ty, rx, ry, 0, 0, Math.PI * 2);
    ctx.fillStyle = t.color;
    ctx.fill();
    if (t.leaves) {
      for (const [dx, dy, r, color] of [[0, -8, 1, '#1FA97A'], [-7, -2, .72, '#2ED39A'], [7, -3, .7, '#5CF2BE'], [0, -17, .62, '#5CF2BE']]) {
        ctx.beginPath();
        ctx.arc(bx + dx * t.leaves / 15, ty + dy * t.leaves / 15, t.leaves * r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      }
    }
  }

  function limb(points, width, color) {
    ctx.beginPath();
    points.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
    ctx.lineWidth = width;
    ctx.strokeStyle = color;
    ctx.stroke();
  }

  function dot(x, y, r, fill) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = fill;
    ctx.fill();
  }

  function drawPerson(p, time) {
    const walking = p.path.length > 0;
    const swing = walking && !calm.matches ? Math.sin(time / 110) : 0;
    const bob = Math.abs(swing) * 2.5;
    const [fx, fy] = iso(p.x, p.y);
    const working = p.state === 'working' && !walking;
    const skin = p.spec.skin ?? '#E8C39E';
    // Walking up the screen shows the back; the side tells which way the face turns.
    let away = false, side = 0;
    if (walking) {
      const [tx, ty] = iso(...p.path[0]);
      away = ty < fy - .5;
      side = Math.sign(tx - fx);
    }

    ctx.beginPath();
    ctx.ellipse(fx, fy, 17, 9, 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgb(0 0 0 / .45)';
    ctx.fill();
    if (selected === p.id || working || p.state === 'error') {
      const pulse = working && !calm.matches ? (time / 1400) % 1 : .35;
      ctx.beginPath();
      ctx.ellipse(fx, fy, 20 + pulse * 12, 11 + pulse * 6.5, 0, 0, Math.PI * 2);
      ctx.strokeStyle = p.state === 'error' ? '#C4302B' : p.spec.color;
      ctx.globalAlpha = selected === p.id ? 1 : 1 - pulse;
      ctx.lineWidth = selected === p.id ? 3.5 : 2.5;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    const hip = (p.seated ? 12 : 16) + bob;
    const waist = fy - hip, top = waist - 22;

    // Legs: bent forward on a seat, swinging while walking.
    for (const s of [-1, 1]) {
      const foot = p.seated
        ? [fx + s * 4.5, fy + 1]
        : [fx + s * 3.5 + s * swing * 3.5 * (side || 1), fy - Math.max(0, s * swing) * 2];
      const knee = p.seated ? [[fx + s * 4.5, fy - 9]] : [];
      limb([[fx + s * 3.5, waist], ...knee, foot], 5.5, '#1A2236');
      ctx.beginPath();
      ctx.ellipse(foot[0] + (side || s), foot[1] + 1, 3.4, 1.9, 0, 0, Math.PI * 2);
      ctx.fillStyle = '#0B0F18';
      ctx.fill();
    }

    // Torso: broad at the shoulders, its right side in shadow.
    ctx.beginPath();
    ctx.moveTo(fx - 7, waist);
    ctx.lineTo(fx - 9, top + 5);
    ctx.quadraticCurveTo(fx - 9, top, fx - 4, top);
    ctx.lineTo(fx + 4, top);
    ctx.quadraticCurveTo(fx + 9, top, fx + 9, top + 5);
    ctx.lineTo(fx + 7, waist);
    ctx.quadraticCurveTo(fx, waist + 3, fx - 7, waist);
    ctx.fillStyle = p.spec.color;
    ctx.fill();
    ctx.save();
    ctx.clip();
    ctx.fillStyle = shade(p.spec.color, .78);
    ctx.fillRect(fx + 2.5, top - 1, 9, 30);
    ctx.restore();
    if (!away) poly([[fx - 3.5, top], [fx, top + 4.5], [fx + 3.5, top]], skin);

    // Arms: typing at the desk, a cup at the coffee machine, a hand up while talking, swinging on the way.
    const sleeve = shade(p.spec.color, .88);
    const typing = calm.matches ? 0 : Math.sin(time / 70);
    const wave = calm.matches ? 0 : Math.sin(time / 160) * 2;
    const cup = p.spot === 'coffee' && !walking;
    for (const s of [-1, 1]) {
      let arm;
      if (working && p.seated) arm = [[fx + s * 8.5, top + 3], [fx + s * 10, top + 12], [fx + s * 4, top + 14 + s * typing * 1.3]];
      else if (p.talking && s === 1) arm = [[fx + 8.5, top + 3], [fx + 13, top + 4], [fx + 14 + wave, top - 4]];
      else if (cup && s === -1) arm = [[fx - 8.5, top + 3], [fx - 10.5, top + 12], [fx - 4.5, top + 9]];
      else if (walking) arm = [[fx + s * 9, top + 3], [fx + s * 10, top + 10], [fx + s * 9.5 - s * swing * 4 * (side || 1), top + 17]];
      else arm = [[fx + s * 9, top + 3], [fx + s * 10.5, top + 11], [fx + s * 10, top + 18]];
      limb(arm, 4.5, sleeve);
      const [ax, ay] = arm.at(-1);
      dot(ax, ay, 2.4, skin);
      if (cup && s === -1) {
        ctx.fillStyle = '#F4F7FF';
        ctx.fillRect(ax - 2.5, ay - 5, 5, 5.5);
      }
    }

    // Neck and head.
    limb([[fx, top + 1], [fx, top - 3]], 5, shade(skin, .88));
    const [hx, hy] = [fx, top - 10];
    if (p.spec.long) {
      ctx.beginPath();
      ctx.roundRect(hx - 10.5, hy - 8, 21, 18, 6);
      ctx.fillStyle = p.spec.hair;
      ctx.fill();
    }
    for (const s of [-1, 1]) dot(hx + s * 8.8, hy + 1, 2.3, skin);
    dot(hx, hy, 9, skin);
    if (away) dot(hx, hy - .5, 9.4, p.spec.hair);
    else {
      ctx.beginPath();
      ctx.arc(hx, hy - 1.5, 9.4, Math.PI * .95, Math.PI * 2.05);
      ctx.fillStyle = p.spec.hair;
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(hx - 2.5 + side, hy - 5.5, 5.5, 2.6, -.3, 0, Math.PI * 2);
      ctx.fill();

      // The face: eyes that blink now and then, brows, cheeks and a mouth that shows the mood.
      const look = side * 1.2;
      p.blinkAt ??= [...p.id].reduce((sum, c) => sum + c.charCodeAt(0), 0) * 97 % 4200;
      const blink = !calm.matches && (time + p.blinkAt) % 4200 < 130;
      for (const s of [-1, 1]) {
        const ex = hx + s * 3.3 + look;
        if (blink) limb([[ex - 1.4, hy + .8], [ex + 1.4, hy + .8]], 1.2, '#1B1B24');
        else {
          ctx.beginPath();
          ctx.ellipse(ex, hy + .5, 1.4, 1.9, 0, 0, Math.PI * 2);
          ctx.fillStyle = '#1B1B24';
          ctx.fill();
          dot(ex + .5, hy - .2, .55, '#FFFFFF');
        }
        const frown = p.state === 'error' ? -s * .8 : working ? s * .4 : 0;
        limb([[hx + s * 1.8 + look, hy - 3 - frown], [hx + s * 4.9 + look, hy - 3.6 + frown]], 1.2, p.spec.hair);
        ctx.globalAlpha = .3;
        dot(hx + s * 5.6 + look, hy + 3.4, 1.8, '#FF7A8A');
        ctx.globalAlpha = 1;
      }
      ctx.beginPath();
      if (p.talking) {
        const open = calm.matches ? 1.6 : 0.6 + Math.abs(Math.sin(time / 90)) * 2.4;
        ctx.ellipse(hx + look, hy + 4.8, 2.6, open, 0, 0, Math.PI * 2);
        ctx.fillStyle = '#5A1E1E';
        ctx.fill();
      } else {
        if (p.state === 'error') ctx.arc(hx + look, hy + 7.2, 2.6, Math.PI * 1.2, Math.PI * 1.8);
        else if (working) { ctx.moveTo(hx + look - 1.8, hy + 4.8); ctx.lineTo(hx + look + 1.8, hy + 4.8); }
        else ctx.arc(hx + look, hy + 3, 2.8, Math.PI * .18, Math.PI * .82);
        ctx.lineWidth = 1.2;
        ctx.strokeStyle = '#7A3B2E';
        ctx.stroke();
      }
    }
    if (p.spec.headset) {
      ctx.beginPath();
      ctx.arc(hx, hy, 10.5, Math.PI * 1.05, Math.PI * 1.95);
      ctx.lineWidth = 1.8;
      ctx.strokeStyle = '#2B3448';
      ctx.stroke();
      for (const s of [-1, 1]) dot(hx + s * 9.6, hy + 1, 2.6, '#2B3448');
      if (!away) limb([[hx + 9.6, hy + 2], [hx + 6, hy + 7], [hx + 3, hy + 6.5]], 1.2, '#2B3448');
    }
    ctx.restore();
    p.head = [hx, hy];
  }

  function drawFloor() {
    ctx.save();
    ctx.transform(COS, SIN, -COS, SIN, 0, 0); // plan coordinates now land on the floor
    for (const room of ROOMS) {
      ctx.fillStyle = room.floor === 'wood' ? '#1D1A33' : room.floor === 'tile' ? '#16213A' : room.floor;
      ctx.fillRect(room.x, room.y, room.w, room.h);
      ctx.lineWidth = 1;
      ctx.beginPath();
      // Deck plates: the command room's are gold-seamed, the galley's finer.
      const step = room.floor === 'tile' ? 24 : 40;
      ctx.strokeStyle = room.floor === 'wood' ? 'rgb(255 181 71 / .14)' : 'rgb(120 190 255 / .08)';
      for (let y = room.y + step; y < room.y + room.h; y += step) { ctx.moveTo(room.x, y); ctx.lineTo(room.x + room.w, y); }
      for (let x = room.x + step; x < room.x + room.w; x += step) { ctx.moveTo(x, room.y); ctx.lineTo(x, room.y + room.h); }
      ctx.stroke();
    }
    const pad = (x, y, w, h, color) => {
      ctx.fillStyle = `${color}14`; ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = `${color}88`; ctx.lineWidth = 2; ctx.strokeRect(x + 8, y + 8, w - 16, h - 16);
      ctx.strokeStyle = `${color}33`; ctx.lineWidth = 1; ctx.strokeRect(x + 16, y + 16, w - 32, h - 32);
    };
    pad(60, 164, 210, 92, '#FFB547');
    pad(45, 395, 515, 270, '#4C9BFF');
    pad(870, 430, 200, 150, '#5CF2BE');
    ctx.fillStyle = 'rgb(79 216 255 / .08)'; ctx.fillRect(90, 301, 780, 18);   // corridor light strip
    ctx.fillStyle = 'rgb(79 216 255 / .5)'; ctx.fillRect(90, 309, 780, 2);
    ctx.fillStyle = '#2A3550'; ctx.fillRect(28, 290, 34, 40);                  // airlock plate
    signs('floor');
    ctx.restore();
  }

  /** Paint room names where *where* says: lying on the floor, or upright on a back wall. */
  function signs(where) {
    ctx.font = '600 22px Bahnschrift, "Segoe UI", sans-serif';
    ctx.fillStyle = 'rgb(120 220 255 / .6)';
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    for (const room of ROOMS) {
      if (room.sign?.[0] !== where) continue;
      if (where === 'floor') { ctx.fillText(room.name, room.sign[1], room.sign[2]); continue; }
      ctx.save();
      // Upright on the wall: letters run along the wall and stand straight up.
      if (where === 'north') ctx.transform(COS, SIN, 0, 1, ...iso(room.sign[1], 23, TALL - 27));
      else ctx.transform(COS, -SIN, 0, 1, ...iso(23, room.sign[1], TALL - 27));
      ctx.fillText(room.name, 0, 0);
      ctx.restore();
    }
  }

  /** Stars, a nebula and a planet, fixed to the screen so the station seems to drift past them. */
  function drawSpace(width, height) {
    const sky = ctx.createRadialGradient(width * .7, height * .2, 0, width * .7, height * .2, Math.max(width, height));
    sky.addColorStop(0, '#16224A');
    sky.addColorStop(.45, '#0A1028');
    sky.addColorStop(1, '#04060F');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);
    const nebula = ctx.createRadialGradient(width * .15, height * .85, 0, width * .15, height * .85, width * .5);
    nebula.addColorStop(0, 'rgb(140 70 255 / .18)');
    nebula.addColorStop(1, 'rgb(140 70 255 / 0)');
    ctx.fillStyle = nebula;
    ctx.fillRect(0, 0, width, height);
    for (const [sx, sy, r, a] of STARS) {
      ctx.globalAlpha = a;
      ctx.fillStyle = '#FFFFFF';
      ctx.fillRect(sx * width, sy * height, r, r);
    }
    ctx.globalAlpha = 1;
    const [px, py, pr] = [width * .9, height * .9, Math.min(width, height) * .22];
    const planet = ctx.createRadialGradient(px - pr * .4, py - pr * .4, pr * .1, px, py, pr);
    planet.addColorStop(0, '#3B7BD9');
    planet.addColorStop(.7, '#123A7A');
    planet.addColorStop(1, '#050B1E');
    ctx.beginPath();
    ctx.arc(px, py, pr, 0, Math.PI * 2);
    ctx.fillStyle = planet;
    ctx.fill();
    ctx.strokeStyle = 'rgb(120 200 255 / .35)';
    ctx.lineWidth = 3;
    ctx.stroke();
  }

  function drawSlab() {
    const [x0, y0, x1, y1, drop] = [17, 17, 1183, 703, 18];
    poly([iso(x0, y1), iso(x1, y1), iso(x1, y1, -drop), iso(x0, y1, -drop)], '#0F1626');
    poly([iso(x1, y0), iso(x1, y1), iso(x1, y1, -drop), iso(x1, y0, -drop)], '#0A0F1B');
    poly([iso(x0, y0), iso(x1, y0), iso(x1, y1), iso(x0, y1)], '#111A2C');
    // The hull's running lights.
    ctx.beginPath();
    ctx.moveTo(...iso(x0, y1, -drop / 2)); ctx.lineTo(...iso(x1, y1, -drop / 2)); ctx.lineTo(...iso(x1, y0, -drop / 2));
    ctx.strokeStyle = 'rgb(79 216 255 / .55)';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  /** Names and speech bubbles are drawn at screen size so they stay readable when the office is small. */
  function drawLabels(ratio) {
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const onScreen = ([x, y]) => [(x - VIEW.x) * scale + offset[0], (y - VIEW.y) * scale + offset[1]];
    const pill = (x, y, text, fill, ink, stroke) => {
      const width = ctx.measureText(text).width + 14;
      ctx.beginPath();
      ctx.roundRect(x - width / 2, y - 9, width, 18, 9);
      ctx.fillStyle = fill;
      ctx.fill();
      if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1.2; ctx.stroke(); }
      ctx.fillStyle = ink;
      ctx.fillText(text, x, y + .5);
    };
    /** A speech bubble of up to three lines, its tail pointing down at *y*. */
    const bubble = (x, y, text, edge) => {
      const lines = wrap(text, 210).slice(0, 3);
      const width = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 18;
      const height = lines.length * 15 + 10;
      const top = y - height - 6;
      ctx.beginPath();
      ctx.roundRect(x - width / 2, top, width, height, 8);
      ctx.moveTo(x - 5, top + height); ctx.lineTo(x, top + height + 6); ctx.lineTo(x + 5, top + height);
      ctx.fillStyle = HUD;
      ctx.fill();
      ctx.strokeStyle = edge;
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.fillStyle = INK;
      lines.forEach((line, i) => ctx.fillText(line, x, top + 12 + i * 15));
    };
    const wrap = (text, max) => {
      const lines = [''];
      for (const word of text.split(' ')) {
        const next = lines.at(-1) ? `${lines.at(-1)} ${word}` : word;
        if (ctx.measureText(next).width > max && lines.at(-1)) lines.push(word); else lines[lines.length - 1] = next;
      }
      if (lines.length > 3) lines[2] = `${lines[2].slice(0, -1)}…`;
      return lines;
    };
    objectHits = OBJECTS.map(([id, x, y, z]) => [id, ...onScreen(iso(x, y, z)), Math.max(14, 30 * scale)]);
    // Each taken desk's screen opens its owner's computer.
    for (const t of screens) {
      const owner = t.screen.startsWith('slot') ? Object.values(people).find((p) => `slot${p.slot}` === t.screen)?.id : t.screen;
      if (people[owner]) objectHits.push([`pc:${owner}`, ...onScreen(iso((t.x0 + t.x1) / 2, t.y1, t.z0 + 12)), Math.max(10, 18 * scale)]);
    }
    // The board and clock hang on the wall, behind whatever people say.
    drawBoard(onScreen);
    drawClock(onScreen);
    if (plan?.total) {
      const [x, y] = onScreen(iso(20, 140, 86));
      ctx.font = '600 11px Bahnschrift, "Segoe UI", sans-serif';
      pill(x, y, `📋 Plan ${plan.done}/${plan.total}`, HUD, INK, plan.done === plan.total ? '#39E09B' : NEON);
    }
    const byHeight = Object.values(people).filter((p) => p.head).sort((a, b) => a.head[1] - b.head[1]);
    for (const p of byHeight) {
      const [x, y] = onScreen(p.head);
      const above = y - 9 * scale - 13;
      ctx.font = '600 11.5px Bahnschrift, "Segoe UI", sans-serif';
      pill(x, above, p.spec.short, selected === p.id ? p.spec.color : HUD, selected === p.id ? '#081020' : INK, p.spec.color);
      if (p.says && (!p.path.length || p.saying)) {
        ctx.font = '11.5px Bahnschrift, "Segoe UI", sans-serif';
        bubble(x, above - 10, p.says, p.spec.color);
      }
      p.hit = [x, y];
      if (p.code && !p.path.length) drawCode(x, above - (p.says ? 74 : 16), p);
    }
    if (performance.now() - printedAt < PRINT_MS) {
      const [x, y] = onScreen(iso(600, 424, 60));
      ctx.font = '600 11px Bahnschrift, "Segoe UI", sans-serif';
      pill(x, y, '🖨 Rapor hazır', HUD, INK, NEON);
    }
  }

  /** A hologram of the code someone is writing: a few lines rolling past, the file on top. */
  function drawCode(x, bottom, p) {
    const lines = p.code.split('\n').map((l) => (l.length > 38 ? `${l.slice(0, 37)}…` : l));
    const shown = 6;
    const start = calm.matches || lines.length <= shown ? 0 : Math.floor(performance.now() / 900) % (lines.length - shown + 1);
    const view = lines.slice(start, start + shown);
    const width = 230;
    const height = 20 + view.length * 13;
    const top = bottom - height;
    ctx.save();
    ctx.globalAlpha = .9;
    ctx.beginPath();
    ctx.roundRect(x - width / 2, top, width, height, 6);
    ctx.fillStyle = 'rgb(6 20 38 / .82)';
    ctx.fill();
    ctx.strokeStyle = p.spec.color;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.textAlign = 'left';
    ctx.font = '600 10px Bahnschrift, "Segoe UI", sans-serif';
    ctx.fillStyle = p.spec.color;
    ctx.fillText(`✎ ${p.file || 'kod'}`, x - width / 2 + 8, top + 10);
    ctx.font = '10px "JetBrains Mono", Consolas, monospace';
    ctx.fillStyle = '#9FF0FF';
    view.forEach((line, i) => ctx.fillText(line, x - width / 2 + 8, top + 24 + i * 13));
    ctx.restore();
    ctx.textAlign = 'center';
  }

  /** The meeting room's screen doubles as the team's board: who is on what. */
  function boardLines() {
    if (!latest) return [];
    const mode = BOARD_MODES[boardMode];
    if (mode === 'AJANLAR') {
      return latest.agents.filter((a) => a.id !== 'cagan')
        .map((a) => `${a.state === 'working' ? '▶' : a.state === 'error' ? '!' : '·'} ${PEOPLE[a.id]?.short ?? a.name}: ${a.activity || (a.state === 'idle' ? 'boşta' : a.state)}`);
    }
    if (mode === 'TOKEN · BUGÜN') {
      if (!usage) return ['Ölçülüyor…'];
      const k = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n));
      return [`Claude  giriş ${k(usage.claude.input)} · çıkış ${k(usage.claude.output)}`,
        `Claude  önbellek ${k(usage.claude.cache)}`,
        `Gemini  giriş ${k(usage.gemini.input)} · çıkış ${k(usage.gemini.output)}`];
    }
    if (mode === 'SON KARARLAR') return decisions.length ? decisions.slice(-3).map((d) => `✓ ${d}`) : ['Henüz toplantı yok'];
    const open = (latest.tasks ?? []).filter((t) => ['running', 'queued', 'proposed'].includes(t.status));
    const names = Object.fromEntries(latest.agents.map((a) => [a.id, a.name]));
    const mark = { running: '▶', queued: '…', proposed: '?' };
    if (open.length) return open.slice(-3).map((t) => `${mark[t.status]} ${names[t.to] ?? t.to}: ${t.text}`);
    const busy = latest.agents.filter((a) => a.state === 'working' && a.activity);
    if (busy.length) return busy.slice(0, 3).map((a) => `▶ ${PEOPLE[a.id]?.short ?? a.name}: ${a.activity}`);
    return ['Açık iş yok'];
  }

  function drawBoard(onScreen) {
    const lines = boardLines().map((line) => shorten(line, 34));
    const [cx, cy] = onScreen(iso(470, 20, 96));
    ctx.font = '10.5px Bahnschrift, "Segoe UI", sans-serif';
    const width = Math.max(90, ...lines.map((l) => ctx.measureText(l).width)) + 16;
    const height = 18 + lines.length * 14;
    ctx.beginPath();
    ctx.roundRect(cx - width / 2, cy - height, width, height, 6);
    ctx.fillStyle = HUD;
    ctx.fill();
    ctx.strokeStyle = 'rgb(79 216 255 / .6)';
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.textAlign = 'left';
    ctx.fillStyle = NEON;
    ctx.font = '600 10px Bahnschrift, "Segoe UI", sans-serif';
    ctx.fillText(`${BOARD_MODES[boardMode]}  ›`, cx - width / 2 + 8, cy - height + 10);
    ctx.fillStyle = '#EDF0EE';
    ctx.font = '10.5px Bahnschrift, "Segoe UI", sans-serif';
    lines.forEach((line, i) => ctx.fillText(line, cx - width / 2 + 8, cy - height + 24 + i * 14));
    ctx.textAlign = 'center';
  }

  /** A wall clock in Cuba's room, telling the real time. */
  function drawClock(onScreen) {
    const [x, y] = onScreen(iso(282, 22, 92));
    const r = Math.max(7, 13 * scale * 1.4);
    const now = new Date();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = HUD;
    ctx.fill();
    ctx.strokeStyle = NEON;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    const hand = (turns, length, width) => {
      const angle = turns * Math.PI * 2 - Math.PI / 2;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x + Math.cos(angle) * r * length, y + Math.sin(angle) * r * length);
      ctx.lineWidth = width;
      ctx.stroke();
    };
    hand(((now.getHours() % 12) + now.getMinutes() / 60) / 12, .5, 2);
    hand(now.getMinutes() / 60, .78, 1.4);
  }

  function draw(time) {
    const box = canvas.getBoundingClientRect();
    const ratio = devicePixelRatio || 1;
    if (!box.width || !box.height) return;
    if (canvas.width !== Math.round(box.width * ratio) || canvas.height !== Math.round(box.height * ratio)) {
      canvas.width = Math.round(box.width * ratio);
      canvas.height = Math.round(box.height * ratio);
    }
    scale = Math.min(box.width / VIEW.w, box.height / VIEW.h) * zoom;
    offset = [(box.width - VIEW.w * scale) / 2 + pan[0], (box.height - VIEW.h * scale) / 2 + pan[1]];
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    drawSpace(box.width, box.height);
    const k = ratio * scale;
    ctx.setTransform(k, 0, 0, k, (offset[0] - VIEW.x * scale) * ratio, (offset[1] - VIEW.y * scale) * ratio);
    drawSlab();
    drawFloor();
    const standing = Object.values(people).map((p) => ({
      ...p, ref: p, x0: p.x - 7, y0: p.y - 7, x1: p.x + 7, y1: p.y + 7, z0: p.seated ? 12 : 0, order: 1e6,
    }));
    for (const thing of paintOrder(fixed, after, standing)) {
      if (thing.kind === 'box') drawBox(thing);
      else if (thing.kind === 'cyl') drawCyl(thing);
      else drawPerson(thing.ref, time);
    }
    signs('north');
    signs('west');
    drawLabels(ratio);
  }

  function frame(time) {
    requestAnimationFrame(frame);
    const moving = walk(Math.min(.1, (time - lastFrame) / 1000));
    const alive = moving || Object.values(people).some((p) => p.state === 'working')
      || performance.now() - printedAt < PRINT_MS || latest?.phase === 'meeting' || latest?.phase === 'review';
    // Nothing moves in a resting office, so it is not redrawn.
    if (!dirty && !(alive && !calm.matches)) { lastFrame = time; return; }
    if (alive && !moving && time - lastFrame < 33) return; // the pulse needs no more than 30 frames a second
    lastFrame = time;
    dirty = false;
    draw(time);
  }

  function objectAt(event) {
    const box = canvas.getBoundingClientRect();
    const [x, y] = [event.clientX - box.left, event.clientY - box.top];
    const hit = objectHits.find(([, ox, oy, r]) => Math.hypot(x - ox, y - oy) < r);
    if (!hit) return null;
    return OBJECTS.find(([id]) => id === hit[0]) ?? [hit[0], 0, 0, 0, `${people[hit[0].slice(3)]?.spec.short} bilgisayarı: ne yaptığını gör`];
  }

  function personAt(event) {
    const box = canvas.getBoundingClientRect();
    const [x, y] = [event.clientX - box.left, event.clientY - box.top];
    return Object.values(people)
      .filter((p) => p.hit && Math.abs(x - p.hit[0]) < 22 && y > p.hit[1] - 32 && y < p.hit[1] + 34 * scale + 8)
      .sort((a, b) => b.hit[1] - a.hit[1])[0];
  }

  // Drag to move the office, wheel to zoom towards the pointer, double-click to see it all again.
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => {
    drag = { x: e.clientX, y: e.clientY, pan: [...pan], moved: false };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) {
      const thing = !personAt(e) && objectAt(e);
      canvas.style.cursor = personAt(e) || thing ? 'pointer' : 'grab';
      canvas.title = thing ? thing[4] : '';
      return;
    }
    const [dx, dy] = [e.clientX - drag.x, e.clientY - drag.y];
    if (Math.hypot(dx, dy) > 4) drag.moved = true;
    if (!drag.moved) return;
    pan = [drag.pan[0] + dx, drag.pan[1] + dy];
    canvas.style.cursor = 'grabbing';
    dirty = true;
  });
  canvas.addEventListener('pointerup', (e) => {
    if (drag && !drag.moved) {
      const p = personAt(e);
      const thing = !p && objectAt(e);
      if (p) onSelect(p.id);
      else if (thing?.[0] === 'board') { boardMode = (boardMode + 1) % BOARD_MODES.length; dirty = true; }
      if (thing) onObject(thing[0]);
    }
    drag = null;
  });
  canvas.addEventListener('pointercancel', () => { drag = null; });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    zoomBy(Math.exp(-e.deltaY * .0015), e);
  }, { passive: false });
  canvas.addEventListener('dblclick', () => { zoom = FIT_ZOOM; pan = [0, 0]; dirty = true; });

  /** Zoom by *factor*, keeping the point under *at* (a pointer event) where it is. */
  function zoomBy(factor, at) {
    const box = canvas.getBoundingClientRect();
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom * factor));
    const [cx, cy] = at ? [at.clientX - box.left, at.clientY - box.top] : [box.width / 2, box.height / 2];
    // The canvas centre moves with pan; points keep their distance to it in proportion to the zoom.
    const [mx, my] = [box.width / 2 + pan[0], box.height / 2 + pan[1]];
    pan = [pan[0] + (cx - mx) * (1 - next / zoom), pan[1] + (cy - my) * (1 - next / zoom)];
    zoom = next;
    dirty = true;
  }

  const controls = document.createElement('div');
  controls.className = 'office-controls';
  for (const [label, title, act] of [
    ['+', 'Yakınlaştır', () => zoomBy(1.25)],
    ['−', 'Uzaklaştır', () => zoomBy(.8)],
    ['⟲', 'Ofisin tamamı (çift tık)', () => { zoom = FIT_ZOOM; pan = [0, 0]; dirty = true; }],
  ]) {
    const button = Object.assign(document.createElement('button'), { type: 'button', textContent: label, title });
    button.setAttribute('aria-label', title);
    button.addEventListener('click', act);
    controls.append(button);
  }
  canvas.after(controls);
  new ResizeObserver(() => { dirty = true; }).observe(canvas);
  // People drift from the coffee machine to the sofa as time passes.
  // People drift on as time passes; the clock and the windows follow the hour.
  setInterval(arrange, 5000);
  requestAnimationFrame(frame);

  return {
    update(snapshot) { latest = { ...snapshot, agents: [...snapshot.agents, BOSS] }; seenAt = Date.now(); arrange(); },
    select(id) { selected = id; dirty = true; },
    where(agent) { return latest ? describe(agent, spotOf(agent, latest), latest) : ''; },
    color(id) { return PEOPLE[id]?.color ?? people[id]?.spec.color ?? '#7F8DA6'; },
    /** A report came out: the printer prints it. */
    print() { printedAt = performance.now(); dirty = true; },
    setUsage(next) { usage = next; dirty = true; },
    setDecisions(next) { decisions = next; dirty = true; },
    setPlan(next) { plan = next; dirty = true; },
  };
}
