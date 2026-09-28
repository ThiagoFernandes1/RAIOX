"""Interface de linha de comando."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

from . import __version__, complexity, gitlog, html_report, metrics, terminal

EPILOG = """exemplos:
  raiox                                  analisa o repositório da pasta atual
  raiox ../meu-projeto --html raiox.html --open
  raiox https://github.com/pallets/flask --since "2 years ago"
  raiox --json - | jq .summary           saída JSON para outras ferramentas
  raiox --strict                         falha (código 3) se houver achado de risco alto; útil em CI
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="raiox",
        description="Raio-X do seu repositório git: hotspots, bus factor, acoplamento oculto e conhecimento órfão.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("repo", nargs="?", default=".", help="caminho ou URL do repositório (padrão: pasta atual)")
    p.add_argument("--since", help='analisa só commits a partir de uma data, ex.: "2024-01-01" ou "1 year ago"')
    p.add_argument("--html", metavar="ARQUIVO", help="gera o relatório HTML interativo")
    p.add_argument("--open", action="store_true", help="abre o relatório HTML no navegador")
    p.add_argument("--json", metavar="ARQUIVO", help='salva o resultado completo em JSON ("-" para a saída padrão)')
    p.add_argument("--top", type=int, default=10, help="quantos itens mostrar por seção no terminal (padrão: 10)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help='ignora arquivos que casam com o padrão, ex.: --exclude "docs/*" (pode repetir)')
    p.add_argument("--min-shared", type=int, default=3,
                   help="commits em comum para considerar dois arquivos acoplados (padrão: 3)")
    p.add_argument("--min-coupling", type=float, default=0.5,
                   help="grau mínimo de acoplamento entre 0 e 1 (padrão: 0.5)")
    p.add_argument("--max-changeset", type=int, default=30,
                   help="ignora commits com mais arquivos que isso no cálculo de acoplamento (padrão: 30)")
    p.add_argument("--stale-days", type=int, default=180,
                   help="dias sem commitar para um autor ser considerado inativo (padrão: 180)")
    p.add_argument("--strict", action="store_true", help="sai com código 3 se houver algum achado de risco alto")
    p.add_argument("--no-color", action="store_true", help="desativa cores no terminal")
    p.add_argument("--version", action="version", version=f"raiox {__version__}")
    return p


@contextmanager
def open_repo(target: str) -> Iterator[tuple]:
    if gitlog.is_remote(target):
        print(f"Clonando {target}…", file=sys.stderr)
        with gitlog.clone(target) as path:
            yield path, gitlog.remote_name(target)
    else:
        root = gitlog.repo_root(Path(target))
        yield root, root.name


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _utf8_stdout()
    options = metrics.Options(
        top=args.top,
        min_shared=args.min_shared,
        min_coupling=args.min_coupling,
        max_changeset=args.max_changeset,
        stale_days=args.stale_days,
        excludes=tuple(args.exclude),
    )
    patterns = metrics.DEFAULT_EXCLUDES + options.excludes

    try:
        with open_repo(args.repo) as (root, name):
            commits = gitlog.read_log(root, since=args.since)
            files = {
                p: complexity.measure_file(root / p)
                for p in gitlog.list_files(root)
                if not metrics.is_excluded(p, patterns)
            }
            report = metrics.analyze(commits, files, repo_name=name, options=options)
    except (gitlog.GitError, ValueError) as exc:
        print(f"raiox: {exc}", file=sys.stderr)
        return 2

    if args.json == "-":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        color = not args.no_color and terminal.supports_color()
        print(terminal.render(report, top=args.top, color=color))
        if args.json:
            Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON salvo em {args.json}", file=sys.stderr)

    if args.html or args.open:
        out = Path(args.html or "raiox.html").resolve()
        out.write_text(html_report.render(report), encoding="utf-8")
        print(f"Relatório HTML salvo em {out}", file=sys.stderr)
        if args.open:
            webbrowser.open(out.as_uri())

    if args.strict and any(i["level"] == "alto" for i in report["insights"]):
        return 3
    return 0
