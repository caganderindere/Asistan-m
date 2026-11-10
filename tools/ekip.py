"""The team lead's handle on the team: plan, start and hand out work.

Talks to the running Claude Ses server, which owns the worker processes.
Exit codes: 0 done, 2 the request was refused (reason printed), 3 server unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

STATUS = {
    "proposed": "önerildi", "queued": "sırada", "running": "çalışıyor",
    "done": "bitti", "error": "hata", "stopped": "durduruldu",
}


AGENT_STATE = {"idle": "boşta", "working": "çalışıyor", "error": "hata"}


def call(path: str, body: dict | None = None) -> dict:
    port = os.environ.get("CLAUDE_SES_PORT", "8765")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/team/{path}",
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Ekip-Token": os.environ.get("CLAUDE_SES_TOKEN", "")},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        try:
            reason = json.load(e).get("error", "")
        except ValueError:
            reason = ""
        print(reason or f"Sunucu isteği reddetti ({e.code}).")
        sys.exit(2)
    except OSError:
        print("Claude Ses sunucusuna ulaşılamadı.")
        sys.exit(3)


def task_line(task: dict) -> str:
    return f"#{task['id']} {task['to']} [{STATUS.get(task['status'], task['status'])}]: {task['text']}"


def split_task(spec: str) -> dict:
    to, sep, text = spec.partition(":")
    if not sep:
        print(f'Görev "<çalışan>: <iş>" biçiminde olmalı: {spec}')
        sys.exit(2)
    return {"to": to.strip(), "text": text.strip()}


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ekip.py")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--gorev", action="append", required=True, metavar='"çalışan: iş"')
    sub.add_parser("baslat").add_argument("ids", nargs="*", type=int)
    ver = sub.add_parser("ver")
    ver.add_argument("to")
    ver.add_argument("text")
    sub.add_parser("sor").add_argument("question")
    sub.add_parser("iptal")
    sub.add_parser("durum")
    args = parser.parse_args(argv)

    if args.command == "plan":
        tasks = call("plan", {"tasks": [split_task(spec) for spec in args.gorev]})["tasks"]
        print("Plan kaydedildi, kimse başlamadı. Çağan onaylayınca 'baslat' çalıştır.")
        print("\n".join(task_line(t) for t in tasks))
    elif args.command == "baslat":
        tasks = call("begin", {"ids": args.ids})["tasks"]
        print("Başlatıldı. Raporlar [EKİP RAPORU] mesajı olarak gelecek; bekleme.")
        print("\n".join(task_line(t) for t in tasks))
    elif args.command == "ver":
        task = call("assign", {"to": args.to, "text": args.text})["task"]
        print("Görev verildi. Raporu [EKİP RAPORU] mesajı olarak gelecek; bekleme.")
        print(task_line(task))
    elif args.command == "sor":
        call("ask", {"question": args.question})
        print("Soru ekranda gösteriliyor. Şimdi soruyu Çağan'a sesli sor ve yanıtını bekle.")
    elif args.command == "iptal":
        print(f"{call('cancel', {})['removed']} önerilmiş görev silindi.")
    elif args.command == "durum":
        state = call("state")
        for agent in state["agents"]:
            doing = f" ({agent['activity']})" if agent["activity"] else ""
            print(f"{agent['id']}: {AGENT_STATE.get(agent['state'], agent['state'])}{doing}")
        print("\n".join(task_line(t) for t in state["tasks"]) or "Görev yok.")


if __name__ == "__main__":
    main()
