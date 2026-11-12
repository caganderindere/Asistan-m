"""Çağan's days: what he does (sport, driving, meals, sleep…), what he is doing right now, and the world outside.

Cuba logs each thing Çağan mentions to data/yasam.jsonl and sees the last week in its prompt,
so it can say "third workout this week" or notice that he has not slept enough. A situation
("araçta", "uykuda"…) changes how Cuba talks until it runs out. Weather comes from Open-Meteo
(free, no key); other current facts from a Gemini call grounded in Google Search.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import httpx

from server.usage import GEMINI

KINDS = ("spor", "araç", "yemek", "uyku", "sağlık", "iş", "sosyal", "alışveriş", "diğer")
# How long each situation lasts when Çağan does not say.
SITUATIONS = {"araçta": 60, "sporda": 90, "işte": 240, "uykuda": 480, "dışarıda": 120, "evde": 240, "toplantıda": 60}
WEEK_LINES = 25

SEARCH_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_CODES = {
    0: "açık", 1: "çoğunlukla açık", 2: "parçalı bulutlu", 3: "kapalı", 45: "sisli", 48: "kırağılı sis",
    51: "hafif çisenti", 53: "çisenti", 55: "yoğun çisenti", 61: "hafif yağmur", 63: "yağmurlu", 65: "kuvvetli yağmur",
    66: "dondurucu yağmur", 67: "kuvvetli dondurucu yağmur", 71: "hafif kar", 73: "karlı", 75: "yoğun kar",
    77: "kar taneli", 80: "sağanak", 81: "kuvvetli sağanak", 82: "şiddetli sağanak", 85: "kar sağanağı",
    86: "yoğun kar sağanağı", 95: "gök gürültülü fırtına", 96: "dolulu fırtına", 99: "şiddetli dolulu fırtına",
}


class LifeLog:
    def __init__(self, folder: Path, clock: Callable[[], datetime.datetime] = datetime.datetime.now) -> None:
        self._log = folder / "yasam.jsonl"
        self._state = folder / "durum.json"
        self._clock = clock

    # ── What he did ────────────────────────────────────────────

    def add(self, kind: str, detail: str, minutes: int | None = None, value: str = "") -> dict:
        kind = kind if kind in KINDS else "diğer"
        entry = {"time": self._clock().strftime("%Y-%m-%d %H:%M"), "kind": kind, "detail": " ".join(detail.split())}
        if minutes:
            entry["minutes"] = int(minutes)
        if value:
            entry["value"] = value
        self._log.parent.mkdir(parents=True, exist_ok=True)
        with self._log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self, days: int = 7) -> list[dict]:
        since = (self._clock() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
        try:
            rows = self._log.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        found = []
        for row in rows:
            try:
                entry = json.loads(row)
            except ValueError:
                continue
            if entry.get("time", "") >= since:
                found.append(entry)
        return found

    def day(self, day: str) -> list[dict]:
        return [e for e in self.entries(days=60) if e["time"].startswith(day)]

    def week(self) -> str:
        """The last seven days for Cuba's prompt: counts per kind, a sport streak, the latest entries."""
        entries = self.entries()
        if not entries:
            return "Son yedi günde kayıt yok."
        counts = Counter(e["kind"] for e in entries)
        sport_days = {e["time"][:10] for e in entries if e["kind"] == "spor"}
        lines = ["Bu hafta: " + ", ".join(f"{kind} {n}" for kind, n in counts.most_common())]
        # Days in a row with sport, counting back from today (or yesterday, if today is still to come).
        today = self._clock().date()
        day = today if today.isoformat() in sport_days else today - datetime.timedelta(days=1)
        streak = 0
        while day.isoformat() in sport_days:
            streak += 1
            day -= datetime.timedelta(days=1)
        last_sport = max(sport_days, default="")
        lines.append(f"Spor serisi: {streak} gün" + (f"; son spor {last_sport}" if last_sport else "; bu hafta spor yok"))
        for e in entries[-WEEK_LINES:]:
            extra = f" ({e['minutes']} dk)" if e.get("minutes") else ""
            extra += f" [{e['value']}]" if e.get("value") else ""
            lines.append(f"- {e['time']} {e['kind']}: {e['detail']}{extra}")
        return "\n".join(lines)

    # ── What he is doing now ───────────────────────────────────

    def set_situation(self, situation: str, minutes: int | None = None) -> dict | None:
        """Say what Çağan is doing; "yok" or an unknown word ends it. Returns the new situation."""
        if situation not in SITUATIONS:
            self._state.unlink(missing_ok=True)
            return None
        until = self._clock() + datetime.timedelta(minutes=minutes or SITUATIONS[situation])
        state = {"situation": situation, "since": self._clock().strftime("%H:%M"), "until": until.isoformat(timespec="minutes")}
        self._state.parent.mkdir(parents=True, exist_ok=True)
        self._state.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return state

    def situation(self) -> dict | None:
        try:
            state = json.loads(self._state.read_text(encoding="utf-8"))
            if datetime.datetime.fromisoformat(state["until"]) > self._clock():
                return state
        except (FileNotFoundError, ValueError, KeyError):
            pass
        return None

    def prompt(self) -> str:
        now = self.situation()
        where = (f"Çağan şu an {now['situation']} ({now['since']}'den beri). Ona göre davran."
                 if now else "Bilinen bir durum yok.")
        return f"# Şu anki durum\n{where}\n\n# Çağan'ın son yedi günü\n{self.week()}"


