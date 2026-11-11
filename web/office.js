// The office, seen from a corner above. Where each person is shows their real
// state: at the desk while working, around the table while a plan awaits
// approval or the team talks over finished work, by the coffee machine just
// after finishing, on a sofa when idle for long.

const COS = Math.cos(Math.PI / 6);
const SIN = 0.5;
const VIEW = { x: -610, y: -126, w: 1635, h: 1102 }; // what the projection covers, in drawing units
const COFFEE_BREAK_S = 90;
const WALK_SPEED = 240; // plan units per second
const INK = '#1D2733';
const GLASS = '#B5DAEE';
const PRINT_MS = 3500;
const QUOTE_MS = 4000;
// What people say as they take on work and hand it back.
const STARTING = ['Hallediyorum!', 'Hemen bakıyorum.', 'Tamamdır, başlıyorum.', 'Bende.', 'Üstüme aldım.'];
const FINISHED = ['Bitti!', 'Teslim ettim.', 'Tamam, hazır.', 'İş tamam.', 'Raporu bıraktım.'];
const pick = (list) => list[Math.floor(Math.random() * list.length)];

/** The window glass at this hour: daylight, dusk, night, dawn. */
function windowColor(hour = new Date().getHours()) {
  if (hour >= 7 && hour < 17) return GLASS;
  if (hour >= 17 && hour < 19) return '#E8B98A';
  if (hour === 6) return '#C9C2E0';
  return '#2B3A55';
}

