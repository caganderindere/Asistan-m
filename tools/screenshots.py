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
RESEARCH = "D:\\demo\\magaza\\pazarlama\\arastirma-2026-11-14-online-cicekci-fiyatlari.md"
DECK = "D:\\demo\\magaza\\pazarlama\\kis-kampanyasi-sunum.pptx"
RESEARCH_TEXT = """# Online çiçekçi fiyatları

Özet: İstanbul'da online çiçek siparişinde ortalama sepet 650–900 TL. Rakiplerin üçü aynı gün teslimatı ücretsiz \
veriyor; mağazanın 79 TL teslimat ücreti sepette en çok terk edilen adım.

## Bulgular
| Rakip | Gül buketi (11) | Teslimat | Aynı gün |
|---|---|---|---|
| Çiçekevi | 749 TL | Ücretsiz | 15:00'e kadar |
| BuketAl | 689 TL | 49 TL | 13:00'e kadar |
| Lale&Co | 820 TL | Ücretsiz | 17:00'ye kadar |

## Öneriler
- 600 TL üstü siparişte teslimatı ücretsiz yap.
- Aynı gün teslimat saatini ürün sayfasında göster.

## Kaynaklar
- [Çiçekevi](https://example.com/cicekevi)
- [BuketAl](https://example.com/buketal)
"""
DOCS = [
    {"name": "pazarlama/arastirma-2026-11-14-online-cicekci-fiyatlari", "path": RESEARCH, "kind": "md", "kb": 2.4,
     "time": "2026-11-14T10:52", "project": "magaza"},
    {"name": "pazarlama/kis-kampanyasi-sunum.pptx", "path": DECK, "kind": "pptx", "kb": 1840.2,
     "time": "2026-11-14T10:20", "project": "magaza"},
    {"name": "2026-11-14-kupon-indirimi", "path": "D:\\demo\\magaza\\docs\\ekip\\2026-11-14-kupon-indirimi.md",
     "kind": "md", "kb": 3.1, "time": "2026-11-14T09:41", "project": "magaza"},
    {"name": "pazarlama/hedef-kitle", "path": "D:\\demo\\blog\\pazarlama\\hedef-kitle.md", "kind": "md", "kb": 5.6,
     "time": "2026-11-13T16:05", "project": "blog"},
    {"name": "2026-11-12-push-bildirim", "path": "D:\\demo\\mobil\\docs\\ekip\\2026-11-12-push-bildirim.md",
     "kind": "md", "kb": 4.0, "time": "2026-11-12T18:30", "project": "mobil-uygulama"},
]
# Work handed over, as the job cards under the orb show it: one running, two done with checked documents.
JOB_CARDS = [
    {"type": "job", "project": "blog", "state": "working", "text": "Bağımlılıkları güncelle, testleri çalıştır"},
    {"type": "job", "project": "magaza", "state": "working", "text": "Online çiçekçi fiyatları"},
    {"type": "job", "project": "magaza", "state": "done",
     "docs": [{"name": "pazarlama/arastirma-2026-11-14-online-cicekci-fiyatlari.md", "path": RESEARCH, "ok": True, "kb": 2.4},
              {"name": "pazarlama/kis-kampanyasi-sunum.pptx", "path": DECK, "ok": True, "kb": 1840.2}]},
]
API = {
    "/api/settings": {"live_voice": "Algenib", "voices": {"Algenib": "Kalın, pürüzlü — müdür sesi", "Charon": "Sakin"}},
    "/api/teyit": {"bilgiler": [{"konu": "Mağaza", "bilgi": "En çok satan ürün kırmızı gül buketi. (Google, 2026-11-14)"},
                                {"konu": "Mağaza", "bilgi": "Rakip Çiçeksepeti aynı gün teslimatı 16:00'ya kadar alıyor. (ekip raporu, 2026-11-14)"}]},
    "/api/memory": {"files": {"cagan.md": "", "bugun.md": "2026-11-14\n1. [x] Mağaza testleri\n2. [ ] Sınav çalışması",
                              "gorevler.md": "", "takvim.md": "", "notlar.md": ""}, "diary": []},
    "/api/life": {"week": [], "situation": None},
    "/api/schedule": {"jobs": JOBS["jobs"]},
    "/api/project": {"name": "magaza", "path": PROJECT, "branch": "main", "changed": 2,
                     "commits": [["12 dakika önce", "fix: kupon indirimi toplamdan sonra uygulanıyor"],
                                 ["2 saat önce", "feat: aynı gün teslimat saati ürün sayfasında"]],
                     "readme": "# Mağaza\nÇiçek ve hediye mağazası.", "docs": [{**d, "text": RESEARCH_TEXT} if d["kind"] == "md"
                                                                       else d for d in DOCS[:3]]},
    "/api/belgeler": {"docs": DOCS},
    "/api/belge": {"name": "arastirma-2026-11-14-online-cicekci-fiyatlari.md", "text": RESEARCH_TEXT},
}


SOCKETS = []  # the page's socket, to send it more later, as the server would


def on_ws(ws) -> None:
    if not ws.url.endswith("/ws"):
        return
    SOCKETS.append(ws)
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


def open_page(p, viewport: dict, **options):
    """A page on the made-up server; the bundled Chromium is not installed, Edge is."""
    browser = p.chromium.launch(channel="msedge")
    context = browser.new_context(viewport=viewport, **options)
    page = context.new_page()
    page.route_web_socket("**/ws*", on_ws)
    page.route(f"{BASE}/**", serve)
    page.goto(BASE + "/")
    page.wait_for_timeout(2500)
    return browser, context, page


def show_jobs(page) -> None:
    """The job cards, as the server would send them over the socket."""
    for card in JOB_CARDS:
        SOCKETS[-1].send(json.dumps(card, ensure_ascii=False))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        old.unlink()
    with sync_playwright() as p:
        browser, _, page = open_page(p, {"width": 1440, "height": 900}, device_scale_factor=2)
        show_jobs(page)
        page.wait_for_timeout(400)
        page.screenshot(path=OUT / "asistan.png")
        page.click("#tabOffice")
        page.wait_for_timeout(2000)
        page.screenshot(path=OUT / "ofis.png")
        for pane, name in (("talk", "konusma"), ("schedule", "zamanli"), ("docs", "belgeler"), ("project", "proje"), ("memory", "hafiza")):
            page.click(f'.side-tabs [data-pane="{pane}"]')
            page.wait_for_timeout(600)
            page.locator("aside.side").screenshot(path=OUT / f"{name}.png")
        page.click('.side-tabs [data-pane="docs"]')
        page.click(".doc-open >> nth=0")
        page.wait_for_timeout(500)
        page.locator("#docDialog").screenshot(path=OUT / "belge.png")
        browser.close()
        # The phone app (Tailscale + home screen): the assistant screen at iPhone size.
        browser, _, page = open_page(p, {"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True)
        show_jobs(page)
        page.wait_for_timeout(400)
        page.screenshot(path=OUT / "telefon.png")
        browser.close()
    print("\n".join(str(f) for f in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    sys.exit(main())
