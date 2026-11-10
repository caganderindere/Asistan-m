"""Write each team member's system prompt from the templates in ekip/."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path

from server.config import ROOT
from server.team import LEAD, ROLES

ASSISTANT = ROOT / "asistan" / "ASISTAN.md"
TEMPLATES = ROOT / "ekip"
EKIP_TOOL = ROOT / "tools" / "ekip.py"


def write_prompts(out_dir: Path, models: Mapping[str, str]) -> dict[str, Path]:
    """Return the prompt file of every role, freshly written into *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)
    roster = "\n".join(
        f"- `{role.id}`: {role.name}, {role.department}, model {models.get(role.id, '?')}. {role.duty}"
        for role in ROLES
        if role.id != LEAD
    )
    lead = ASSISTANT.read_text(encoding="utf-8") + (TEMPLATES / "LIDER.md").read_text(encoding="utf-8")
    lead = lead.replace("{{roster}}", roster).replace("{{ekip}}", f"{sys.executable} {EKIP_TOOL}")
    worker = (TEMPLATES / "CALISAN.md").read_text(encoding="utf-8")

    paths: dict[str, Path] = {}
    for role in ROLES:
        text = lead if role.id == LEAD else (
            worker.replace("{{name}}", role.name)
            .replace("{{department}}", role.department)
            .replace("{{duty}}", role.duty)
        )
        paths[role.id] = out_dir / f"{role.id}.md"
        paths[role.id].write_text(text, encoding="utf-8")
    return paths
