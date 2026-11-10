// The office seen from above. Where each person stands is their real state:
// at the desk while working, around the table while a plan awaits approval,
// by the coffee machine just after finishing, on the sofa when idle for long.

const NS = 'http://www.w3.org/2000/svg';
const COFFEE_BREAK_S = 90;

const PEOPLE = {
  lider:       { short: 'Lider',       color: '#C8860B', hair: '#2B211B', desk: [165, 186], meeting: [352, 140], coffee: [1000, 106], sofa: [1114, 478] },
  kidemli:     { short: 'Kıdemli',     color: '#A23B72', hair: '#4A3426', desk: [145, 522], meeting: [440, 80],  coffee: [1052, 106], sofa: [860, 624] },
  gelistirici: { short: 'Geliştirici', color: '#2B6CD4', hair: '#1F1B18', desk: [375, 522], meeting: [540, 80],  coffee: [1104, 106], sofa: [922, 624] },
  testci:      { short: 'Testçi',      color: '#2D8F5B', hair: '#6B4A2E', desk: [810, 168], meeting: [440, 200], coffee: [1016, 222], sofa: [984, 624] },
  asistan:     { short: 'Asistan',     color: '#D9622B', hair: '#3A2A20', desk: [650, 518], meeting: [540, 200], coffee: [1108, 222], sofa: [1114, 552] },
};

const ROOMS = [
  { name: 'Yönetim',        x: 20,  y: 20,  w: 280, h: 250, fill: 'url(#wood)',  label: [34, 260] },
  { name: 'Toplantı odası', x: 300, y: 20,  w: 380, h: 250, fill: '#B4BFCE',     label: [314, 258] },
  { name: 'Kalite',         x: 680, y: 20,  w: 260, h: 250, fill: '#CADBCD',     label: [694, 258] },
  { name: 'Mutfak',         x: 940, y: 20,  w: 240, h: 330, fill: 'url(#tile)',  label: [954, 338] },
  { name: '',               x: 20,  y: 270, w: 920, h: 80,  fill: '#DCE0DD',     label: null },
  { name: 'Mühendislik',    x: 20,  y: 350, w: 500, h: 350, fill: '#CAD4DF',     label: [34, 688] },
  { name: 'Destek',         x: 520, y: 350, w: 260, h: 350, fill: '#E2D6C0',     label: [534, 688] },
  { name: 'Dinlenme',       x: 780, y: 350, w: 400, h: 350, fill: '#D8CCB9',     label: [794, 688] },
];

// [x1, y1, x2, y2]; the gaps between them are the doors.
const WALLS = [
  [20, 270, 140, 270], [190, 270, 460, 270], [520, 270, 790, 270], [840, 270, 940, 270],
  [20, 350, 240, 350], [300, 350, 630, 350], [680, 350, 820, 350], [880, 350, 1040, 350], [1100, 350, 1180, 350],
  [300, 20, 300, 270], [680, 20, 680, 270], [940, 20, 940, 285], [940, 335, 940, 350],
  [520, 350, 520, 700], [780, 350, 780, 700],
  // Outer wall, open at the entrance on the left of the corridor.
  [20, 20, 1180, 20], [1180, 20, 1180, 700], [1180, 700, 20, 700], [20, 700, 20, 335], [20, 285, 20, 20],
];

function el(tag, attrs = {}, parent = null, text = '') {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text) node.textContent = text;
  parent?.append(node);
  return node;
}

const rect = (p, x, y, w, h, fill, extra = {}) => el('rect', { x, y, width: w, height: h, fill, ...extra }, p);
const circle = (p, cx, cy, r, fill, extra = {}) => el('circle', { cx, cy, r, fill, ...extra }, p);

function plant(p, x, y, r = 13) {
  circle(p, x, y, r, '#8A6A4A');
  circle(p, x, y, r - 3, '#3F7D4F');
  for (const [dx, dy] of [[-4, -3], [4, -2], [0, 5]]) circle(p, x + dx, y + dy, r / 3, '#5FA06C');
}

