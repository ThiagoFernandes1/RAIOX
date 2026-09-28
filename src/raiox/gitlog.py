"""Leitura do histórico do git: executa o git, faz o parse do log e resolve renomeações."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

SEP = "\x1f"   # separa campos do cabeçalho de cada commit
MARK = "\x1e"  # marca o início de cada commit
LOG_FORMAT = f"{MARK}%H{SEP}%aN{SEP}%aE{SEP}%aI{SEP}%s"


class GitError(RuntimeError):
    """Falha ao executar o git ou repositório inválido."""


@dataclass
class FileChange:
    path: str
    added: int
    deleted: int
    binary: bool = False


@dataclass
class Commit:
    sha: str
    author: str
    email: str
    date: datetime
    subject: str
    changes: List[FileChange] = field(default_factory=list)


def run_git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=off", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise GitError("git não encontrado no PATH") from exc
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(msg or f"git {' '.join(args)} falhou")
    return proc.stdout.decode("utf-8", "replace")


def repo_root(path: Path) -> Path:
    if not Path(path).exists():
        raise GitError(f"caminho não existe: {path}")
    try:
        top = run_git(Path(path), "rev-parse", "--show-toplevel").strip()
    except GitError as exc:
        raise GitError(f"{path} não é um repositório git") from exc
    try:
        run_git(Path(top), "rev-parse", "--verify", "HEAD")
    except GitError as exc:
        raise GitError("o repositório ainda não tem commits") from exc
    return Path(top)


def is_remote(target: str) -> bool:
    return target.startswith(("http://", "https://", "git@", "ssh://")) or (
        target.endswith(".git") and not Path(target).exists()
    )


def remote_name(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _force_remove(func, path, _exc):
    # No Windows os objetos do .git são somente leitura
    os.chmod(path, stat.S_IWRITE)
    func(path)


@contextmanager
def clone(url: str) -> Iterator[Path]:
    tmp = tempfile.mkdtemp(prefix="raiox-")
    try:
        dest = Path(tmp) / "repo"
        run_git(Path(tmp), "clone", "--quiet", "--no-tags", url, str(dest))
        yield dest
    finally:
        if sys.version_info >= (3, 12):
            shutil.rmtree(tmp, onexc=_force_remove)
        else:
            shutil.rmtree(tmp, onerror=_force_remove)


def list_files(repo: Path) -> List[str]:
    out = run_git(repo, "ls-files", "-z")
    return [p for p in out.split("\0") if p]


def read_log(repo: Path, since: Optional[str] = None) -> List[Commit]:
    args = ["log", "--numstat", "--no-merges", "-M", f"--pretty=format:{LOG_FORMAT}"]
    if since:
        args.append(f"--since={since}")
    return resolve_renames(parse_log(run_git(repo, *args)))


def _parse_date(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def parse_log(text: str) -> List[Commit]:
    """Converte a saída de `git log --numstat` (formato LOG_FORMAT) em commits, do mais novo ao mais antigo."""
    commits = []
    for block in text.split(MARK):
        block = block.strip("\n")
        if not block:
            continue
        header, _, body = block.partition("\n")
        parts = header.split(SEP, 4)
        if len(parts) != 5:
            continue
        sha, author, email, date, subject = parts
        commit = Commit(sha, author, email.lower(), _parse_date(date), subject)
        for line in body.splitlines():
            cols = line.split("\t", 2)
            if len(cols) != 3:
                continue
            added, deleted, path = cols
            binary = added == "-" or deleted == "-"
            commit.changes.append(
                FileChange(path, 0 if binary else int(added), 0 if binary else int(deleted), binary)
            )
        commits.append(commit)
    return commits


_BRACE = re.compile(r"^(.*)\{(.*) => (.*)\}(.*)$")


def split_rename(path: str) -> Tuple[Optional[str], str]:
    """`src/{a => b}/x.py` -> ('src/a/x.py', 'src/b/x.py'); caminho comum -> (None, caminho)."""
    match = _BRACE.match(path)
    if match:
        pre, old, new, post = match.groups()

        def join(mid: str) -> str:
            return (pre + mid + post).replace("//", "/").lstrip("/")

        return join(old), join(new)
    if " => " in path:
        old, new = path.split(" => ", 1)
        return old, new
    return None, path


def resolve_renames(commits: List[Commit]) -> List[Commit]:
    """Reescreve os caminhos para o nome atual de cada arquivo, seguindo as renomeações.

    Espera os commits do mais novo ao mais antigo (ordem do `git log`): quando um
    commit renomeia A -> B, todos os commits mais antigos que tocaram A passam a contar para B.
    """
    alias = {}

    def canonical(path: str) -> str:
        seen = set()
        while path in alias and path not in seen:
            seen.add(path)
            path = alias[path]
        return path

    for commit in commits:
        for change in commit.changes:
            old, new = split_rename(change.path)
            current = canonical(new)
            if old is not None and old != current:
                alias[old] = current
            change.path = current
    return commits