const PEOPLE = {
  lider:       { short: 'Daim',      color: '#C8860B', hair: '#2B211B', desk: [165, 180], meeting: [366, 140], coffee: [1000, 84],  sofa: [930, 388],  visit: [165, 180] },
  kidemli:     { short: 'Kıdemli',     color: '#A23B72', hair: '#4A3426', desk: [145, 516], meeting: [428, 88],  coffee: [1052, 84],  sofa: [824, 465],  visit: [70, 240] },
  gelistirici: { short: 'Geliştirici', color: '#2B6CD4', hair: '#1F1B18', desk: [375, 516], meeting: [552, 88],  coffee: [1104, 84],  sofa: [824, 525],  visit: [115, 248] },
  testci:      { short: 'Testçi',      color: '#2D8F5B', hair: '#6B4A2E', desk: [810, 162], meeting: [428, 192], coffee: [1016, 222], sofa: [824, 585],  visit: [215, 248] },
  asistan:     { short: 'Asistan',     color: '#D9622B', hair: '#3A2A20', desk: [650, 510], meeting: [552, 192], coffee: [1108, 222], sofa: [1000, 388], visit: [260, 240] },
  // The boss: not in the team's snapshots, so the office adds him itself.
  cagan:       { short: 'Çağan',       color: '#1D2733', hair: '#241C17', desk: [255, 110], meeting: [614, 140], coffee: [1150, 160], sofa: [1000, 465], visit: [255, 110] },
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
  { name: 'Toplantı odası', x: 300, y: 20,  w: 380, h: 250, floor: '#B4BFCE', sign: ['north', 318],      door: [[490, 255], [490, 310]] },
  { name: 'Kalite',         x: 680, y: 20,  w: 260, h: 250, floor: '#CADBCD', sign: ['north', 698],      door: [[815, 255], [815, 310]] },
  { name: 'Mutfak',         x: 940, y: 20,  w: 240, h: 330, floor: 'tile',    sign: ['north', 958],      door: [[960, 310], [920, 310]] },
  { name: '',               x: 20,  y: 270, w: 920, h: 80,  floor: '#DCE0DD', sign: null,                door: null },
  { name: 'Mühendislik',    x: 20,  y: 350, w: 500, h: 350, floor: '#CAD4DF', sign: ['west', 684],       door: [[270, 368], [270, 310]] },
  { name: 'Destek',         x: 520, y: 350, w: 260, h: 350, floor: '#E2D6C0', sign: ['floor', 596, 580], door: [[655, 368], [655, 310]] },
  { name: 'Dinlenme',       x: 780, y: 350, w: 400, h: 350, floor: '#D8CCB9', sign: ['floor', 880, 676], door: [[850, 368], [850, 310]] },
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
    cyl(x, y, 8 * size, 12 * size, '#8A6A4A', { leaves: 15 * size });
  };
  const chair = (x, y) => cyl(x, y, 10, 12, '#465362');
  const desk = (owner, x, y, w, d, screens = 1) => {
    box(x, y, w, d, 26, '#B98E5E');
    const total = screens * 44 + (screens - 1) * 8;
    for (let i = 0; i < screens; i += 1) {
      box(x + (w - total) / 2 + i * 52, y + 9, 44, 4, 24, '#2A3441', { z0: 26, screen: owner });
    }
    box(x + w / 2 - 20, y + d - 22, 40, 12, 1.5, '#E3E7EA', { z0: 26 });   // keyboard
    cyl(x + w - 20, y + d - 18, 4.5, 7, '#F4F1EA', { z0: 26 });            // mug
    box(x + 12, y + d - 30, 22, 18, .8, '#FBFBF8', { z0: 26 });            // paper
  };
  const books = (thing, along, count) => {
    const colors = ['#A23B72', '#2B6CD4', '#C8860B', '#2D8F5B', '#D9622B', '#66727F'];
    thing.decor = [];
    for (let row = 0; row < 2; row += 1) {
      for (let i = 0; i < count; i += 1) {
        thing.decor.push({ face: 'south', a0: 4 + i * (along - 8) / count, a1: 4 + (i + .78) * (along - 8) / count, z0: 8 + row * 26, z1: 26 + row * 26, color: colors[(i + row * 2) % colors.length] });
      }
    }
  };

  for (const [x1, y1, x2, y2, h] of WALLS) {
    const wall = x1 === x2 ? box(x1 - 3, y1, 6, y2 - y1, h, '#EEF0EC') : box(x1, y1 - 3, x2 - x1, 6, h, '#EEF0EC');
    wall.wall = true;
    if (h !== TALL) wall.color = h === CUT ? '#C9D0CD' : '#E4E8E4';
  }
  const north = things[0];
  const west = [things[1], things[2]];
  const glass = GLASS;
  north.decor = [
    { face: 'south', a0: 190, a1: 262, z0: 34, z1: 78, color: glass },                       // Yönetim window
    { face: 'south', a0: 405, a1: 535, z0: 36, z1: 80, color: '#1F2731', lit: 'wallScreen' }, // meeting room screen
    { face: 'south', a0: 684, a1: 790, z0: 38, z1: 76, color: '#FBFBF8' },                   // Kalite board
    { face: 'south', a0: 692, a1: 718, z0: 56, z1: 70, color: '#2D8F5B' },
    { face: 'south', a0: 724, a1: 750, z0: 56, z1: 70, color: '#C8860B' },
    { face: 'south', a0: 756, a1: 782, z0: 56, z1: 70, color: '#D0362F' },
    { face: 'south', a0: 830, a1: 905, z0: 34, z1: 78, color: glass },
    { face: 'south', a0: 980, a1: 1140, z0: 52, z1: 82, color: glass },                      // above the counter
  ];
  west[0].decor = [{ face: 'east', a0: 70, a1: 170, z0: 34, z1: 76, color: '#FBFBF8' }];     // Yönetim whiteboard
  west[1].decor = [
    { face: 'east', a0: 75, a1: 165, z0: 34, z1: 78, color: glass },
    { face: 'east', a0: 215, a1: 305, z0: 34, z1: 78, color: glass },
  ];

  // Yönetim
  books(box(40, 26, 130, 16, 62, '#7A5B3C'), 130, 10);
  plant(272, 48, 1.15);
  chair(120, 62); chair(210, 62);
  desk('lider', 85, 96, 160, 62);
  chair(165, 180);

  // Toplantı odası
  for (const person of Object.values(PEOPLE)) chair(...person.meeting);
  box(390, 105, 200, 70, 24, '#B98E5E', { table: true });
  plant(322, 44); plant(656, 246);

  // Kalite
  desk('testci', 735, 82, 150, 58, 2);
  chair(810, 162);
  const rack = box(898, 60, 30, 150, 70, '#4C5A6A');
  rack.decor = [0, 1, 2, 3].flatMap((i) => [
    { face: 'east', a0: 10 + i * 36, a1: 34 + i * 36, z0: 10, z1: 60, color: '#1F2731' },
    { face: 'east', a0: 26 + i * 36, a1: 30 + i * 36, z0: 50, z1: 54, color: i % 2 ? '#5FD08F' : '#DDA63A' },
  ]);
  plant(916, 244);
  // Reports come out here.
  box(698, 206, 36, 28, 30, '#D9DDE0', { printer: true });

  // Mutfak
  box(948, 26, 224, 36, 30, '#F6F7F5');
  box(962, 32, 38, 24, 20, '#2A3441', { z0: 30 });                        // coffee machine
  for (const x of [1016, 1030, 1044]) cyl(x, 46, 4.5, 7, '#F4F1EA', { z0: 30 });
  box(1066, 34, 44, 22, 1, '#B9C3CB', { z0: 30 });                        // sink
  box(1122, 34, 40, 22, 1.5, '#39434F', { z0: 30 });                      // hob
  box(1138, 80, 36, 54, 66, '#DCE3E8');                                   // fridge
  for (const [x, y] of [[1016, 222], [1108, 222], [1062, 270]]) cyl(x, y, 9, 16, '#465362');
  cyl(1062, 222, 27, 28, '#B98E5E');
  cyl(1054, 216, 4.5, 7, '#F4F1EA', { z0: 28 }); cyl(1072, 228, 4.5, 7, '#F4F1EA', { z0: 28 });
  plant(1120, 326);
  box(1150, 292, 22, 38, 26, '#3D4957');                                  // bin

  // Koridor
  box(880, 276, 22, 22, 34, '#DCE3E8');                                   // water cooler
  cyl(891, 287, 7, 16, '#8FC1E3', { z0: 34 });
  plant(560, 288, .85);

  // Mühendislik
  books(box(40, 358, 100, 16, 46, '#7A5B3C'), 100, 8);
  desk('kidemli', 65, 432, 160, 62, 2);
  desk('gelistirici', 295, 432, 160, 62);
  chair(145, 516); chair(375, 516);
  box(400, 600, 90, 60, 24, '#B98E5E');                                   // spare desk
  box(423, 610, 44, 4, 24, '#2A3441', { z0: 24 });
  plant(492, 380, 1.1); plant(496, 674, 1.1);

  // Destek
  desk('asistan', 575, 430, 150, 58);
  chair(650, 510);
  const cabinets = box(536, 600, 46, 84, 42, '#8D99A6');
  cabinets.decor = [0, 1, 2].map((i) => ({ face: 'east', a0: 4 + i * 27, a1: 26 + i * 27, z0: 6, z1: 36, color: '#AEB8C2' }));
  box(700, 640, 60, 44, 22, '#B98E5E');
  box(706, 646, 48, 32, 14, '#E1E6E9', { z0: 22 });                       // printer
  plant(756, 378);

  // Dinlenme
  box(792, 430, 12, 190, 32, '#4F6F7B'); box(804, 430, 38, 190, 14, '#7FA3B0');   // sofa by the wall
  box(895, 358, 140, 12, 32, '#4F6F7B'); box(895, 370, 140, 36, 14, '#7FA3B0');   // sofa under the window
  box(900, 470, 110, 54, 13, '#B98E5E');                                  // coffee table
  box(916, 482, 30, 20, 2, '#A23B72', { z0: 13 });
  cyl(984, 508, 4.5, 7, '#F4F1EA', { z0: 13 });
  cyl(1090, 610, 18, 15, '#C8860B');                                      // pouf
  box(1146, 440, 24, 130, 20, '#7A5B3C');                                 // TV unit
  box(1160, 452, 4, 106, 46, '#1F2731', { z0: 20 });
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
      visit: "Daim'in odasında" }[spot] ?? '';
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

