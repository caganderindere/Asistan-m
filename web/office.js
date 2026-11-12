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
  lider:       { short: 'Cuba',        color: '#FFB547', hair: '#2B211B', desk: [165, 180], meeting: [366, 140], coffee: [1000, 84],  sofa: [930, 388],  visit: [165, 180] },
  kidemli:     { short: 'Kıdemli',     color: '#FF5FA2', hair: '#4A3426', desk: [145, 516], meeting: [428, 88],  coffee: [1052, 84],  sofa: [824, 465],  visit: [70, 240] },
  gelistirici: { short: 'Geliştirici', color: '#4C9BFF', hair: '#1F1B18', desk: [375, 516], meeting: [552, 88],  coffee: [1104, 84],  sofa: [824, 525],  visit: [115, 248] },
  testci:      { short: 'Testçi',      color: '#39E09B', hair: '#6B4A2E', desk: [810, 162], meeting: [428, 192], coffee: [1016, 222], sofa: [824, 585],  visit: [215, 248] },
  asistan:     { short: 'Asistan',     color: '#FF8A3D', hair: '#3A2A20', desk: [650, 510], meeting: [552, 192], coffee: [1108, 222], sofa: [1000, 388], visit: [260, 240] },
  // The boss: not in the team's snapshots, so the office adds him itself.
  cagan:       { short: 'Çağan',       color: '#C9D6EE', hair: '#241C17', desk: [255, 110], meeting: [614, 140], coffee: [1150, 160], sofa: [1000, 465], visit: [255, 110] },
};
// Spots where one stands; everywhere else there is a seat.
const STANDING = new Set([
  '1000,84', '1052,84', '1104,84', '1150,160',
  '70,240', '115,248', '215,248', '260,240', '255,110',
]);
const BOSS = { id: 'cagan', name: 'Çağan', state: 'idle', activity: '', seconds: 0, log: [] };

// door: [just inside the room, the matching point in the corridor]
// sign: where the room's name is painted: high on the back wall behind it
// ('north' at x, 'west' at y), or on a clear patch of floor.
const ROOMS = [
  { name: 'Yönetim',        x: 20,  y: 20,  w: 280, h: 250, floor: 'wood',    sign: ['north', 40],       door: [[165, 255], [165, 310]] },
  { name: 'Toplantı odası', x: 300, y: 20,  w: 380, h: 250, floor: '#152038', sign: ['north', 318],      door: [[490, 255], [490, 310]] },
  { name: 'Kalite',         x: 680, y: 20,  w: 260, h: 250, floor: '#11262A', sign: ['north', 698],      door: [[815, 255], [815, 310]] },
  { name: 'Mutfak',         x: 940, y: 20,  w: 240, h: 330, floor: 'tile',    sign: ['north', 958],      door: [[960, 310], [920, 310]] },
  { name: '',               x: 20,  y: 270, w: 920, h: 80,  floor: '#0F1828', sign: null,                door: null },
  { name: 'Mühendislik',    x: 20,  y: 350, w: 500, h: 350, floor: '#131D34', sign: ['west', 684],       door: [[270, 368], [270, 310]] },
  { name: 'Destek',         x: 520, y: 350, w: 260, h: 350, floor: '#1E1A30', sign: ['floor', 596, 580], door: [[655, 368], [655, 310]] },
  { name: 'Dinlenme',       x: 780, y: 350, w: 400, h: 350, floor: '#181834', sign: ['floor', 880, 676], door: [[850, 368], [850, 310]] },
];
const KITCHEN_TO_LOUNGE = [[1070, 332], [1070, 368]];

