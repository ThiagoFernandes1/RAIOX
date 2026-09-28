"""Relatório colorido para o terminal."""

from __future__ import annotations

import os
import sys
from pathlib import PurePosixPath
from typing import List


class Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def bold(self, t): return self._wrap("1", t)
    def dim(self, t): return self._wrap("2", t)
    def red(self, t): return self._wrap("31", t)
    def yellow(self, t): return self._wrap("33", t)
    def cyan(self, t): return self._wrap("36", t)
    def green(self, t): return self._wrap("32", t)
    def title(self, t): return self._wrap("1;7", f" {t} ")


def supports_color(stream=sys.stdout) -> bool:
    if os.environ.get("NO_COLOR") or not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if os.name == "nt":
        try:  # habilita sequências ANSI no console do Windows
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            return False
    return True


def _n(v) -> str:
    return f"{int(round(v)):,}".replace(",", ".")


def _bar(value: float, width: int = 10) -> str:
    blocks = " ▏▎▍▌▋▊▉█"
    cells = max(0.0, min(1.0, value)) * width
    full = int(cells)
    rest = blocks[int((cells - full) * 8)] if full < width else ""
    return ("█" * full + rest).ljust(width)


def _short(path: str, width: int) -> str:
    if len(path) <= width:
        return path
    name = PurePosixPath(path).name
    if len(name) + 2 >= width:
        return "…" + path[-(width - 1):]
    return path[: width - len(name) - 2] + "…/" + name


def render(report: dict, top: int = 10, color: bool = False) -> str:
    st = Style(color)
    s = report["summary"]
    lines: List[str] = []
    out = lines.append

    out("")
    out(f"{st.title('RAIO-X')} {st.bold(report['repo'])}")
    out(st.dim("─" * 64))
    autores = "autor" if s["authors"] == 1 else "autores"
    ativos = "ativo" if s["active_authors"] == 1 else "ativos"
    out(f"{_n(s['commits'])} commits · {s['authors']} {autores} ({s['active_authors']} {ativos}) · "
        f"{_n(s['files'])} arquivos · {_n(s['loc'])} linhas")
    tf_names = ", ".join(s["truck_factor_authors"])
    tf = f"{s['truck_factor']}" + (f" ({tf_names})" if tf_names else "")
    tf = st.red(tf) if s["truck_factor"] <= 1 and s["authors"] > 1 else st.bold(tf)
    out(f"{s['first_commit'][:10]} → {s['last_commit'][:10]}   Bus factor: {tf}")

    out("")
    out(st.bold("DIAGNÓSTICO"))
    marks = {"alto": st.red("● alto "), "medio": st.yellow("● médio"), "info": st.cyan("● info ")}
    for i in report["insights"]:
        out(f"  {marks[i['level']]}  {st.bold(i['title'])}")
        out(f"            {st.dim(i['detail'])}")

    hs = report["hotspots"][:top]
    if hs:
        out("")
        out(st.bold("HOTSPOTS") + st.dim("  (frequência de mudança × complexidade)"))
        out(st.dim(f"  {'score':>5}  {'':10}  {'commits':>7}  {'linhas':>7}  arquivo"))
        for h in hs:
            bar = _bar(h["score"] / 100)
            bar = st.red(bar) if h["score"] >= 60 else st.yellow(bar) if h["score"] >= 30 else st.green(bar)
            out(f"  {h['score']:5.0f}  {bar}  {h['revisions']:7}  {_n(h['loc']):>7}  {_short(h['path'], 40)}")

    cp = report["coupling"][:top]
    if cp:
        out("")
        out(st.bold("ACOPLAMENTO TEMPORAL") + st.dim("  (arquivos que mudam juntos)"))
        for c in cp:
            tag = st.yellow(" oculto") if c["hidden"] else ""
            out(f"  {c['degree']:4.0%}  {c['shared']:3}x  {_short(c['a'], 28)} ⇄ {_short(c['b'], 28)}{tag}")

    authors = report["authors"][:top]
    if authors:
        out("")
        out(st.bold("AUTORES"))
        most = authors[0]["commits"] or 1
        for a in authors:
            state = "" if a["active"] else st.dim(" (inativo)")
            out(f"  {_bar(a['commits'] / most, 12)} {a['commits']:5} commits  "
                f"{a['files_owned']:4} arquivos  {a['name']}{state}")
    out("")
    return "\n".join(lines)
