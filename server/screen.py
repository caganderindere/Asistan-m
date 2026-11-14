"""Cuba looks at this PC's screen when Çağan asks: one screenshot, read by Gemini, answered in words.

The screenshot is taken here, on the PC the server runs on, so it works from the voice, the phone and
Telegram alike. Nothing is kept: the picture goes to Gemini once and is dropped.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable

import httpx

from server.gemini_bridge import ONE_SHOT
from server.usage import GEMINI

MAX_WIDTH = 1920
LOOK_PROMPT = """Bu, Çağan'ın bilgisayar ekranının şu anki görüntüsü. Sen Cuba'sın, onun asistanı.
Sorusunu ekrandakine bakarak Türkçe, kısa ve net cevapla: sesli okunacak, en fazla birkaç cümle.
Ekranda hata varsa ne olduğunu ve muhtemel çözümünü söyle. Yazıları okuyabiliyorsan aynen aktar;
okuyamadığını uydurma."""


def grab_screen() -> bytes:
    """All monitors as one JPEG, no wider than MAX_WIDTH."""
    import mss
    from PIL import Image

    with mss.mss() as shot:
        raw = shot.grab(shot.monitors[0])
        image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    if image.width > MAX_WIDTH:
        image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=80)
    return out.getvalue()


async def look(key: str, model: str, question: str, grab: Callable[[], bytes] = grab_screen,
               client: httpx.AsyncClient | None = None) -> dict:
    """Gemini's answer to *question* about what is on the screen right now."""
    try:
        picture = grab()
    except Exception as error:  # noqa: BLE001 - no screen (locked, remote session) is told, not raised
        return {"error": f"Ekran görüntüsü alınamadı ({type(error).__name__})."}
    body = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(picture).decode()}},
            {"text": question or "Ekranda ne var?"},
        ]}],
        "systemInstruction": {"parts": [{"text": LOOK_PROMPT}]},
    }
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=8))
    try:
        response = await client.post(ONE_SHOT.format(model=model), json=body, headers={"x-goog-api-key": key})
        response.raise_for_status()
        data = response.json()
        GEMINI.add(data.get("usageMetadata"))
        parts = data["candidates"][0]["content"].get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
        return {"error": f"Ekrana bakılamadı ({type(error).__name__})."}
    finally:
        if own:
            await client.aclose()
    return {"gordugum": text} if text else {"error": "Gemini ekran hakkında bir şey söylemedi."}
