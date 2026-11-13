"""Reach Çağan when the work needs his own hand: Cuba says it aloud, or Telegram, or rings his phone.

    cagan.py "<mesaj>"           he hears or reads it
    cagan.py --acil "<mesaj>"    and if he is away, his phone rings too

For what only he can do: a Windows admin (UAC) prompt, a login or 2FA code, a payment, a decision
the work cannot go on without. Exit codes as in ekip.py: 0 done, 2 refused, 3 server unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from ekip import call


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--acil", action="store_true", help="Çağan uzaktaysa telefonunu da çaldır")
    parser.add_argument("mesaj", nargs="+")
    args = parser.parse_args()
    result = call("cagan", {"mesaj": " ".join(args.mesaj), "acil": args.acil,
                            "terminal": os.environ.get("CLAUDE_SES_TERMINAL", "")})
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