// [x1, y1, x2, y2, height]; the gaps between them are the doors.
const TALL = 112, LOW = 28, CUT = 9;
const WALLS = [
  [20, 20, 1180, 20, TALL], [20, 20, 20, 285, TALL], [20, 335, 20, 700, TALL],
  [1180, 20, 1180, 700, CUT], [20, 700, 1180, 700, CUT],
  [20, 270, 140, 270, LOW], [190, 270, 460, 270, LOW], [520, 270, 790, 270, LOW], [840, 270, 940, 270, LOW],
  [20, 350, 240, 350, LOW], [300, 350, 630, 350, LOW], [680, 350, 820, 350, LOW], [880, 350, 1040, 350, LOW], [1100, 350, 1180, 350, LOW],
  [300, 20, 300, 270, LOW], [680, 20, 680, 270, LOW], [940, 20, 940, 285, LOW], [940, 335, 940, 350, LOW],
  [520, 350, 520, 700, LOW], [780, 350, 780, 700, LOW],
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
    { face: 'south', a0: 684, a1: 790, z0: 38, z1: 76, color: '#CFE9FF' },                   // Kalite board
    { face: 'south', a0: 692, a1: 718, z0: 56, z1: 70, color: '#39E09B' },
    { face: 'south', a0: 724, a1: 750, z0: 56, z1: 70, color: '#FFB547' },
    { face: 'south', a0: 756, a1: 782, z0: 56, z1: 70, color: '#FF4D5E' },
    { face: 'south', a0: 830, a1: 905, z0: 34, z1: 78, color: glass },
    { face: 'south', a0: 980, a1: 1140, z0: 52, z1: 82, color: glass },                      // above the counter
  ];
  west[0].decor = [{ face: 'east', a0: 70, a1: 170, z0: 34, z1: 76, color: '#CFE9FF' }];     // Yönetim whiteboard
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

  // Kalite
  desk('testci', 735, 82, 150, 58, 2);
  chair(810, 162);
  const rack = box(898, 60, 30, 150, 70, '#1A2236');
  rack.decor = [0, 1, 2, 3].flatMap((i) => [
    { face: 'east', a0: 10 + i * 36, a1: 34 + i * 36, z0: 10, z1: 60, color: '#081020' },
    { face: 'east', a0: 26 + i * 36, a1: 30 + i * 36, z0: 50, z1: 54, color: i % 2 ? '#39E09B' : '#FFB547' },
  ]);
  plant(916, 244);
  // Reports come out here.
  box(698, 206, 36, 28, 30, '#3A4766', { printer: true });

  // Mutfak
  box(948, 26, 224, 36, 30, '#2A3550');
  box(962, 32, 38, 24, 20, '#0B111C', { z0: 30 });                        // coffee machine
  for (const x of [1016, 1030, 1044]) cyl(x, 46, 4.5, 7, '#9FB3D1', { z0: 30 });
  box(1066, 34, 44, 22, 1, '#4A5A7A', { z0: 30 });                        // sink
  box(1122, 34, 40, 22, 1.5, '#141B2B', { z0: 30 });                      // hob
  box(1138, 80, 36, 54, 66, '#3A4766');                                   // fridge
  for (const [x, y] of [[1016, 222], [1108, 222], [1062, 270]]) cyl(x, y, 9, 16, '#24304A');
  cyl(1062, 222, 27, 28, '#33415E');
  cyl(1054, 216, 4.5, 7, '#9FB3D1', { z0: 28 }); cyl(1072, 228, 4.5, 7, '#9FB3D1', { z0: 28 });
  plant(1120, 326);
  box(1150, 292, 22, 38, 26, '#1A2236');                                  // bin

  // Koridor
  box(880, 276, 22, 22, 34, '#3A4766');                                   // water cooler
  cyl(891, 287, 7, 16, '#4FD8FF', { z0: 34 });
  plant(560, 288, .85);

  // Mühendislik
  books(box(40, 358, 100, 16, 46, '#1E2840'), 100, 8);
  desk('kidemli', 65, 432, 160, 62, 2);
  desk('gelistirici', 295, 432, 160, 62);
  chair(145, 516); chair(375, 516);
  box(400, 600, 90, 60, 24, '#33415E');                                   // spare desk
  box(423, 610, 44, 4, 24, '#0B111C', { z0: 24 });
  plant(492, 380, 1.1); plant(496, 674, 1.1);

  // Destek
  desk('asistan', 575, 430, 150, 58);
  chair(650, 510);
  const cabinets = box(536, 600, 46, 84, 42, '#2C3A52');
  cabinets.decor = [0, 1, 2].map((i) => ({ face: 'east', a0: 4 + i * 27, a1: 26 + i * 27, z0: 6, z1: 36, color: '#3E4E6E' }));
  box(700, 640, 60, 44, 22, '#33415E');
  box(706, 646, 48, 32, 14, '#4A5A7A', { z0: 22 });                       // printer
  plant(756, 378);

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

