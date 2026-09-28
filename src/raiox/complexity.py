"""Complexidade por indentação: uma métrica que funciona para qualquer linguagem.

Código muito aninhado (ifs dentro de loops dentro de funções...) tem mais
indentação. Somar os níveis de indentação de cada linha é uma aproximação
simples e surpreendentemente boa da complexidade ciclomática, sem precisar de
um parser por linguagem (ver "Your Code as a Crime Scene", Adam Tornhill).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

MAX_BYTES = 1_000_000
TAB_WIDTH = 4


def measure(text: str) -> Dict[str, float]:
    indents = []
    for line in text.splitlines():
        if not line.strip():
            continue
        expanded = line.expandtabs(TAB_WIDTH)
        indents.append(len(expanded) - len(expanded.lstrip(" ")))

    nonzero = [i for i in indents if i > 0]
    # A menor indentação usada no arquivo define um "nível" (2 espaços, 4 espaços, tab...)
    unit = min(max(min(nonzero), 2), 8) if nonzero else TAB_WIDTH
    levels = [i / unit for i in indents]

    return {
        "loc": len(indents),
        "complexity": round(sum(levels), 1),
        "mean": round(sum(levels) / len(levels), 2) if levels else 0.0,
        "max": round(max(levels), 1) if levels else 0.0,
    }


def measure_file(path: Path) -> Optional[Dict[str, float]]:
    """Mede um arquivo; devolve None se for binário, grande demais ou ilegível."""
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8000]:
        return None
    return measure(data.decode("utf-8", "replace"))