function chair(p, x, y) {
  circle(p, x, y, 14, '#3D4957');
  circle(p, x, y, 10, '#4C5A6A');
}

/** A desk with its screen; the screen lights up while its owner works there. */
function desk(p, id, x, y, w, h, screens = 1) {
  rect(p, x, y, w, h, '#B98E5E', { rx: 4, stroke: '#8E6A41', 'stroke-width': 2 });
  const sw = 44;
  const total = screens * sw + (screens - 1) * 6;
  for (let i = 0; i < screens; i += 1) {
    rect(p, x + (w - total) / 2 + i * (sw + 6), y + 7, sw, 9, '#1F2731', { rx: 2, class: 'screen', 'data-owner': id });
  }
  rect(p, x + w / 2 - 20, y + h - 20, 40, 11, '#DDE2E6', { rx: 2 });        // keyboard
  circle(p, x + w - 20, y + h - 18, 6, '#F4F1EA', { stroke: '#8E6A41' });   // mug
  rect(p, x + 12, y + h - 26, 22, 16, '#F6F7F5', { transform: `rotate(-8 ${x + 23} ${y + h - 18})` }); // paper
}

function bookshelf(p, x, y, w) {
  rect(p, x, y, w, 16, '#7A5B3C', { rx: 2 });
  const colors = ['#A23B72', '#2B6CD4', '#C8860B', '#2D8F5B', '#D9622B', '#66727F'];
  for (let i = 0; i * 9 + 6 < w - 6; i += 1) rect(p, x + 4 + i * 9, y + 3, 6, 10, colors[i % colors.length]);
}

function sofa(p, x, y, w, h, seats, vertical = false) {
  rect(p, x, y, w, h, '#5E7F8C', { rx: 9 });
  for (let i = 0; i < seats; i += 1) {
    if (vertical) rect(p, x + 5, y + 6 + i * ((h - 12) / seats), w - 16, (h - 12) / seats - 5, '#7FA3B0', { rx: 6 });
    else rect(p, x + 6 + i * ((w - 12) / seats), y + 5, (w - 12) / seats - 5, h - 16, '#7FA3B0', { rx: 6 });
  }
}

