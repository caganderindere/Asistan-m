"""The team talking finished work over: a real exchange, played out on Gemini so it costs no Claude tokens.

One Gemini call writes the whole meeting from the members' reports. Unlike taking turns once
around the table, people answer each other by name, an objection is answered by whoever it was
aimed at, and the talk stops as soon as they agree. The meeting ends with decisions and the work
it proposes, which waits for Çağan's yes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

MAX_LINES = 10
LINE_CHARS = 300
REPORT_CHARS = 2500

PROMPT = """Bir yazılım ekibinin iş sonrası toplantısını yazıyorsun. Ekip az önce bir işi bitirdi; aşağıda her
üyenin kendi raporu var. Toplantıyı, üyelerin gerçekten konuşacağı gibi yaz:
- Herkes kendi uzmanlığından konuşur ve başkasının raporunda gördüğü somut sorunu, eksiği ya da kendi
  işiyle çakışan şeyi söyler. Nezaketen onaylama yok; sorun yoksa bunu kısaca söyler.
- Biri birine itiraz eder ya da soru sorarsa sıradaki söz o kişinindir: adıyla hitap edilir ve cevap verir.
- Raporlarda olmayan hiçbir şeyi uydurma: yazılmamış test, hata ya da dosya icat etme.
- Ekip anlaşınca konuşma biter; en fazla {max_lines} söz. Son sözü {lead} alır ve neyde anlaşıldığını,
  açık kalanı söyler.
- Her söz bir iki cümle, Türkçe, düz konuşma dili.
Toplantıdan çıkan kararları ve yapılması gereken işleri ayrıca yaz. İş yalnızca konuşmada gerçekten
ortaya çıktıysa yazılır; "kim" alanı üyelerden birinin kimliğidir.

Üyeler (kimlik: ad, görev):
{members}

Yalnızca şu JSON'u döndür:
{{"lines": [{{"who": "kimlik", "text": "..."}}], "kararlar": ["..."], "gorevler": [{{"kim": "kimlik", "is": "..."}}]}}"""

Ask = Callable[[str, str, bool], Awaitable[str]]


async def hold_meeting(ask: Ask, members: list[dict], reports: list[str], lead: dict) -> dict | None:
    """Write the meeting of *members* (dicts with id, name, duty) over *reports*; None if it failed.

    *lead* chairs it and has the last word. The result holds only lines by known people.
    """
    people = [*members, lead]
    known = {p["id"] for p in people}
    system = PROMPT.format(
        max_lines=MAX_LINES,
        lead=lead["name"],
        members="\n".join(f"- {p['id']}: {p['name']}, {p.get('duty') or 'ekip üyesi'}" for p in people),
    )
    try:
        raw = await ask(system, "\n\n".join(r[-REPORT_CHARS:] for r in reports), True)
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - no meeting is better than a broken one
        logger.exception("meeting failed")
        return None
    lines = [
        {"who": str(line.get("who")), "text": str(line.get("text", "")).strip()[:LINE_CHARS]}
        for line in data.get("lines", []) if isinstance(line, dict)
    ]
    lines = [line for line in lines if line["who"] in known and line["text"]][:MAX_LINES]
    if not lines:
        return None
    tasks = [
        {"to": str(item.get("kim")), "text": str(item.get("is", "")).strip()}
        for item in data.get("gorevler", []) if isinstance(item, dict)
    ]
    return {
        "lines": lines,
        "decisions": [str(d).strip() for d in data.get("kararlar", []) if str(d).strip()],
        "tasks": [t for t in tasks if t["to"] in known and t["text"]],
    }
