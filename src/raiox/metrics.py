"""Análise do histórico: hotspots, donos do código, bus factor, acoplamento temporal e diagnóstico."""

from __future__ import annotations

import fnmatch
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .gitlog import Commit

DEFAULT_EXCLUDES = (
    "*.lock", "package-lock.json", "pnpm-lock.yaml", "go.sum", "*.min.js", "*.min.css",
    "*.map", "*.svg", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.webp", "*.pdf",
    "*.woff", "*.woff2", "*.ttf", "*.eot", "*.db", "*.sqlite", "*.sqlite3", "*.zip",
)

# Um autor é considerado "dono" de um arquivo se escreveu ao menos esta fração dele
OWNER_SHARE = 0.25


@dataclass
class Options:
    top: int = 10
    min_shared: int = 3          # commits em comum para considerar um acoplamento
    min_coupling: float = 0.5    # grau mínimo de acoplamento (0..1)
    max_changeset: int = 30      # commits maiores que isso (refactors em massa) não contam para acoplamento
    stale_days: int = 180        # autor sem commits há mais tempo que isso é considerado inativo
    excludes: Sequence[str] = ()


@dataclass
class FileStats:
    path: str
    revisions: int = 0
    added: int = 0
    deleted: int = 0
    added_by: Counter = field(default_factory=Counter)
    commits_by: Counter = field(default_factory=Counter)
    first: Optional[datetime] = None
    last: Optional[datetime] = None

    def ownership(self) -> Dict[str, float]:
        weights = self.added_by if sum(self.added_by.values()) else self.commits_by
        total = sum(weights.values())
        return {a: w / total for a, w in weights.items()} if total else {}


@dataclass
class AuthorStats:
    name: str
    commits: int = 0
    added: int = 0
    deleted: int = 0
    first: Optional[datetime] = None
    last: Optional[datetime] = None


def is_excluded(path: str, patterns: Iterable[str]) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in patterns)


def is_test(path: str) -> bool:
    p = PurePosixPath(path.lower())
    stem = p.name.split(".")[0]
    if stem.startswith("test_") or stem.endswith(("_test", "_spec")) or stem in ("test", "tests"):
        return True
    if ".test." in p.name or ".spec." in p.name:
        return True
    return any(part in ("test", "tests", "__tests__", "spec", "specs") for part in p.parts[:-1])


def truck_factor(owners: Dict[str, Set[str]]) -> Tuple[int, List[str]]:
    """Algoritmo guloso de Avelino et al.: remove o autor que é dono de mais arquivos
    até que mais da metade dos arquivos fique sem nenhum dono."""
    remaining = {path: set(o) for path, o in owners.items()}
    total = len(remaining)
    removed: List[str] = []
    while total:
        orphans = sum(1 for o in remaining.values() if not o)
        if orphans > total / 2:
            break
        counts = Counter(a for o in remaining.values() for a in o)
        if not counts:
            break
        top = max(counts, key=lambda a: (counts[a], a))
        removed.append(top)
        for o in remaining.values():
            o.discard(top)
    return len(removed), removed


