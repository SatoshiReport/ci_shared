"""Helpers for resolving consuming repositories that share ci_shared."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

CONFIG_CANDIDATES: tuple[str, ...] = (
    "ci_shared.config.json",
    ".ci_shared.config.json",
)
DEFAULT_CONSUMERS: tuple[str, ...] = ("api", "zeus", "kalshi", "aws")


@dataclass(frozen=True)
class ConsumingRepo:
    """Represents a repository that should receive ci_shared updates."""

    name: str
    path: Path


def _load_config(repo_root: Path) -> dict | None:
    for candidate in CONFIG_CANDIDATES:
        config_path = repo_root / candidate
        if not config_path.is_file():
            continue
        try:
            with config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _coerce_repo_entry(
    repo_root: Path,
    *,
    name: str,
    raw_path: str | None,
) -> ConsumingRepo:
    if raw_path:
        resolved = Path(raw_path).expanduser()
        if not resolved.is_absolute():
            resolved = (repo_root / raw_path).resolve()
    else:
        resolved = (repo_root.parent / name).resolve()
    return ConsumingRepo(name=name, path=resolved)


def _load_from_config(repo_root: Path, config: dict) -> List[ConsumingRepo]:
    raw_entries = config.get("consuming_repositories")
    if not isinstance(raw_entries, Sequence):
        return []

    repos: list[ConsumingRepo] = []
    for entry in raw_entries:
        if isinstance(entry, str):
            repos.append(_coerce_repo_entry(repo_root, name=entry, raw_path=None))
            continue
        if isinstance(entry, dict):
            name = entry.get("name")
            path_value = entry.get("path")
            if isinstance(name, str):
                repos.append(
                    _coerce_repo_entry(
                        repo_root,
                        name=name,
                        raw_path=path_value if isinstance(path_value, str) else None,
                    )
                )
    return repos


def _load_from_env(repo_root: Path, env_value: str) -> List[ConsumingRepo]:
    repos: list[ConsumingRepo] = []
    for token in shlex.split(env_value):
        path = Path(token).expanduser()
        name = path.name
        if not path.is_absolute():
            path = (repo_root / token).resolve()
        repos.append(ConsumingRepo(name=name, path=path))
    return repos


def load_consuming_repos(repo_root: Path | None = None) -> List[ConsumingRepo]:
    """Resolve consuming repositories from config/env/defaults."""

    repo_root = repo_root.resolve() if repo_root else Path.cwd().resolve()
    env_value = os.environ.get("CI_SHARED_PROJECTS")
    if isinstance(env_value, str):
        env_override = env_value.strip()
    else:
        env_override = ""
    if env_override:
        env_repos = _load_from_env(repo_root, env_override)
        if env_repos:
            return env_repos

    config = _load_config(repo_root)
    if config:
        config_repos = _load_from_config(repo_root, config)
        if config_repos:
            return config_repos

    return [
        _coerce_repo_entry(repo_root, name=name, raw_path=None)
        for name in DEFAULT_CONSUMERS
    ]


__all__ = ["ConsumingRepo", "load_consuming_repos", "CONFIG_CANDIDATES"]
