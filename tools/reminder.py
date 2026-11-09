"""Reminder command line the assistant uses.

  reminder.py add --at "YYYY-MM-DD HH:MM" --text "..."   exit 0, 2 (bad/past time), 3 (scheduler)
  reminder.py list
  reminder.py delete <id>                                  exit 0, 1 (not found)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.reminders import PastTimeError, ReminderStore, WindowsScheduler  # noqa: E402
from server.config import ROOT  # noqa: E402

TIME_FORMAT = "%Y-%m-%d %H:%M"
STORE_PATH = ROOT / "asistan" / "hatirlatmalar.json"


def main(argv: list[str], store: ReminderStore | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reminder.py")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("--at", required=True)
    add.add_argument("--text", required=True)
    commands.add_parser("list")
    delete = commands.add_parser("delete")
    delete.add_argument("id")
    args = parser.parse_args(argv)
    store = store or ReminderStore(STORE_PATH, WindowsScheduler())

    if args.command == "add":
        try:
            at = datetime.strptime(args.at, TIME_FORMAT)
        except ValueError:
            print("Tarih biçimi YYYY-MM-DD HH:MM olmalı", file=sys.stderr)
            return 2
        try:
            reminder = store.add(at, args.text)
        except PastTimeError:
            print("Bu zaman geçmişte", file=sys.stderr)
            return 2
        except RuntimeError as exc:
            print(f"Hatırlatma kurulamadı: {exc}", file=sys.stderr)
            return 3
        print(f"Kuruldu: {reminder.id} {reminder.at.strftime(TIME_FORMAT)}")
        return 0
    if args.command == "list":
        for r in store.upcoming():
            print(f"{r.id}  {r.at.strftime(TIME_FORMAT)}  {r.text}")
        return 0
    return 0 if store.delete(args.id) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