def _week(d: datetime):
    day = d.date()
    return day - timedelta(days=day.weekday())


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _fmt(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def analyze(
    commits: List[Commit],
    files: Dict[str, Optional[Dict[str, float]]],
    repo_name: str = "",
    options: Optional[Options] = None,
) -> dict:
    """`files` mapeia cada arquivo rastreado hoje para sua medição de complexidade (ou None se binário)."""
    opt = options or Options()
    patterns = tuple(DEFAULT_EXCLUDES) + tuple(opt.excludes)
    tracked = {p: m for p, m in files.items() if not is_excluded(p, patterns)}
    commits = sorted(commits, key=lambda c: c.date)
    if not commits:
        raise ValueError("nenhum commit encontrado no período analisado")
    reference = commits[-1].date

    stats: Dict[str, FileStats] = {}
    authors: Dict[str, AuthorStats] = {}
    changesets: List[List[str]] = []

    for c in commits:
        author = authors.setdefault(c.author, AuthorStats(c.author))
        author.commits += 1
        author.first = author.first or c.date
        author.last = c.date

        per_file: Dict[str, Tuple[int, int]] = {}
        for ch in c.changes:
            author.added += ch.added
            author.deleted += ch.deleted
            if ch.path in tracked:
                a, d = per_file.get(ch.path, (0, 0))
                per_file[ch.path] = (a + ch.added, d + ch.deleted)

        for path, (added, deleted) in per_file.items():
            fs = stats.setdefault(path, FileStats(path))
            fs.revisions += 1
            fs.added += added
            fs.deleted += deleted
            fs.added_by[c.author] += added
            fs.commits_by[c.author] += 1
            fs.first = fs.first or c.date
            fs.last = c.date
        if per_file:
            changesets.append(sorted(per_file))

    active_cutoff = reference - timedelta(days=opt.stale_days)
    is_active = {name: a.last >= active_cutoff for name, a in authors.items()}

    # --- Hotspots: arquivos que mudam muito E são complexos -------------------------
    measured = {p: tracked[p] for p in stats if tracked.get(p) and tracked[p]["loc"] > 0}
    max_rev = max((stats[p].revisions for p in measured), default=0) or 1
    max_cx = max((m["complexity"] for m in measured.values()), default=0) or 1

    hotspots = []
    owners: Dict[str, Set[str]] = {}
    for path, m in measured.items():
        fs = stats[path]
        share = fs.ownership()
        owner = max(share, key=lambda a: (share[a], a))
        owners[path] = {a for a, s in share.items() if s >= OWNER_SHARE} | {owner}
        score = math.sqrt((fs.revisions / max_rev) * (m["complexity"] / max_cx)) * 100
        hotspots.append({
            "path": path,
            "revisions": fs.revisions,
            "loc": int(m["loc"]),
            "complexity": m["complexity"],
            "max_depth": m["max"],
            "churn": fs.added + fs.deleted,
            "score": round(score, 1),
            "owner": owner,
            "owner_share": round(share[owner], 3),
            "owner_active": is_active[owner],
            "authors": len(fs.commits_by),
            "age_days": (reference - fs.last).days,
        })
    hotspots.sort(key=lambda h: (-h["score"], h["path"]))

    # --- Bus factor ---------------------------------------------------------------
    tf, tf_authors = truck_factor(owners)

    # --- Conhecimento órfão: dono principal não está mais ativo -------------------
    orphaned = sorted(
        (h for h in hotspots if not h["owner_active"]),
        key=lambda h: (-h["complexity"], h["path"]),
    )

    # --- Acoplamento temporal ----------------------------------------------------
    pairs: Counter = Counter()
    for cs in changesets:
        if 2 <= len(cs) <= opt.max_changeset:
            pairs.update(combinations(cs, 2))
    coupling = []
    for (a, b), shared in pairs.items():
        if shared < opt.min_shared:
            continue
        degree = shared / ((stats[a].revisions + stats[b].revisions) / 2)
        if degree < opt.min_coupling:
            continue
        cross = str(PurePosixPath(a).parent) != str(PurePosixPath(b).parent)
        coupling.append({
            "a": a,
            "b": b,
            "shared": shared,
            "degree": round(degree, 3),
            "cross_dir": cross,
            "hidden": cross and not (is_test(a) or is_test(b)),
        })
    coupling.sort(key=lambda c: (-c["degree"], -c["shared"], c["a"], c["b"]))

    # --- Linha do tempo semanal (até 2 anos) ---------------------------------------
    weekly = Counter(_week(c.date) for c in commits)
    last_week = _week(reference)
    start = max(_week(commits[0].date), last_week - timedelta(weeks=103))
    timeline = []
    wk = start
    while wk <= last_week:
        timeline.append({"week": wk.isoformat(), "commits": weekly.get(wk, 0)})
        wk += timedelta(weeks=1)

    # --- Idade do código ----------------------------------------------------------
    buckets = [("< 1 mês", 30), ("1–6 meses", 182), ("6–12 meses", 365), ("> 1 ano", None)]
    age = [{"bucket": b, "files": 0, "loc": 0} for b, _ in buckets]
    for h in hotspots:
        for i, (_, limit) in enumerate(buckets):
            if limit is None or h["age_days"] < limit:
                age[i]["files"] += 1
                age[i]["loc"] += h["loc"]
                break

    # --- Autores ------------------------------------------------------------------
    owned = Counter(h["owner"] for h in hotspots)
    author_list = sorted(
        (
            {
                "name": a.name,
                "commits": a.commits,
                "added": a.added,
                "deleted": a.deleted,
                "files_owned": owned.get(a.name, 0),
                "first": _iso(a.first),
                "last": _iso(a.last),
                "active": is_active[a.name],
            }
            for a in authors.values()
        ),
        key=lambda a: (-a["commits"], a["name"]),
    )

    total_loc = sum(h["loc"] for h in hotspots)
    report = {
        "repo": repo_name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "options": {
            "min_shared": opt.min_shared,
            "min_coupling": opt.min_coupling,
            "max_changeset": opt.max_changeset,
            "stale_days": opt.stale_days,
        },
        "summary": {
            "commits": len(commits),
            "authors": len(authors),
            "active_authors": sum(is_active.values()),
            "files": len(hotspots),
            "loc": total_loc,
            "first_commit": _iso(commits[0].date),
            "last_commit": _iso(reference),
            "truck_factor": tf,
            "truck_factor_authors": tf_authors,
        },
        "hotspots": hotspots,
        "coupling": coupling,
        "orphaned": orphaned,
        "authors": author_list,
        "timeline": timeline,
        "age": age,
    }
    report["insights"] = diagnose(report)
    return report


LEVEL_ORDER = {"alto": 0, "medio": 1, "info": 2}


def diagnose(report: dict) -> List[dict]:
    """Transforma as métricas em achados legíveis, do mais grave ao mais leve."""
    s = report["summary"]
    hotspots = report["hotspots"]
    stale_days = report["options"]["stale_days"]
    out: List[dict] = []

    def add(level: str, title: str, detail: str) -> None:
        out.append({"level": level, "title": title, "detail": detail})

    tf, names = s["truck_factor"], s["truck_factor_authors"]
    if s["authors"] == 1:
        add("info", "Projeto de um autor só",
            f"Todo o conhecimento do código está com {report['authors'][0]['name']}. "
            "Documentação e testes são o que protege o projeto se outra pessoa precisar assumir.")
    elif tf <= 2 and names:
        who = " e ".join(names)
        add("alto" if tf == 1 else "medio", f"Bus factor {tf}",
            f"Se {who} {'sair' if tf == 1 else 'saírem'} do projeto, mais da metade dos arquivos "
            "fica sem ninguém que conheça bem o código.")

    if hotspots and hotspots[0]["score"] >= 50 and hotspots[0]["revisions"] >= 3:
        h = hotspots[0]
        add("alto", f"Principal hotspot: {h['path']}",
            f"Mudou em {h['revisions']} commits e tem {_fmt(h['loc'])} linhas com complexidade "
            f"{_fmt(h['complexity'])} (aninhamento máx. {h['max_depth']:g}). "
            "É o melhor candidato a refatoração: arquivos assim concentram a maior parte dos bugs.")

    if len(hotspots) >= 10:
        by_rev = sorted((h["revisions"] for h in hotspots), reverse=True)
        k = max(1, math.ceil(len(by_rev) * 0.1))
        share = sum(by_rev[:k]) / sum(by_rev)
        if share >= 0.3:
            add("medio", "Mudanças concentradas",
                f"{k} arquivos (10% do total) recebem {share:.0%} de todas as alterações. "
                "Vale investir em testes justamente neles.")

    hidden = [c for c in report["coupling"] if c["hidden"]]
    if hidden:
        c = hidden[0]
        extra = f" Há outros {len(hidden) - 1} pares assim." if len(hidden) > 1 else ""
        add("medio", f"Acoplamento oculto: {PurePosixPath(c['a']).name} ⇄ {PurePosixPath(c['b']).name}",
            f"{c['a']} e {c['b']} mudaram juntos em {c['shared']} commits ({c['degree']:.0%} das vezes), "
            f"mas ficam em pastas diferentes. Indica uma dependência implícita que ninguém vê no código.{extra}")

    orphaned = report["orphaned"]
    if orphaned and s["authors"] > 1:
        loc = sum(h["loc"] for h in orphaned)
        ex = ", ".join(h["path"] for h in orphaned[:3])
        add("medio", f"Conhecimento órfão em {len(orphaned)} arquivos",
            f"{_fmt(loc)} linhas têm como principal autor alguém sem commits há mais de "
            f"{stale_days} dias. Exemplos: {ex}.")

    old = next((a for a in report["age"] if a["bucket"] == "> 1 ano"), None)
    if old and s["loc"] and old["loc"] / s["loc"] >= 0.3:
        add("info", f"{old['loc'] / s['loc']:.0%} do código não muda há mais de 1 ano",
            "Código estável é bom sinal, desde que ainda seja usado. Confira se não há código morto.")

    authors = report["authors"]
    if len(authors) >= 2 and authors[0]["commits"] / s["commits"] >= 0.7:
        add("info", f"{authors[0]['name']} fez {authors[0]['commits'] / s['commits']:.0%} dos commits",
            "O ritmo do projeto depende muito de uma pessoa só.")

    if not out:
        add("info", "Nada alarmante", "Nenhum sinal forte de risco foi encontrado no histórico.")

    out.sort(key=lambda i: LEVEL_ORDER[i["level"]])
    return out
