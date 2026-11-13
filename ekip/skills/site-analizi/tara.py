"""Crawl a site and report its technical, SEO and AI-search (GEO) facts as JSON, standard library only.

    python tara.py https://ornek.com [--sayfa 12] [--hiz] [--cikti rapor.json]

Measures what a marketer would check by hand on every page: title, description, headings, images
without alt text, social tags, structured data, analytics, speed; and for the whole site robots.txt,
which AI crawlers may read it, sitemap and llms.txt. `sorunlar` lists what it found wrong, per page.
The agent reads this instead of fetching each page itself, then judges content and tone on top.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

AGENT = "Mozilla/5.0 (compatible; CubaSiteAnalizi/1.0)"
AI_BOTS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "anthropic-ai",
           "PerplexityBot", "Google-Extended", "CCBot", "Bytespider", "Applebot-Extended")
TRACKERS = {"Google Analytics": r"gtag\(|google-analytics\.com|G-[A-Z0-9]{6,}", "Google Tag Manager": r"googletagmanager\.com/gtm",
            "Meta Pixel": r"connect\.facebook\.net|fbq\(", "Hotjar": r"hotjar", "Yandex Metrica": r"mc\.yandex",
            "Microsoft Clarity": r"clarity\.ms", "TikTok Pixel": r"analytics\.tiktok\.com"}
SKIP = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|pdf|zip|mp4|mp3|css|js|ico|xml|txt|woff2?)(?:\?|$)", re.I)


def fetch(url: str, timeout: float = 20) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept-Language": "tr,en;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(3_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return {"url": response.geturl(), "durum": response.status, "tur": response.headers.get("Content-Type", ""),
                    "sure_ms": int((time.monotonic() - started) * 1000), "boyut_kb": len(raw) // 1024,
                    "metin": raw.decode(charset, errors="replace")}
    except urllib.error.HTTPError as e:
        return {"url": url, "durum": e.code, "tur": "", "sure_ms": int((time.monotonic() - started) * 1000), "metin": ""}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "durum": 0, "hata": str(e)[:200], "metin": ""}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self.headings: dict[str, list[str]] = {"h1": [], "h2": [], "h3": []}
        self.images = self.images_no_alt = self.forms = 0
        self.title = self.lang = self.canonical = ""
        self.jsonld: list[str] = []
        self._in: str = ""
        self._buf: list[str] = []
        self.words = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link" and "canonical" in a.get("rel", "").lower():
            self.canonical = a.get("href", "")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            self.images += 1
            if not a.get("alt", "").strip():
                self.images_no_alt += 1
        elif tag == "form":
            self.forms += 1
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in, self._buf = "jsonld", []
        elif tag in ("title", "h1", "h2", "h3"):
            self._in, self._buf = tag, []
        elif tag in ("script", "style", "noscript"):
            self._in = "skip"

    def handle_endtag(self, tag: str) -> None:
        text = " ".join("".join(self._buf).split())
        if self._in == "title" and tag == "title":
            self.title = text
        elif self._in in self.headings and tag == self._in:
            self.headings[tag].append(text[:120])
        elif self._in == "jsonld" and tag == "script":
            self.jsonld.append("".join(self._buf))
        elif self._in == "skip" and tag in ("script", "style", "noscript"):
            pass
        else:
            return
        self._in, self._buf = "", []

    def handle_data(self, data: str) -> None:
        if self._in and self._in != "skip":
            self._buf.append(data)
        if self._in != "skip" and self._in != "jsonld":
            self.words += len(data.split())


def schema_types(blocks: list[str]) -> list[str]:
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            kind = node.get("@type")
            found.extend(kind if isinstance(kind, list) else [kind] if kind else [])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for block in blocks:
        try:
            walk(json.loads(block))
        except ValueError:
            found.append("GEÇERSİZ-JSON-LD")
    return sorted({str(t) for t in found})


def analyse(page: dict) -> dict:
    parser = Page()
    parser.feed(page["metin"])
    meta = parser.meta
    report = {
        "url": page["url"], "durum": page["durum"], "sure_ms": page.get("sure_ms"), "boyut_kb": page.get("boyut_kb"),
        "baslik": parser.title, "baslik_uzunluk": len(parser.title),
        "aciklama": meta.get("description", ""), "aciklama_uzunluk": len(meta.get("description", "")),
        "h1": parser.headings["h1"], "h2": parser.headings["h2"][:15], "kelime": parser.words,
        "dil": parser.lang, "canonical": parser.canonical, "robots_meta": meta.get("robots", ""),
        "viewport": bool(meta.get("viewport")), "gorsel": parser.images, "altsiz_gorsel": parser.images_no_alt,
        "form": parser.forms, "og": {k: v for k, v in meta.items() if k.startswith("og:")},
        "twitter_kart": meta.get("twitter:card", ""), "yapisal_veri": schema_types(parser.jsonld),
        "izleme": [name for name, pattern in TRACKERS.items() if re.search(pattern, page["metin"])],
    }
    problems = []
    if page["durum"] != 200:
        problems.append(f"HTTP {page['durum']}")
    if not parser.title:
        problems.append("başlık (title) yok")
    elif not 15 <= len(parser.title) <= 60:
        problems.append(f"başlık {len(parser.title)} karakter (15-60 olmalı)")
    if not meta.get("description"):
        problems.append("meta açıklama yok")
    elif not 70 <= len(meta["description"]) <= 160:
        problems.append(f"meta açıklama {len(meta['description'])} karakter (70-160 olmalı)")
    if len(parser.headings["h1"]) != 1:
        problems.append(f"{len(parser.headings['h1'])} tane H1 var (1 olmalı)")
    if parser.images_no_alt:
        problems.append(f"{parser.images_no_alt}/{parser.images} görselde alt metni yok")
    if not meta.get("viewport"):
        problems.append("mobil viewport etiketi yok")
    if not meta.get("og:image"):
        problems.append("og:image yok (paylaşımda görsel çıkmaz)")
    if not parser.jsonld:
        problems.append("yapısal veri (JSON-LD) yok")
    if "noindex" in meta.get("robots", "").lower():
        problems.append("sayfa noindex: Google'da çıkmaz")
    if page.get("sure_ms") and page["sure_ms"] > 2000:
        problems.append(f"sunucu yanıtı yavaş ({page['sure_ms']} ms)")
    if parser.words < 250:
        problems.append(f"içerik ince ({parser.words} kelime)")
    report["sorunlar"] = problems
    report["_linkler"] = parser.links
    return report


def robots_rules(text: str) -> dict:
    """For each AI crawler: is the whole site closed to it?"""
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    rules: list[str] = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        if key.lower() == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key.lower() in ("disallow", "allow"):
            rules.append(f"{key.lower()}:{value}")
    if agents:
        groups.append((agents, rules))

    def closed(bot: str) -> bool:
        own = [r for a, r in groups if bot.lower() in a] or [r for a, r in groups if "*" in a]
        return any("disallow:/" in r and "allow:/" not in r for r in own)

    return {bot: "kapalı" if closed(bot) else "açık" for bot in AI_BOTS}


def speed(url: str) -> dict:
    api = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?" + urllib.parse.urlencode(
        {"url": url, "strategy": "mobile", "category": "performance"})
    result = fetch(api, timeout=90)
    try:
        data = json.loads(result["metin"])
        audits = data["lighthouseResult"]["audits"]
        return {"mobil_performans": round(data["lighthouseResult"]["categories"]["performance"]["score"] * 100),
                **{k: audits[k]["displayValue"] for k in ("largest-contentful-paint", "cumulative-layout-shift",
                                                           "total-blocking-time", "first-contentful-paint") if k in audits}}
    except (ValueError, KeyError, TypeError):
        return {"hata": f"PageSpeed ölçülemedi (HTTP {result['durum']})"}


def crawl(start: str, limit: int, with_speed: bool) -> dict:
    if "://" not in start:
        start = "https://" + start
    first = fetch(start)
    if not first["metin"]:
        return {"hata": f"Site açılmadı: {first.get('hata') or 'HTTP ' + str(first['durum'])}", "url": start}
    base = urllib.parse.urlsplit(first["url"])
    origin = f"{base.scheme}://{base.netloc}"
    site: dict = {"site": origin, "https": base.scheme == "https", "yonlendirme": first["url"] if first["url"] != start else ""}

    robots = fetch(origin + "/robots.txt")
    robots_text = robots["metin"] if robots["durum"] == 200 else ""
    site["robots_txt"] = bool(robots_text)
    site["yapay_zeka_botlari"] = robots_rules(robots_text)
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_text) or [origin + "/sitemap.xml"]
    sitemap = fetch(maps[0])
    site["sitemap"] = {"url": maps[0], "var": sitemap["durum"] == 200 and "<" in sitemap["metin"],
                       "adres_sayisi": sitemap["metin"].count("<loc>")}
    llms = fetch(origin + "/llms.txt")
    site["llms_txt"] = llms["durum"] == 200 and not llms["metin"].lstrip().startswith("<")

    pages, queue, seen = [], [first["url"]], {first["url"].rstrip("/")}
    cached = {first["url"]: first}
    while queue and len(pages) < limit:
        url = queue.pop(0)
        page = cached.pop(url, None) or fetch(url)
        if "html" not in page.get("tur", "html") and page["durum"] == 200:
            continue
        report = analyse(page)
        for href in report.pop("_linkler"):
            link = urllib.parse.urljoin(page["url"], href).split("#")[0]
            parts = urllib.parse.urlsplit(link)
            if parts.netloc == base.netloc and parts.scheme in ("http", "https") and not SKIP.search(parts.path):
                key = link.rstrip("/")
                if key not in seen:
                    seen.add(key)
                    queue.append(link)
        pages.append(report)
    site["sayfalar"] = pages
    site["bulunan_ic_link"] = len(seen)
    titles = [p["baslik"] for p in pages if p["baslik"]]
    site["tekrarlanan_basliklar"] = sorted({t for t in titles if titles.count(t) > 1})
    issues = []
    if not site["https"]:
        issues.append("site HTTPS değil")
    if not site["robots_txt"]:
        issues.append("robots.txt yok")
    if not site["sitemap"]["var"]:
        issues.append("sitemap.xml bulunamadı")
    if not site["llms_txt"]:
        issues.append("llms.txt yok (yapay zekâ aramalarına site özeti verilmiyor)")
    blocked = [b for b, s in site["yapay_zeka_botlari"].items() if s == "kapalı"]
    if blocked:
        issues.append(f"robots.txt şu yapay zekâ botlarına kapalı: {', '.join(blocked)}")
    if site["tekrarlanan_basliklar"]:
        issues.append(f"{len(site['tekrarlanan_basliklar'])} başlık birden çok sayfada aynı")
    if not any(p["izleme"] for p in pages):
        issues.append("analitik/izleme kodu görülmedi")
    site["site_sorunlari"] = issues
    if with_speed:
        site["hiz"] = speed(first["url"])
    return site


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--sayfa", type=int, default=12, help="en çok kaç sayfa taransın")
    parser.add_argument("--hiz", action="store_true", help="Google PageSpeed ile mobil hızı da ölç")
    parser.add_argument("--cikti", help="JSON'u bu dosyaya da yaz")
    args = parser.parse_args()
    result = crawl(args.url, max(1, args.sayfa), args.hiz)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.cikti:
        with open(args.cikti, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    return 1 if "hata" in result and "sayfalar" not in result else 0


if __name__ == "__main__":
    sys.exit(main())
