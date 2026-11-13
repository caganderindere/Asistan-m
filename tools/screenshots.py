"""Takes the README screenshots from made-up data: no real talk or memory ends up in them.

  .venv\\Scripts\\python tools\\screenshots.py      writes docs\\img\\*.png
"""

from __future__ import annotations

import json
import mimetypes
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = ROOT / "docs" / "img"
BASE = "http://cuba.local"

PROJECT = "D:\\demo\\magaza"
PROJECTS = {"type": "projects", "current": PROJECT, "projects": [
    {"name": "magaza", "path": PROJECT}, {"name": "blog", "path": "D:\\demo\\blog"},
    {"name": "mobil-uygulama", "path": "D:\\demo\\mobil"}]}


def agent(id_, name, state="idle", activity="", code="", file=""):
    return {"id": id_, "name": name, "department": "Terminal", "duty": "", "model": "", "state": state,
            "activity": activity, "seconds": 42, "task": None, "log": [activity] if activity else [],
            "code": code, "file": file}


CREW = {"type": "terminal_team", "project": PROJECT, "phase": "working", "question": "", "review": None, "tasks": [],
        "agents": [
            agent("lider", "Cuba", "working", "Ajan başlattı: sepet indirimi"),
            agent("kidemli", "Kıdemli Geliştirici", "working", "Edit: cart.py",
                  "def total(self):\n    sub = sum(i.price * i.qty for i in self.items)\n    return sub - self.discount(sub)",
                  "cart.py"),
            agent("gelistirici", "Geliştirici", "working", "Write: coupon.py"),
            agent("testci", "Testçi", "working", "Bash: pytest tests/test_cart.py"),
            agent("asistan", "Asistan"),
        ]}
NAMES = {"lider": "Cuba", "kidemli": "Kıdemli Geliştirici", "gelistirici": "Geliştirici", "testci": "Testçi"}
MEETING = [
    {"who": "kidemli", "text": "İndirimi sepet toplamından sonra uyguladım; kupon ve kampanya artık üst üste binmiyor."},
    {"who": "testci", "text": "Sepet testleri geçiyor. Sıfır tutarlı sepet için bir test daha ekledim."},
    {"who": "gelistirici", "text": "Kupon kodu büyük-küçük harf duyarsız oldu, süresi geçmiş kupon net bir hata veriyor."},
    {"who": "lider", "text": "Güzel. Ödeme sayfasındaki toplamı da aynı fonksiyondan alalım, sonra patrona raporlarım."},
]
CHAT = {"type": "chat", "turns": [
    {"you": "Bugün önce mağaza sitesinin testleri, sonra sınavlarıma çalışacağım.",
     "reply": "Not aldım patron: önce mağaza testleri, sonra sınav çalışması. Bugünün planına yazdım."},
    {"you": "Mağazada kupon indirimi yanlış hesaplanıyor, ekibe ver.",
     "reply": "Ekibe verdim patron. Kıdemli hesabı düzeltiyor, Testçi testleri yazıyor."},
    {"meeting": MEETING},
    {"you": "30 dakika sonra blog projesinde bağımlılıkları güncellesinler.",
     "reply": "Saat 11:00'e kurdum patron. Zamanı gelince ekibe veririm."},
]}
JOBS = {"type": "schedule", "jobs": [
    {"id": 3, "at": "2026-11-13 09:00", "folder": "D:\\demo\\mobil", "project": "mobil-uygulama",
     "text": "Gece derlemesinin loglarına bak, hata varsa raporla.", "status": "soruluyor", "created": "", "ran": ""},
    {"id": 4, "at": "2026-11-13 11:00", "folder": "D:\\demo\\blog", "project": "blog",
     "text": "Bağımlılıkları güncelle, testleri çalıştır, kırılan olursa düzeltmeden önce bana sor.",
     "status": "bekliyor", "created": "", "ran": ""},
    {"id": 5, "at": "2026-11-14 09:00", "folder": PROJECT, "project": "magaza",
     "text": "Haftalık güvenlik taramasını çalıştır ve özetle.", "status": "bekliyor", "created": "", "ran": ""},
    {"id": 2, "at": "2026-11-13 08:30", "folder": PROJECT, "project": "magaza",
     "text": "Lint uyarılarını temizle.", "status": "yapildi", "created": "", "ran": "2026-11-13 08:30"},
]}
OUTPUTS = {"type": "outputs", "items": [
    {"time": "10:41", "project": "magaza", "summary": "Kupon indirimi düzeltildi, 12 sepet testi geçiyor.",
     "report": "cart.py: indirim toplamdan sonra uygulanıyor…", "done": True},
]}
API = {
    "/api/settings": {"live_voice": "Algenib", "voices": {"Algenib": "Kalın, pürüzlü — müdür sesi", "Charon": "Sakin"}},
    "/api/memory": {"files": {"cagan.md": "", "bugun.md": "2026-11-13\n1. [ ] Mağaza testleri\n2. [ ] Sınav çalışması",
                              "gorevler.md": "", "takvim.md": "", "notlar.md": ""}, "diary": []},
    "/api/life": {"week": [], "situation": None},
    "/api/schedule": {"jobs": JOBS["jobs"]},
    "/api/project": {"name": "magaza", "path": PROJECT},
}


def on_ws(ws) -> None:
    if not ws.url.endswith("/ws"):
        return
    for message in ({"type": "status", "state": "ok", "live": True}, PROJECTS,
                    {"type": "roster", "members": []}, CREW, CHAT, JOBS, OUTPUTS,
                    {"type": "usage", "claude": {"input": 182000, "output": 41000, "cache": 900000},
                     "gemini": {"input": 64000, "output": 9000}},
                    {"type": "terminals", "busy": [PROJECT], "open": [PROJECT]}):
        ws.send(json.dumps(message, ensure_ascii=False))


def serve(route) -> None:
    path = route.request.url.removeprefix(BASE).split("?")[0]
    if path in API:
        return route.fulfill(json=API[path])
    file = WEB / "index.html" if path == "/" else WEB / path.removeprefix("/static/").lstrip("/")
    if file.is_file():
        return route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "text/plain")
    return route.fulfill(status=404, body="")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.route_web_socket("**/ws*", on_ws)
        page.route(f"{BASE}/**", serve)
        page.goto(BASE + "/")
        page.wait_for_timeout(2500)
        page.screenshot(path=OUT / "ofis.png")
        for pane in ("talk", "schedule"):
            page.click(f'.side-tabs [data-pane="{pane}"]')
            page.wait_for_timeout(600)
            page.locator("aside.side").screenshot(path=OUT / f"{ {'talk': 'konusma', 'schedule': 'zamanli'}[pane]}.png")
        browser.close()
    print("\n".join(str(f) for f in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    sys.exit(main())
