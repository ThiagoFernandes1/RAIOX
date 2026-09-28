"""Gera o relatório HTML: um único arquivo, sem dependências, que abre em qualquer navegador."""

from __future__ import annotations

import html
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.html")


def render(report: dict) -> str:
    data = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("__TITLE__", html.escape(report["repo"]))
    return page.replace("__DATA__", data)