function furnish(p) {
  // Yönetim
  rect(p, 60, 150, 210, 100, '#9C3F3A', { rx: 6, opacity: .55 });
  rect(p, 68, 158, 194, 84, 'none', { rx: 4, stroke: '#F1DFC6', 'stroke-width': 1.5, opacity: .7 });
  bookshelf(p, 40, 28, 130);
  rect(p, 23, 90, 5, 90, '#F6F7F5', { stroke: '#8D99A6' });
  plant(p, 270, 50, 15);
  chair(p, 165, 186);
  desk(p, 'lider', 85, 96, 160, 62);
  chair(p, 120, 60); chair(p, 210, 60);

  // Toplantı odası
  rect(p, 425, 23, 130, 7, '#1F2731', { rx: 2, id: 'wallScreen' });
  for (const person of Object.values(PEOPLE)) chair(p, ...person.meeting);
  chair(p, 628, 140);
  el('ellipse', { cx: 490, cy: 140, rx: 112, ry: 40, fill: '#B98E5E', stroke: '#8E6A41', 'stroke-width': 2 }, p);
  rect(p, 468, 130, 44, 20, '#F6F7F5', { rx: 2, id: 'planSheet', transform: 'rotate(4 490 140)' });
  plant(p, 322, 42); plant(p, 656, 244);

  // Kalite
  rect(p, 700, 23, 110, 6, '#F6F7F5', { stroke: '#8D99A6' });
  for (const [i, c] of ['#2D8F5B', '#C8860B', '#D0362F'].entries()) rect(p, 708 + i * 34, 31, 26, 14, c, { rx: 2, opacity: .8 });
  chair(p, 810, 168);
  desk(p, 'testci', 735, 82, 150, 58, 2);
  rect(p, 898, 60, 30, 150, '#4C5A6A', { rx: 3 });
  for (let i = 0; i < 5; i += 1) {
    rect(p, 902, 66 + i * 29, 22, 20, '#1F2731', { rx: 2 });
    circle(p, 919, 81 + i * 29, 2, i % 2 ? '#2D8F5B' : '#C8860B');
  }
  plant(p, 916, 244);

  // Mutfak
  rect(p, 948, 28, 224, 36, '#F6F7F5', { rx: 3, stroke: '#8D99A6' });
  rect(p, 1066, 34, 44, 24, '#C3CCD3', { rx: 5, stroke: '#8D99A6' });   // sink
  circle(p, 1088, 46, 3, '#66727F');
  rect(p, 962, 32, 40, 28, '#2A3441', { rx: 4 });                        // coffee machine
  circle(p, 974, 46, 6, '#11161C'); circle(p, 992, 40, 2.5, '#D0362F', { id: 'brewLight' });
  for (const x of [1016, 1030, 1044]) circle(p, x, 46, 5, '#F4F1EA', { stroke: '#8D99A6' });
  rect(p, 1122, 32, 44, 28, '#E1E6E9', { rx: 3, stroke: '#8D99A6' });    // hob
  circle(p, 1134, 46, 6, 'none', { stroke: '#66727F' }); circle(p, 1154, 46, 6, 'none', { stroke: '#66727F' });
  rect(p, 1138, 80, 36, 56, '#DCE3E8', { rx: 4, stroke: '#8D99A6' });    // fridge
  rect(p, 1141, 106, 3, 22, '#8D99A6');
  for (const x of [1016, 1108]) circle(p, x, 222, 11, '#4C5A6A');        // stools
  circle(p, 1062, 262, 11, '#4C5A6A');
  circle(p, 1062, 222, 32, '#B98E5E', { stroke: '#8E6A41', 'stroke-width': 2 });
  circle(p, 1054, 216, 5, '#F4F1EA', { stroke: '#8D99A6' }); circle(p, 1072, 228, 5, '#F4F1EA', { stroke: '#8D99A6' });
  plant(p, 1118, 326, 12);
  rect(p, 1150, 290, 22, 40, '#3D4957', { rx: 3 });                      // bin

  // Koridor
  rect(p, 26, 290, 34, 40, '#8D7B62', { rx: 3 });                        // doormat
  rect(p, 90, 302, 800, 16, '#C5CBC8', { rx: 8 });
  rect(p, 880, 276, 22, 22, '#DCE3E8', { rx: 4, stroke: '#8D99A6' });    // water cooler
  circle(p, 891, 287, 7, '#8FC1E3');
  plant(p, 560, 288, 10);

  // Mühendislik
  rect(p, 60, 560, 420, 110, '#5F7391', { rx: 8, opacity: .35 });
  chair(p, 145, 522); chair(p, 375, 522);
  desk(p, 'kidemli', 65, 432, 160, 62, 2);
  desk(p, 'gelistirici', 295, 432, 160, 62);
  rect(p, 150, 692, 220, 6, '#F6F7F5', { stroke: '#8D99A6' });           // whiteboard
  bookshelf(p, 40, 358, 100);
  rect(p, 400, 600, 90, 60, '#B98E5E', { rx: 4, stroke: '#8E6A41', 'stroke-width': 2 });
  rect(p, 414, 612, 26, 34, '#F6F7F5'); rect(p, 448, 616, 30, 22, '#1F2731', { rx: 2 });
  plant(p, 492, 378, 14); plant(p, 496, 674, 14);

  // Destek
  chair(p, 650, 518);
  desk(p, 'asistan', 575, 430, 150, 58);
  rect(p, 536, 600, 46, 84, '#8D99A6', { rx: 3 });                       // filing cabinets
  rect(p, 541, 606, 36, 22, '#AEB8C2'); rect(p, 541, 632, 36, 22, '#AEB8C2'); rect(p, 541, 658, 36, 22, '#AEB8C2');
  rect(p, 700, 640, 60, 44, '#E1E6E9', { rx: 4, stroke: '#8D99A6' });    // printer
  rect(p, 712, 648, 36, 14, '#F6F7F5');
  plant(p, 756, 376, 12);

  // Dinlenme
  rect(p, 830, 430, 240, 150, '#6F9C97', { rx: 10, opacity: .6 });
  rect(p, 842, 442, 216, 126, 'none', { rx: 6, stroke: '#EAF1EE', 'stroke-width': 1.5, opacity: .7 });
  sofa(p, 822, 600, 204, 52, 3);
  sofa(p, 1092, 432, 52, 164, 2, true);
  rect(p, 900, 480, 110, 54, '#B98E5E', { rx: 6, stroke: '#8E6A41', 'stroke-width': 2 }); // coffee table
  rect(p, 915, 492, 30, 20, '#A23B72', { transform: 'rotate(-10 930 502)' });
  circle(p, 984, 510, 6, '#F4F1EA', { stroke: '#8D99A6' });
  circle(p, 835, 400, 20, '#C8860B', { opacity: .85 }); circle(p, 835, 400, 12, '#DDA63A'); // pouf
  rect(p, 900, 353, 130, 6, '#1F2731', { rx: 2 });                       // TV
  bookshelf(p, 1060, 680, 100);
  plant(p, 1154, 376, 15); plant(p, 1040, 676, 13);
}

