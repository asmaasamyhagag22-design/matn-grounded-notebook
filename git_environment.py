"""Isolate Git commands that explicitly target a repository from hook-local state."""
from __future__ import annotations

import os
from collections.abc import Mapping

# Identity is safe to inherit; repository selection, config, object/index paths,
# execution controls and every unknown future GIT_* variable are discarded.
GIT_ENV_ALLOWLIST = frozenset({
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
})


def git_environment(overrides: Mapping[str, str] | None = None, *,
                    source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a fresh environment; callers must also pass the target ``cwd``."""
    values = os.environ if source is None else source
    env = {key: value for key, value in values.items()
           if not key.upper().startswith("GIT_") or key in GIT_ENV_ALLOWLIST}
    for key, value in (overrides or {}).items():
        if key.upper().startswith("GIT_") and key not in GIT_ENV_ALLOWLIST:
            raise ValueError(f"Git environment override is not allowlisted: {key}")
        env[key] = value
    return env


def repository_config_paths(root):
    """Resolve common/worktree config paths without trusting inherited Git state."""
    from pathlib import Path
    root = Path(root).resolve()
    marker = root / ".git"
    if marker.is_dir():
        git_dir = marker
    else:
        text = marker.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir: "):
            raise ValueError(f"Invalid Git worktree marker: {marker}")
        git_dir = (root / text.removeprefix("gitdir: ")).resolve()
    common = git_dir
    if (git_dir / "commondir").is_file():
        common = (git_dir / (git_dir / "commondir").read_text(encoding="utf-8").strip()).resolve()
    paths = {common / "config"}
    if (git_dir / "config.worktree").is_file():
        paths.add(git_dir / "config.worktree")
    return sorted(paths)


def core_bare_snapshot(paths):
    """Read only core.bare, avoiding a Git subprocess that could be redirected."""
    import configparser
    values = {}
    for path in paths:
        config = configparser.RawConfigParser(strict=False)
        try:
            with path.open(encoding="utf-8") as stream:
                config.read_file(stream)
            values[path] = config.getboolean("core", "bare", fallback=False)
        except configparser.Error as exc:
            raise ValueError(f"Invalid Git config {path}: {exc}") from exc
    return values