# ── The world outside ───────────────────────────────────────────

async def weather(place: str, client: httpx.AsyncClient | None = None) -> dict:
    """Now and the next hours at *place*, from Open-Meteo."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(15, connect=8))
    try:
        found = (await client.get(GEOCODE_URL, params={"name": place, "count": 1, "language": "tr"})).json()
        if not found.get("results"):
            return {"error": f"{place} bulunamadı."}
        spot = found["results"][0]
        data = (await client.get(FORECAST_URL, params={
            "latitude": spot["latitude"], "longitude": spot["longitude"], "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        })).json()
    except (httpx.HTTPError, ValueError, KeyError) as error:
        return {"error": f"Hava durumuna ulaşılamadı ({type(error).__name__})."}
    finally:
        if own:
            await client.aclose()
    now = data["current"]
    hours = data["hourly"]
    start = next((i for i, t in enumerate(hours["time"]) if t >= now["time"]), 0)
    return {
        "yer": f"{spot['name']}, {spot.get('country', '')}".strip(", "),
        "simdi": f"{now['temperature_2m']}°C (hissedilen {now['apparent_temperature']}°C), "
                 f"{WEATHER_CODES.get(now['weather_code'], 'bilinmiyor')}, rüzgar {now['wind_speed_10m']} km/sa",
        "sonraki_saatler": [
            f"{hours['time'][i][11:16]} {hours['temperature_2m'][i]}°C, yağış %{hours['precipitation_probability'][i]}, "
            f"{WEATHER_CODES.get(hours['weather_code'][i], '')}"
            for i in range(start, min(start + 6, len(hours["time"])))
        ],
        "bugun": f"en düşük {data['daily']['temperature_2m_min'][0]}°C, en yüksek {data['daily']['temperature_2m_max'][0]}°C, "
                 f"yağış olasılığı %{data['daily']['precipitation_probability_max'][0]}",
        "yarin": f"en düşük {data['daily']['temperature_2m_min'][1]}°C, en yüksek {data['daily']['temperature_2m_max'][1]}°C, "
                 f"yağış olasılığı %{data['daily']['precipitation_probability_max'][1]}",
    }


async def web_search(key: str, model: str, question: str, client: httpx.AsyncClient | None = None) -> dict:
    """A short, current answer from Gemini grounded in Google Search, with its sources."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(40, connect=8))
    body = {
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "systemInstruction": {"parts": [{"text": "Google'da arayıp kısa, güncel ve Türkçe cevap ver. Bulamadığını uydurma."}]},
        "tools": [{"google_search": {}}],
    }
    try:
        response = await client.post(SEARCH_URL.format(model=model), json=body, headers={"x-goog-api-key": key})
        response.raise_for_status()
        data = response.json()
        GEMINI.add(data.get("usageMetadata"))
        candidate = data["candidates"][0]
        text = "".join(p.get("text", "") for p in candidate["content"].get("parts", []) if not p.get("thought"))
        sources = [c["web"].get("title", "") for c in candidate.get("groundingMetadata", {}).get("groundingChunks", [])
                   if "web" in c][:3]
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
        return {"error": f"Arama yapılamadı ({type(error).__name__})."}
    finally:
        if own:
            await client.aclose()
    return {"cevap": text.strip(), "kaynaklar": sources}
