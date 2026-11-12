// The embedded PowerShell, with Claude Code running in it, drawn by xterm.js.

export function createTerminalView(container) {
  const term = new window.Terminal({
    cursorBlink: true,
    fontFamily: 'Cascadia Mono, Consolas, monospace',
    fontSize: 14,
    scrollback: 5000,
    theme: { background: '#0c0c0c' },
  });
  const fit = new window.FitAddon.FitAddon();
  term.loadAddon(fit);
  let ws = null;
  let opened = false;

  const send = (message) => {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  };
  const resize = () => {
    if (container.hidden || !opened) return;
    fit.fit();
    send({ type: 'resize', cols: term.cols, rows: term.rows });
  };

  function connect() {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/terminal`);
    let first = true;
    ws.onmessage = (e) => {
      // The first message replays what the terminal showed before this page opened.
      if (first) { first = false; term.reset(); }
      term.write(e.data);
    };
    ws.onopen = resize;
    ws.onclose = () => setTimeout(connect, 2000);
  }

  term.onData((data) => send({ type: 'input', data }));
  new ResizeObserver(resize).observe(container);

  return {
    show() {
      if (!opened) {
        term.open(container);
        opened = true;
        connect();
      }
      requestAnimationFrame(() => { resize(); term.focus(); });
    },
    /** Type *text* into Claude's prompt and submit it, as if typed by hand. */
    say(text) {
      send({ type: 'input', data: text });
      // Text and Enter in one write would land as a paste with a line break in it.
      setTimeout(() => send({ type: 'input', data: '\r' }), 150);
    },
    key(sequence) {
      send({ type: 'input', data: sequence });
    },
  };
}