const roomOf = ([x, y]) => ROOMS.find((r) => x >= r.x && x < r.x + r.w && y >= r.y && y < r.y + r.h);

/** The corners to walk through from *from* to *to*: out of one door, along the corridor, in at the other. */
function route(from, to) {
  const a = roomOf(from);
  const b = roomOf(to);
  if (!a || !b || a === b) return [to];
  const pair = new Set([a.name, b.name]);
  if (pair.has('Mutfak') && pair.has('Dinlenme')) {
    const through = a.name === 'Mutfak' ? KITCHEN_TO_LOUNGE : [...KITCHEN_TO_LOUNGE].reverse();
    return [...through, to];
  }
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
  ['printer', 716, 220, 40, 'Çıktılar: ekibin raporları'],
  ['board', 470, 20, 96, 'Pano: görünümü değiştir'],
  ['clock', 282, 22, 92, 'Takvim ve hafıza'],
  ['shelf', 105, 34, 62, 'Proje belgeleri'],
  ['table', 490, 140, 30, 'Akış: kim ne dedi'],
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
      if (snapshot.review.speaker === agent.id) return '…';
      const last = snapshot.review.lines.at(-1);
      return last?.who === agent.id ? shorten(last.text, 160) : '';
    }
    if (agent.id === 'lider' && snapshot.question) return '?';
    if (agent.state === 'error') return 'Hata';
    return agent.state === 'working' && spot === 'desk' ? shorten(agent.activity, 90) : '';
  }

  function arrange() {
    if (!latest) return;
    for (const agent of latest.agents) {
      const person = people[agent.id];
      if (!person) continue;
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
    }
    lit = new Set(latest.agents.filter((a) => a.state === 'working' && people[a.id]?.spot === 'desk').map((a) => a.id));
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

  function drawPerson(p, time) {
    const walking = p.path.length > 0;
    const seat = p.seated ? 12 : 0;
    const bob = walking ? Math.abs(Math.sin(time / 110)) * 3 : 0;
    const [fx, fy] = iso(p.x, p.y);
    const working = p.state === 'working' && !walking;

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
    if (!p.seated) drawCyl({ cx: p.x, cy: p.y, r: 6.5, z0: 0, h: 16, color: '#141B2B' });      // legs
    const torso = { cx: p.x, cy: p.y, r: 8.5, z0: (p.seated ? seat : 16) + bob, h: 22, color: p.spec.color };
    drawCyl(torso);
    const [hx, hy] = iso(p.x, p.y, torso.z0 + torso.h + 7);
    ctx.beginPath();
    ctx.arc(hx, hy, 9, 0, Math.PI * 2);
    ctx.fillStyle = '#E8C39E';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(hx, hy - 1.5, 9.2, Math.PI * 1.02, Math.PI * 1.98);
    ctx.fillStyle = p.spec.hair;
    ctx.fill();
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
    pad(60, 540, 300, 130, '#4C9BFF');
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
    // The board and clock hang on the wall, behind whatever people say.
    drawBoard(onScreen);
    drawClock(onScreen);
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
    }
    if (performance.now() - printedAt < PRINT_MS) {
      const [x, y] = onScreen(iso(716, 220, 60));
      ctx.font = '600 11px Bahnschrift, "Segoe UI", sans-serif';
      pill(x, y, '🖨 Rapor hazır', HUD, INK, NEON);
    }
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
    return hit ? OBJECTS.find(([id]) => id === hit[0]) : null;
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
    color(id) { return PEOPLE[id]?.color ?? '#7F8DA6'; },
    /** A report came out: the printer prints it. */
    print() { printedAt = performance.now(); dirty = true; },
    setUsage(next) { usage = next; dirty = true; },
    setDecisions(next) { decisions = next; dirty = true; },
  };
}
