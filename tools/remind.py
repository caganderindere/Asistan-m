"""Fired by Task Scheduler: show the reminder as a notification and speak it."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import winsound
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.reminders import ReminderStore, WindowsScheduler  # noqa: E402
from server.config import ROOT, load_config  # noqa: E402
from server.tts import synthesize  # noqa: E402
from tools.reminder import STORE_PATH  # noqa: E402

POWERSHELL_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
# The text reaches PowerShell through an environment variable, so quotes and
# Turkish characters in it never need escaping on a command line.
TOAST_SCRIPT = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $xml.GetElementsByTagName('text')
$texts.Item(0).AppendChild($xml.CreateTextNode('Hatırlatma')) | Out-Null
$texts.Item(1).AppendChild($xml.CreateTextNode($env:CLAUDE_SES_REMINDER)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{POWERSHELL_APP_ID}').Show($toast)
"""


def show_notification(text: str) -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", TOAST_SCRIPT],
        env={**os.environ, "CLAUDE_SES_REMINDER": text},
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )


def main(reminder_id: str) -> int:
    scheduler = WindowsScheduler()
    store = ReminderStore(STORE_PATH, scheduler)
    reminder = store.get(reminder_id)
    if reminder is None or reminder.done:
        scheduler.delete(reminder_id)
        return 0
    show_notification(reminder.text)
    try:
        wav = asyncio.run(synthesize(f"Hatırlatma: {reminder.text}", load_config(ROOT / "config.json").voice))
        winsound.PlaySound(wav, winsound.SND_MEMORY)
    except Exception:
        logging.exception("reminder %s could not be spoken", reminder_id)
    store.mark_done(reminder_id)
    scheduler.delete(reminder_id)
    return 0


if __name__ == "__main__":
    (ROOT / "data").mkdir(exist_ok=True)
    logging.basicConfig(filename=ROOT / "data" / "remind.log", level=logging.INFO, encoding="utf-8")
    sys.exit(main(sys.argv[1]))