/** Draw the office on *canvas*; returns update(snapshot), select(id), where(agent), color(id). */
export function createOffice(canvas, onSelect) {
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
  let lastFrame = 0;
  let dirty = true;
  let printedAt = -Infinity;

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
    // Daim has just spoken to you and is waiting for your answer, not on a break.
    return agent.id === 'lider' ? 'desk' : 'coffee';
  }

  function bubbleOf(agent, spot, snapshot) {
    if (snapshot.phase === 'review' && spot === 'meeting') {
      if (snapshot.review.speaker === agent.id) return '…';
      const last = snapshot.review.lines.at(-1);
      return last?.who === agent.id ? shorten(last.text, 46) : '';
    }
    if (agent.id === 'lider' && snapshot.question) return '?';
    if (agent.state === 'error') return 'Hata';
    return agent.state === 'working' && spot === 'desk' ? shorten(agent.activity) : '';
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
    const south = t.screen && lit.has(t.screen) ? '#8FD3FF' : shade(t.color, .84);
    poly([iso(t.x0, t.y1, z1), iso(t.x1, t.y1, z1), iso(t.x1, t.y1, t.z0), iso(t.x0, t.y1, t.z0)], south);
    poly([iso(t.x1, t.y0, z1), iso(t.x1, t.y1, z1), iso(t.x1, t.y1, t.z0), iso(t.x1, t.y0, t.z0)], shade(t.color, .68));
    poly([iso(t.x0, t.y0, z1), iso(t.x1, t.y0, z1), iso(t.x1, t.y1, z1), iso(t.x0, t.y1, z1)], t.color);
    for (const d of t.decor ?? []) {
      const color = d.lit && lit.has(d.lit) ? '#8FD3FF' : d.color === GLASS ? windowColor() : d.color;
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
    if (t.table && latest?.phase === 'meeting') {
      // The plan lies on the table until it is approved.
      poly([iso(470, 128, z1), iso(512, 128, z1), iso(512, 152, z1), iso(470, 152, z1)], '#FBFBF8');
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
      for (const [dx, dy, r, color] of [[0, -8, 1, '#3F7D4F'], [-7, -2, .72, '#4E9360'], [7, -3, .7, '#5FA06C'], [0, -17, .62, '#5FA06C']]) {
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
    ctx.fillStyle = 'rgb(0 0 0 / .16)';
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
    if (!p.seated) drawCyl({ cx: p.x, cy: p.y, r: 6.5, z0: 0, h: 16, color: '#39434F' });      // legs
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
      ctx.fillStyle = room.floor === 'wood' ? '#D6BC95' : room.floor === 'tile' ? '#E9EDEF' : room.floor;
      ctx.fillRect(room.x, room.y, room.w, room.h);
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (room.floor === 'wood') {
        ctx.strokeStyle = '#C2A880';
        for (let y = room.y + 14; y < room.y + room.h; y += 14) { ctx.moveTo(room.x, y); ctx.lineTo(room.x + room.w, y); }
      } else if (room.floor === 'tile') {
        ctx.strokeStyle = '#CBD3D8';
        for (let y = room.y + 24; y < room.y + room.h; y += 24) { ctx.moveTo(room.x, y); ctx.lineTo(room.x + room.w, y); }
        for (let x = room.x + 24; x < room.x + room.w; x += 24) { ctx.moveTo(x, room.y); ctx.lineTo(x, room.y + room.h); }
      }
      ctx.stroke();
    }
    const rug = (x, y, w, h, color, edge) => {
      ctx.fillStyle = color; ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = edge; ctx.lineWidth = 2; ctx.strokeRect(x + 8, y + 8, w - 16, h - 16);
    };
    rug(60, 164, 210, 92, '#B4625B', '#F1DFC6');
    rug(60, 540, 300, 130, '#8E9FB8', '#CAD4DF');
    rug(870, 430, 200, 150, '#7FA9A3', '#EAF1EE');
    ctx.fillStyle = '#C5CBC8'; ctx.fillRect(90, 301, 780, 18);     // corridor runner
    ctx.fillStyle = '#8D7B62'; ctx.fillRect(28, 290, 34, 40);      // doormat
    signs('floor');
    ctx.restore();
  }

  /** Paint room names where *where* says: lying on the floor, or upright on a back wall. */
  function signs(where) {
    ctx.font = '600 24px Bahnschrift, "Segoe UI", sans-serif';
    ctx.fillStyle = 'rgb(29 39 51 / .55)';
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

  function drawSlab() {
    const [x0, y0, x1, y1, drop] = [17, 17, 1183, 703, 18];
    poly([iso(x0, y1), iso(x1, y1), iso(x1, y1, -drop), iso(x0, y1, -drop)], '#AEB6B2');
    poly([iso(x1, y0), iso(x1, y1), iso(x1, y1, -drop), iso(x1, y0, -drop)], '#98A09C');
    poly([iso(x0, y0), iso(x1, y0), iso(x1, y1), iso(x0, y1)], '#DCE0DD');
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
    const byHeight = Object.values(people).filter((p) => p.head).sort((a, b) => a.head[1] - b.head[1]);
    for (const p of byHeight) {
      const [x, y] = onScreen(p.head);
      const above = y - 9 * scale - 13;
      ctx.font = '600 11.5px Bahnschrift, "Segoe UI", sans-serif';
      pill(x, above, p.spec.short, selected === p.id ? p.spec.color : INK, '#FFFFFF');
      if (p.says && (!p.path.length || p.saying)) {
        ctx.font = '11.5px Bahnschrift, "Segoe UI", sans-serif';
        pill(x, above - 21, p.says, '#FFFFFF', INK, INK);
      }
      p.hit = [x, y];
    }
    drawBoard(onScreen);
    drawClock(onScreen);
    if (performance.now() - printedAt < PRINT_MS) {
      const [x, y] = onScreen(iso(716, 220, 60));
      ctx.font = '600 11px Bahnschrift, "Segoe UI", sans-serif';
      pill(x, y, '🖨 Rapor hazır', '#FFFFFF', INK, INK);
    }
  }

  /** The meeting room's screen doubles as the team's board: who is on what. */
  function boardLines() {
    if (!latest) return [];
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
    ctx.fillStyle = 'rgb(31 39 49 / .92)';
    ctx.fill();
    ctx.textAlign = 'left';
    ctx.fillStyle = '#8FD3FF';
    ctx.font = '600 10px Bahnschrift, "Segoe UI", sans-serif';
    ctx.fillText('PANO', cx - width / 2 + 8, cy - height + 10);
    ctx.fillStyle = '#EDF0EE';
    ctx.font = '10.5px Bahnschrift, "Segoe UI", sans-serif';
    lines.forEach((line, i) => ctx.fillText(line, cx - width / 2 + 8, cy - height + 24 + i * 14));
    ctx.textAlign = 'center';
  }

  /** A wall clock in Daim's room, telling the real time. */
  function drawClock(onScreen) {
    const [x, y] = onScreen(iso(282, 22, 92));
    const r = Math.max(7, 13 * scale * 1.4);
    const now = new Date();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.fill();
    ctx.strokeStyle = INK;
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
    scale = Math.min(box.width / VIEW.w, box.height / VIEW.h);
    offset = [(box.width - VIEW.w * scale) / 2, (box.height - VIEW.h * scale) / 2];
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
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
      || performance.now() - printedAt < PRINT_MS;
    // Nothing moves in a resting office, so it is not redrawn.
    if (!dirty && !(alive && !calm.matches)) { lastFrame = time; return; }
    if (alive && !moving && time - lastFrame < 33) return; // the pulse needs no more than 30 frames a second
    lastFrame = time;
    dirty = false;
    draw(time);
  }

  function personAt(event) {
    const box = canvas.getBoundingClientRect();
    const [x, y] = [event.clientX - box.left, event.clientY - box.top];
    return Object.values(people)
      .filter((p) => p.hit && Math.abs(x - p.hit[0]) < 22 && y > p.hit[1] - 32 && y < p.hit[1] + 34 * scale + 8)
      .sort((a, b) => b.hit[1] - a.hit[1])[0];
  }

  canvas.addEventListener('click', (e) => { const p = personAt(e); if (p) onSelect(p.id); });
  canvas.addEventListener('mousemove', (e) => { canvas.style.cursor = personAt(e) ? 'pointer' : ''; });
  new ResizeObserver(() => { dirty = true; }).observe(canvas);
  // People drift from the coffee machine to the sofa as time passes.
  // People drift on as time passes; the clock and the windows follow the hour.
  setInterval(arrange, 5000);
  requestAnimationFrame(frame);

  return {
    update(snapshot) { latest = { ...snapshot, agents: [...snapshot.agents, BOSS] }; seenAt = Date.now(); arrange(); },
    select(id) { selected = id; dirty = true; },
    where(agent) { return latest ? describe(agent, spotOf(agent, latest), latest) : ''; },
    color(id) { return PEOPLE[id]?.color ?? '#66727F'; },
    /** A report came out: the printer prints it. */
    print() { printedAt = performance.now(); dirty = true; },
  };
}