function person(layer, id, spec, onSelect) {
  const g = el('g', { class: 'agent', 'data-id': id, tabindex: 0, role: 'button' }, layer);
  circle(g, 0, 0, 22, spec.color, { class: 'pulse' });
  el('ellipse', { cx: 0, cy: 2, rx: 16, ry: 10.5, fill: spec.color, stroke: '#1D2733', 'stroke-width': 1.5 }, g);
  circle(g, 0, 0, 7.5, spec.hair, { stroke: '#1D2733', 'stroke-width': 1 });
  const tagWidth = spec.short.length * 7 + 14;
  rect(g, -tagWidth / 2, 17, tagWidth, 16, '#1D2733', { rx: 8, class: 'tag' });
  el('text', { x: 0, y: 28.5, class: 'tag-text' }, g, spec.short);
  const bubble = el('g', { class: 'bubble' }, g);
  const bubbleBox = rect(bubble, 0, -46, 10, 20, '#FFFFFF', { rx: 6, stroke: '#1D2733', 'stroke-width': 1.2 });
  const bubbleText = el('text', { x: 0, y: -32, class: 'bubble-text' }, bubble);
  g.addEventListener('click', () => onSelect(id));
  g.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(id); } });
  return { g, bubble, bubbleBox, bubbleText };
}

/** A tool working on a long path reads better above a desk as "Edit: app.py". */
function shorten(text, max = 30) {
  const path = text.match(/^(\w+): \S*[\\/]([^\\/\s]+)$/);
  const brief = path ? `${path[1]}: ${path[2]}` : text;
  return brief.length > max ? `${brief.slice(0, max - 1)}…` : brief;
}

