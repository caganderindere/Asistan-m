"""Records a narrated, captioned tour of Cuba from made-up data, for sharing (LinkedIn): no real talk or memory.

  .venv\\Scripts\\python tools\\tanitim.py [çıktı.mp4]      default: the desktop, Cuba-tanitim.mp4

Each scene's narration is spoken by Edge TTS first, so the page holds the scene exactly as long as its line;
the browser recording and the lines are then put together with ffmpeg (the imageio-ffmpeg build).
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.screenshots import BASE, DOCS, JOB_CARDS, OUT, SOCKETS, open_page  # noqa: E402

VOICE = "tr-TR-AhmetNeural"
SIZE = {"width": 1920, "height": 1080}
VIEW = {"width": 1536, "height": 864}  # recorded at this size and scaled up to SIZE: the page reads larger in a feed
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# (scene, narration): the line is also the caption, since LinkedIn plays videos muted.
SCENES = [
    ("intro", "Bu Cuba. Sesle konuştuğum kişisel asistanım ve onun yönettiği bir yapay zekâ ekibi."),
    ("orb", "Cuba ile telefonda konuşur gibi konuşuyorum. Gemini Live sayesinde cevap yarım saniyede geliyor."),
    ("jobs", "Bir iş verdiğimde Cuba onu doğru projenin ekibine veriyor ve sohbete devam ediyor. "
             "Süren işler kürenin altında kart olarak duruyor."),
    ("office", "Ekip, Claude Code üzerinde çalışan ajanlardan oluşuyor. Kim hangi dosyayı yazıyor, "
               "kim test çalıştırıyor, ofiste canlı görüyorum."),
    ("talk", "İş bitince ekip kendi arasında toplantı yapıyor. Cuba da sonucu bana bir iki cümleyle anlatıyor."),
    ("docs", "Araştırmalar, raporlar ve sunumlar tek bir yerde birikiyor. Sunucu her belgenin gerçekten "
             "oluştuğunu kontrol ediyor; Cuba olmayan bir belgeye hazır diyemiyor."),
    ("schedule", "İleri zamanlı iş de kurabiliyorum: otuz dakika sonra blogda bağımlılıkları güncelleyin, diyorum."),
    ("phone", "Telefondan da konuşabiliyorum. Ekip yalnızca benim yapabileceğim bir adımda takılırsa telefonum çalıyor."),
    ("outro", "Konuşma Gemini'de, iş Claude Code'da. Gündelik sohbet hiç Claude token'ı harcamıyor."),
]

OVERLAY_CSS = """
/* Over the input bar, which the tour never uses; the job cards sit just above it. */
#tour-cap { position: fixed; left: 50%; bottom: 14px; transform: translateX(-50%); z-index: 9999; width: max-content; max-width: 1100px;
  padding: 12px 24px; border-radius: 14px; background: rgb(4 6 15 / .88); border: 1px solid rgb(90 200 255 / .35);
  color: #eef4ff; font: 500 25px/1.4 'Segoe UI', system-ui, sans-serif; text-align: center; pointer-events: none;
  box-shadow: 0 10px 40px rgb(0 0 0 / .5); transition: opacity .3s; }
#tour-card { position: fixed; inset: 0; z-index: 9998; display: grid; place-content: center; gap: 18px; text-align: center;
  background: radial-gradient(circle at 50% 40%, #13254a, #04060f 70%); color: #eef4ff; transition: opacity .6s;
  font-family: 'Segoe UI', system-ui, sans-serif; }
#tour-card h1 { margin: 0; font-size: 104px; letter-spacing: .3em; font-weight: 700; color: #7fd8ff;
  text-shadow: 0 0 40px rgb(80 190 255 / .6); }
#tour-card p { margin: 0; font-size: 36px; color: #b9c6e4; }
#tour-card small { font-size: 26px; color: #7fd8ff; }
#tour-phone { position: fixed; inset: 0; z-index: 9997; display: grid; place-items: center; background: rgb(4 6 15 / .75);
  transition: opacity .5s; }
#tour-phone img { height: 620px; margin-bottom: 110px; border-radius: 48px; border: 10px solid #1c2440; box-shadow: 0 30px 80px rgb(0 0 0 / .6); }
"""


async def speak(lines: list[str], folder: Path) -> list[Path]:
    files = []
    for n, line in enumerate(lines):
        path = folder / f"{n}.mp3"
        await edge_tts.Communicate(line, VOICE, rate="+4%").save(str(path))
        files.append(path)
    return files


def duration(path: Path) -> float:
    """Seconds of audio, from ffmpeg's own reading of the file."""
    info = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info.stderr).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def caption(page, text: str) -> None:
    page.evaluate("""text => {
        let cap = document.getElementById('tour-cap');
        if (!cap) { cap = document.createElement('div'); cap.id = 'tour-cap'; }
        // An open dialog sits in the top layer, above any z-index: the caption goes in with it.
        (document.querySelector('dialog[open]') ?? document.body).append(cap);
        cap.textContent = text;
    }""", text)


