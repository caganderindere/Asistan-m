import datetime
import json

import httpx

from server.life import LifeLog, weather, web_search
from server.live import CubaTools


class Clock:
    def __init__(self, when):
        self.now = when

    def __call__(self):
        return self.now


def test_the_week_counts_kinds_and_the_sport_streak(tmp_path):
    clock = Clock(datetime.datetime(2026, 11, 10, 8, 0))
    life = LifeLog(tmp_path, clock)
    for day in (10, 11, 12):
        clock.now = datetime.datetime(2026, 11, day, 19, 0)
        life.add("spor", "koşu", 40, "6 km")
    life.add("araç", "İzmir'e yola çıktı")
    life.add("bilinmez", "x")
    clock.now = datetime.datetime(2026, 11, 13, 9, 0)  # no sport yet today: the streak still counts
    week = life.week()
    assert week.startswith("Bu hafta: spor 3, araç 1, diğer 1")
    assert "Spor serisi: 3 gün; son spor 2026-11-12" in week
    assert "- 2026-11-12 19:00 spor: koşu (40 dk) [6 km]" in week
    clock.now = datetime.datetime(2026, 11, 22, 9, 0)
    assert life.week() == "Son yedi günde kayıt yok."


def test_a_situation_runs_out_or_is_ended(tmp_path):
    clock = Clock(datetime.datetime(2026, 11, 13, 9, 0))
    life = LifeLog(tmp_path, clock)
    life.set_situation("araçta", 30)
    assert life.situation()["situation"] == "araçta" and "Çağan şu an araçta" in life.prompt()
    clock.now += datetime.timedelta(minutes=31)
    assert life.situation() is None and "Bilinen bir durum yok." in life.prompt()
    life.set_situation("uykuda")
    assert life.situation()["situation"] == "uykuda"
    assert life.set_situation("yok") is None and life.situation() is None


async def test_cuba_logs_life_and_tells_the_page(tmp_path):
    told = []

    async def nothing(*_):
        return None

    life = LifeLog(tmp_path)
    tools = CubaTools(nothing, lambda k: None, tmp_path, life=life, notify=told.append)
    done = await tools.run("hayat_kaydet", {"tur": "spor", "detay": "bench press 5x5", "sure_dk": 50})
    assert done["ok"] and "bench press 5x5" in done["son_yedi_gun"]
    await tools.run("durum", {"durum": "sporda"})
    assert [m["type"] for m in told] == ["life", "situation"]
    assert "Çağan şu an sporda" in tools.prompt()
    assert "error" in await tools.run("ara", {"soru": "maç"})  # no search without a key


def test_weather_reads_open_meteo():
    def world(request):
        if "geocoding" in str(request.url):
            return httpx.Response(200, json={"results": [{"name": "İzmir", "country": "Türkiye", "latitude": 38.4, "longitude": 27.1}]})
        hours = [f"2026-11-13T{h:02d}:00" for h in range(24)]
        return httpx.Response(200, json={
            "current": {"time": "2026-11-13T09:15", "temperature_2m": 17.2, "apparent_temperature": 16, "weather_code": 61,
                        "wind_speed_10m": 12, "precipitation": 0.4},
            "hourly": {"time": hours, "temperature_2m": [15] * 24, "precipitation_probability": [70] * 24, "weather_code": [61] * 24},
            "daily": {"temperature_2m_min": [12, 11], "temperature_2m_max": [19, 18], "precipitation_probability_max": [80, 20],
                      "sunrise": ["", ""], "sunset": ["", ""]},
        })

    import asyncio
    client = httpx.AsyncClient(transport=httpx.MockTransport(world))
    result = asyncio.run(weather("izmir", client))
    assert result["yer"] == "İzmir, Türkiye" and "17.2°C" in result["simdi"] and "hafif yağmur" in result["simdi"]
    assert result["sonraki_saatler"][0].startswith("10:00") and len(result["sonraki_saatler"]) == 6
    assert "%80" in result["bugun"]


async def test_search_answers_with_sources():
    def world(request):
        body = json.loads(request.content)
        assert body["tools"] == [{"google_search": {}}]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Galatasaray 2-1 kazandı."}]},
                                                         "groundingMetadata": {"groundingChunks": [{"web": {"title": "ntv.com.tr"}}]}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(world))
    assert await web_search("k", "m", "maç kaç bitti", client) == {"cevap": "Galatasaray 2-1 kazandı.", "kaynaklar": ["ntv.com.tr"]}