/** Draw the office into *svg*; returns update(snapshot) and select(id). */
export function createOffice(svg, onSelect) {
  svg.setAttribute('viewBox', '0 0 1200 720');
  const defs = el('defs', {}, svg);
  const wood = el('pattern', { id: 'wood', width: 46, height: 14, patternUnits: 'userSpaceOnUse' }, defs);
  rect(wood, 0, 0, 46, 14, '#D6BC95');
  el('path', { d: 'M0 0H46M0 7H46M12 0V7M34 7V14', stroke: '#BFA57E', 'stroke-width': 1, fill: 'none' }, wood);
  const tile = el('pattern', { id: 'tile', width: 24, height: 24, patternUnits: 'userSpaceOnUse' }, defs);
  rect(tile, 0, 0, 24, 24, '#E9EDEF');
  el('path', { d: 'M0 0H24M0 0V24', stroke: '#CBD3D8', 'stroke-width': 1.5, fill: 'none' }, tile);

  const floor = el('g', {}, svg);
  for (const room of ROOMS) rect(floor, room.x, room.y, room.w, room.h, room.fill);
  furnish(el('g', {}, svg));
  const walls = el('g', { stroke: '#2A3441', 'stroke-width': 7, 'stroke-linecap': 'square' }, svg);
  for (const [x1, y1, x2, y2] of WALLS) el('line', { x1, y1, x2, y2 }, walls);
  const labels = el('g', { class: 'room-labels' }, svg);
  for (const room of ROOMS) if (room.label) el('text', { x: room.label[0], y: room.label[1] }, labels, room.name);

  const layer = el('g', {}, svg);
  const people = Object.fromEntries(
    Object.entries(PEOPLE).map(([id, spec]) => [id, person(layer, id, spec, onSelect)]),
  );
  let latest = null;
  let seenAt = 0;

  function spotOf(agent, snapshot) {
    if (snapshot.phase === 'meeting') return 'meeting';
    if (agent.state !== 'idle') return 'desk';
    if (agent.id === 'lider' && snapshot.question) return 'desk';
    const idle = agent.seconds + (Date.now() - seenAt) / 1000;
    if (idle >= COFFEE_BREAK_S) return 'sofa';
    // The lead has just spoken to you and is waiting for your answer, not on a break.
    return agent.id === 'lider' ? 'desk' : 'coffee';
  }

  function render() {
    if (!latest) return;
    const atDesk = new Set();
    for (const agent of latest.agents) {
      const view = people[agent.id];
      if (!view) continue;
      const spot = spotOf(agent, latest);
      const [x, y] = PEOPLE[agent.id][spot];
      view.g.style.transform = `translate(${x}px, ${y}px)`;
      view.g.dataset.state = agent.state;
      view.g.dataset.spot = spot;
      if (spot === 'desk' && agent.state === 'working') atDesk.add(agent.id);

      let says = '';
      if (agent.id === 'lider' && latest.question) says = '?';
      else if (agent.state === 'error') says = 'Hata';
      else if (agent.state === 'working' && spot === 'desk') says = shorten(agent.activity);
      view.bubble.style.display = says ? '' : 'none';
      if (says) {
        const width = Math.max(26, says.length * 6.6 + 16);
        view.bubbleBox.setAttribute('x', -width / 2);
        view.bubbleBox.setAttribute('width', width);
        view.bubbleText.textContent = says;
      }
      view.g.setAttribute('aria-label', `${agent.name}: ${describe(agent, spot, latest)}`);
    }
    for (const screen of svg.querySelectorAll('.screen')) {
      screen.classList.toggle('on', atDesk.has(screen.dataset.owner));
    }
    const meeting = latest.phase === 'meeting';
    svg.querySelector('#wallScreen').classList.toggle('on', meeting);
    svg.querySelector('#planSheet').style.display = meeting ? '' : 'none';
  }

  // People drift from the coffee machine to the sofa as time passes.
  setInterval(render, 5000);

  return {
    update(snapshot) { latest = snapshot; seenAt = Date.now(); render(); },
    select(id) {
      for (const [key, view] of Object.entries(people)) view.g.classList.toggle('selected', key === id);
    },
    where(agent) { return latest ? describe(agent, spotOf(agent, latest), latest) : ''; },
    color(id) { return PEOPLE[id]?.color ?? '#66727F'; },
  };
}

function describe(agent, spot, snapshot) {
  if (spot === 'meeting') return 'Toplantıda, plan onayını bekliyor';
  if (agent.state === 'error') return 'Masasında, son işi hata verdi';
  if (agent.state === 'working') return agent.id === 'lider' ? 'Masasında, seninle ilgileniyor' : 'Masasında çalışıyor';
  if (agent.id === 'lider' && snapshot.question) return 'Odasında, kararını bekliyor';
  if (spot === 'desk') return 'Odasında, seni dinliyor';
  return spot === 'coffee' ? 'Mutfakta kahve molasında' : 'Dinlenme alanında, boşta';
}
