"""Move people around the office: the office is physical, everyone walks.

    ofis.py git <yer> <kim> [<kim> ...]   e.g. ofis.py git toplanti cuba kidemli
    ofis.py nerede                       who has been sent where

Places: masa, toplanti, mutfak, dinlenme, yonetim (Cuba's room), serbest (back to their own routine).
People: cuba, kidemli, gelistirici, testci, asistan, pazarlama, icerik, sosyal, cagan
(or "herkes", "ekip" for the software team, "pazarlamaekibi").
Exit codes as in ekip.py: 0 done, 2 refused, 3 server unreachable.
"""

from __future__ import annotations

import argparse
import sys

from ekip import call

PEOPLE = {
    "cuba": "lider", "lider": "lider", "kidemli": "kidemli", "kıdemli": "kidemli",
    "gelistirici": "gelistirici", "geliştirici": "gelistirici", "testci": "testci", "testçi": "testci",
    "asistan": "asistan", "cagan": "cagan", "çağan": "cagan", "ben": "cagan",
    "pazarlama": "pazarlama", "pazarlamaci": "pazarlama", "pazarlamacı": "pazarlama",
    "icerik": "icerik", "içerik": "icerik", "icerikci": "icerik", "içerikçi": "icerik",
    "sosyal": "sosyal", "sosyalci": "sosyal",
}
SOFTWARE = ["kidemli", "gelistirici", "testci", "asistan"]
MARKETING = ["pazarlama", "icerik", "sosyal"]
EVERYONE = ["lider", *SOFTWARE, *MARKETING, "cagan"]
PLACES = {
    "masa": "desk", "masasina": "desk", "toplanti": "meeting", "toplantı": "meeting",
    "mutfak": "coffee", "dinlenme": "sofa", "yonetim": "visit", "yönetim": "visit", "serbest": "",
}
SPOKEN = {"desk": "masasına", "meeting": "toplantı odasına", "coffee": "mutfağa", "sofa": "dinlenme alanına",
          "visit": "Cuba'nın odasına", "": "kendi düzenine"}


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ofis.py")
    sub = parser.add_subparsers(dest="command", required=True)
    go = sub.add_parser("git")
    go.add_argument("yer")
    go.add_argument("kim", nargs="+")
    sub.add_parser("nerede")
    args = parser.parse_args(argv)

    if args.command == "nerede":
        places = call("places", None)["places"]
        print("\n".join(f"{who}: {SPOKEN.get(where, where)}" for who, where in places.items()) or "Herkes kendi düzeninde.")
        return

    where = PLACES.get(args.yer.lower())
    if where is None:
        print(f"Bilinmeyen yer: {args.yer}. Yerler: {', '.join(p for p in PLACES if p.isascii())}")
        sys.exit(2)
    who: list[str] = []
    for name in args.kim:
        name = name.lower().strip(",")
        if name in ("herkes", "ekip", "pazarlamaekibi"):
            who += {"herkes": EVERYONE, "ekip": SOFTWARE, "pazarlamaekibi": MARKETING}[name]
        elif name in PEOPLE:
            who.append(PEOPLE[name])
        else:
            print(f"Bilinmeyen kişi: {name}. Kişiler: cuba, kidemli, gelistirici, testci, asistan, pazarlama, icerik, sosyal, cagan")
            sys.exit(2)
    call("move", {"who": who, "where": where})
    print(f"{', '.join(dict.fromkeys(args.kim))} {SPOKEN[where]} gidiyor.")


if __name__ == "__main__":
    main()
