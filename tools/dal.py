"""Work branches for the terminal's Cuba: code work happens in its own git worktree.

    dal.py ac <iş adı>      opens cuba/<iş> in <proje>-isler/<iş>; prints the folder to work in
    dal.py liste            the open work branches and what they changed

Merging and throwing away are Çağan's call; he says it to Cuba, who does it from the server.
Exit codes: 0 done, 2 refused.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.worktrees import DalError, branches, is_repo, open_branch  # noqa: E402


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    folder = os.getcwd()
    if not is_repo(folder):
        print("Bu proje git deposu değil; iş dalı açılamaz. Projede doğrudan çalış.")
        return 2
    try:
        if argv[:1] == ["ac"] and len(argv) > 1:
            result = open_branch(folder, " ".join(argv[1:]))
        elif argv[:1] == ["liste"]:
            result = branches(folder)
        else:
            print(__doc__)
            return 2
    except DalError as e:
        print(f"HATA: {e}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
