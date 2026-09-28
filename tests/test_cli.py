"""Testes ponta a ponta: cria um repositório git de verdade e roda o raiox nele."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from raiox.cli import main


@unittest.skipUnless(shutil.which("git"), "git não instalado")
class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "projeto"
        self.repo.mkdir()
        self.day = 0
        self.git("init", "-q")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, author="Ana"):
        env = dict(os.environ)
        date = f"2024-01-{1 + self.day % 28:02d}T12:00:00+00:00"
        env.update({
            "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": f"{author.lower()}@x.com",
            "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": f"{author.lower()}@x.com",
            "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
        })
        subprocess.run(["git", "-C", str(self.repo), "-c", "commit.gpgsign=false", *args],
                       check=True, capture_output=True, env=env)

    def commit(self, author, files):
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"muda {', '.join(files)}", author=author)
        self.day += 1

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(self.repo), "--no-color", *args])
        return code, out.getvalue(), err.getvalue()

    def build_history(self):
        body = "def f(x):\n    if x:\n        for i in x:\n            print(i)\n"
        for i in range(6):
            self.commit("Ana", {"src/core.py": body * (i + 1), "web/view.js": f"// v{i}\n"})
        self.commit("Bia", {"README.md": "# Projeto\n"})
        self.git("mv", "src/core.py", "src/engine.py")
        self.git("commit", "-q", "-m", "renomeia")
        self.commit("Ana", {"src/engine.py": body * 8})

    def test_terminal_json_and_html(self):
        self.build_history()
        html = Path(self.tmp.name) / "r.html"
        data = Path(self.tmp.name) / "r.json"
        code, out, err = self.run_cli("--html", str(html), "--json", str(data))

        self.assertEqual(code, 0, err)
        self.assertIn("RAIO-X", out)
        self.assertIn("src/engine.py", out)

        report = json.loads(data.read_text(encoding="utf-8"))
        top = report["hotspots"][0]
        self.assertEqual(top["path"], "src/engine.py")
        self.assertEqual(top["revisions"], 8)  # 6 como core.py + rename + 1 como engine.py
        self.assertNotIn("src/core.py", [h["path"] for h in report["hotspots"]])
        self.assertEqual(report["summary"]["authors"], 2)

        page = html.read_text(encoding="utf-8")
        self.assertIn("<title>Raio-X · projeto</title>", page)
        self.assertNotIn("__DATA__", page)

    def test_json_to_stdout(self):
        self.build_history()
        code, out, _ = self.run_cli("--json", "-")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["repo"], "projeto")

    def test_strict_mode(self):
        self.build_history()
        code, _, _ = self.run_cli("--strict")
        self.assertEqual(code, 3)  # core.py/engine.py é um hotspot de risco alto

    def test_errors(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("não tem commits", err)

        code, _, err = self.run_cli_path(Path(self.tmp.name) / "nao-existe")
        self.assertEqual(code, 2)

    def run_cli_path(self, path):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            return main([str(path)]), None, err.getvalue()


if __name__ == "__main__":
    unittest.main()
