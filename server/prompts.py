"""Write each team member's system prompt from the templates in ekip/."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

from server.config import ROOT
from server.team import LEAD, ROLES

ASSISTANT = ROOT / "asistan" / "ASISTAN.md"
PROFILE = ROOT / "asistan" / "cagan.md"  # what Cuba has learned about Çağan
# Installers the team may run without asking: Çağan wants it to fetch the tools it needs.
INSTALLERS = ("pip install", "uv add", "uv pip install", "npm install", "npx", "winget install")
TEMPLATES = ROOT / "ekip"
EKIP_TOOL = ROOT / "tools" / "ekip.py"
OFIS_TOOL = ROOT / "tools" / "ofis.py"


def ofis_command() -> str:
    return f"{sys.executable} {OFIS_TOOL}"


def office_section() -> str:
    return (TEMPLATES / "OFIS.md").read_text(encoding="utf-8").replace("{{ofis}}", ofis_command())


def write_prompts(out_dir: Path, models: Mapping[str, str]) -> dict[str, Path]:
    """Return the prompt file of every role, freshly written into *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)
    roster = "\n".join(
        f"- `{role.id}`: {role.name}, {role.department}, model {models.get(role.id, '?')}. {role.duty}"
        for role in ROLES
        if role.id != LEAD
    )
    lead = ASSISTANT.read_text(encoding="utf-8") + (TEMPLATES / "LIDER.md").read_text(encoding="utf-8")
    lead = lead.replace("{{roster}}", roster).replace("{{ekip}}", f"{sys.executable} {EKIP_TOOL}") + office_section()
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


PLUGIN = "cuba-ekip"


def _model_alias(model: str) -> str:
    """Subagent files name models by family."""
    for family in ("opus", "sonnet", "haiku"):
        if family in model:
            return family
    return "inherit"


def write_terminal_team(out_dir: Path, models: Mapping[str, str]) -> tuple[Path, Path]:
    """Write the terminal Claude's charter and the plugin holding its team; return both paths."""
    workers = [role for role in ROLES if role.id != LEAD]
    roster = "\n".join(
        f"- `{role.id}`: {role.name}, {role.department}, model {models.get(role.id, '?')}. {role.duty}"
        for role in workers
    )
    charter = out_dir / "TERMINAL.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    charter.write_text(
        (TEMPLATES / "TERMINAL.md").read_text(encoding="utf-8").replace("{{roster}}", roster).replace("{{profil}}", str(PROFILE)) + office_section(),
        encoding="utf-8",
    )

    plugin = out_dir / PLUGIN
    (plugin / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": PLUGIN, "version": "1.0.0", "description": "Cuba'nın yazılım ekibi"}), encoding="utf-8"
    )
    agents = plugin / "agents"
    agents.mkdir(exist_ok=True)
    worker = (TEMPLATES / "CALISAN.md").read_text(encoding="utf-8")
    for role in workers:
        body = (
            worker.replace("{{name}}", role.name)
            .replace("{{department}}", role.department)
            .replace("{{duty}}", role.duty)
            .replace("takım liderinden `[GÖREV #numara]` başlığıyla gelir", "takım lideri Cuba'dan gelir")
        )
        (agents / f"{role.id}.md").write_text(
            f"---\nname: {role.id}\n"
            f"description: {role.name} ({role.department}). {role.duty}\n"
            f"model: {_model_alias(models.get(role.id, ''))}\n---\n\n"
            "Cuba'nın ekibindesin. Emirleri Cuba'dan alırsın; Cuba da Çağan'ın emirlerini dinler.\n\n"
            f"{body}{office_section()}",
            encoding="utf-8",
        )
    return charter, plugin