def card(page, title: str, line: str, small: str = "") -> None:
    page.evaluate("""([title, line, small]) => {
        document.getElementById('tour-card')?.remove();
        const card = document.createElement('div');
        card.id = 'tour-card';
        card.innerHTML = '<h1></h1><p></p><small></small>';
        card.querySelector('h1').textContent = title;
        card.querySelector('p').textContent = line;
        card.querySelector('small').textContent = small;
        document.body.append(card);
    }""", [title, line, small])


def drop(page, element_id: str) -> None:
    page.evaluate("""id => { const el = document.getElementById(id); if (el) { el.style.opacity = 0;
        setTimeout(() => el.remove(), 700); } }""", element_id)


def act(page, scene: str) -> None:
    """What the page does as a scene begins."""
    if scene == "intro":
        card(page, "CUBA", "Kişisel AI komuta merkezi", "Gemini Live · Claude Code")
    elif scene == "orb":
        drop(page, "tour-card")
    elif scene == "jobs":
        for job in JOB_CARDS[:2]:
            SOCKETS[-1].send(json.dumps(job, ensure_ascii=False))
            page.wait_for_timeout(1200)
    elif scene == "office":
        SOCKETS[-1].send(json.dumps(JOB_CARDS[2], ensure_ascii=False))
        page.wait_for_timeout(1500)
        page.click("#tabOffice")
    elif scene == "talk":
        page.click('.side-tabs [data-pane="talk"]')
    elif scene == "docs":
        page.click('.side-tabs [data-pane="docs"]')
        page.wait_for_timeout(2500)
        page.click(".doc-open >> nth=0")
        page.wait_for_selector("#docDialog[open]")
    elif scene == "schedule":
        page.evaluate("document.getElementById('docDialog').close()")
        page.click('.side-tabs [data-pane="schedule"]')
    elif scene == "phone":
        page.evaluate("""() => { const box = document.createElement('div'); box.id = 'tour-phone';
            box.innerHTML = '<img src="/tour/telefon.png" alt="">'; document.body.append(box); }""")
    elif scene == "outro":
        drop(page, "tour-phone")
        card(page, "CUBA", "Konuşma Gemini'de, iş Claude Code'da.", "github.com/caganderindere/Asistan-m")


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "Cuba-tanitim.mp4"
    if not (OUT / "telefon.png").is_file():
        sys.exit("Önce tools\\screenshots.py çalıştır: telefon görüntüsü gerekiyor.")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        voices = asyncio.run(speak([line for _, line in SCENES], work))
        lengths = [duration(v) for v in voices]
        starts = []
        with sync_playwright() as p:
            began = time.monotonic()  # the recording starts with the page
            browser, context, page = open_page(p, VIEW, record_video_dir=str(work), record_video_size=VIEW)
            page.route(f"{BASE}/tour/*", lambda route: route.fulfill(
                body=(OUT / route.request.url.rsplit("/", 1)[1]).read_bytes(), content_type="image/png"))
            page.add_style_tag(content=OVERLAY_CSS)
            for (scene, line), length in zip(SCENES, lengths):
                act(page, scene)
                caption(page, line)
                starts.append(time.monotonic() - began)
                page.wait_for_timeout(int((length + 0.7) * 1000))
            video = Path(page.video.path())
            context.close()
            browser.close()
        # Every line placed where its scene began; the page's load before the first scene is cut away.
        cut = max(starts[0] - 0.3, 0)
        inputs, mix = ["-i", str(video)], []
        for n, (voice, start) in enumerate(zip(voices, starts), 1):
            inputs += ["-i", str(voice)]
            delay = int((start - cut) * 1000)
            mix.append(f"[{n}:a]adelay={delay}|{delay}[a{n}]")
        labels = "".join(f"[a{n}]" for n in range(1, len(voices) + 1))
        mix.append(f"{labels}amix=inputs={len(voices)}:normalize=0[voice]")
        total = starts[-1] + lengths[-1] + 1.2 - cut
        subprocess.run([
            FFMPEG, "-y", "-ss", f"{cut:.2f}", *inputs[:2], *inputs[2:],
            "-filter_complex", ";".join(mix), "-map", "0:v", "-map", "[voice]", "-t", f"{total:.2f}",
            "-vf", f"scale={SIZE['width']}:{SIZE['height']}:flags=lanczos", "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(target),
        ], check=True, capture_output=True)
    print(target)


if __name__ == "__main__":
    main()
