"""
Multi-project registry.

Allows the Orchestrator to manage multiple GitHub repos from one bot instance.
Projects are stored in projects.yaml next to decisions/.

Schema:
  projects:
    - id: tower              # short slug, used in commands
      name: Tower of Babel
      github_repo: skillariatop/Tower_of_Babel
      decisions_dir: ./decisions
      active: true
    - id: my-other-project
      name: My Other Project
      github_repo: skillariatop/Other
      decisions_dir: ./projects/other/decisions
      active: true
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from bot.config import settings

log = logging.getLogger("tower.projects")

PROJECTS_FILE = Path("projects.yaml")


@dataclass
class Project:
    id: str
    name: str
    github_repo: str
    decisions_dir: Path
    active: bool = True


_registry: dict[str, Project] = {}


def load_registry() -> dict[str, Project]:
    global _registry
    if not PROJECTS_FILE.exists():
        # Default: just this repo
        default = Project(
            id="tower",
            name="Tower of Babel",
            github_repo=settings.github_repo,
            decisions_dir=settings.decisions_dir,
        )
        _registry = {"tower": default}
        return _registry

    with open(PROJECTS_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    _registry = {}
    for p in data.get("projects", []):
        proj = Project(
            id=p["id"],
            name=p["name"],
            github_repo=p["github_repo"],
            decisions_dir=Path(p.get("decisions_dir", f"./projects/{p['id']}/decisions")),
            active=p.get("active", True),
        )
        _registry[proj.id] = proj
        log.info("Loaded project: %s (%s)", proj.id, proj.github_repo)

    return _registry


def get_project(project_id: str) -> Optional[Project]:
    return _registry.get(project_id)


def list_projects() -> list[Project]:
    return [p for p in _registry.values() if p.active]


def register_project(id: str, name: str, github_repo: str) -> Project:
    proj = Project(
        id=id,
        name=name,
        github_repo=github_repo,
        decisions_dir=Path(f"./projects/{id}/decisions"),
    )
    proj.decisions_dir.mkdir(parents=True, exist_ok=True)
    _registry[id] = proj
    _save_registry()
    log.info("Registered new project: %s (%s)", id, github_repo)
    return proj


def _save_registry() -> None:
    data = {
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "github_repo": p.github_repo,
                "decisions_dir": str(p.decisions_dir),
                "active": p.active,
            }
            for p in _registry.values()
        ]
    }
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)


# Load on import
load_registry()
