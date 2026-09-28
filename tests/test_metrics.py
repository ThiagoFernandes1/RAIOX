import unittest
from datetime import datetime, timedelta, timezone

from raiox.complexity import measure
from raiox.gitlog import Commit, FileChange
from raiox.metrics import Options, analyze, is_excluded, is_test, truck_factor

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def commit(day, author, *changes):
    return Commit(f"{day}{author}", author, f"{author}@x", T0 + timedelta(days=day), "",
                  [FileChange(p, a, 0) for p, a in changes])


def cx(loc, complexity):
    return {"loc": loc, "complexity": complexity, "mean": complexity / loc, "max": 3}


class ComplexityTest(unittest.TestCase):
    def test_counts_indentation_levels(self):
        src = "def f(x):\n    if x:\n        return 1\n\n    return 0\n"
        m = measure(src)
        self.assertEqual(m["loc"], 4)
        self.assertEqual(m["complexity"], 4.0)   # 0 + 1 + 2 + 1
        self.assertEqual(m["max"], 2.0)

    def test_detects_two_space_indent_and_tabs(self):
        self.assertEqual(measure("a\n  b\n    c\n")["complexity"], 3.0)
        self.assertEqual(measure("a\n\tb\n\t\tc\n")["complexity"], 3.0)

    def test_empty(self):
        self.assertEqual(measure("")["loc"], 0)


class HelpersTest(unittest.TestCase):
    def test_truck_factor(self):
        owners = {"a": {"ana"}, "b": {"ana"}, "e": {"ana"}, "c": {"ana", "bia"}, "d": {"bia"}}
        self.assertEqual(truck_factor(owners), (1, ["ana"]))
        owners = {"a": {"ana"}, "b": {"bia"}, "c": {"caio"}, "d": {"dani"}}
        tf, _ = truck_factor(owners)
        self.assertEqual(tf, 3)
        self.assertEqual(truck_factor({}), (0, []))

    def test_is_test(self):
        for p in ("tests/x.py", "src/test_x.py", "app/x_test.go", "web/x.spec.ts", "a/__tests__/b.js"):
            self.assertTrue(is_test(p), p)
        for p in ("src/latest.py", "src/contest/x.py"):
            self.assertFalse(is_test(p), p)

    def test_excludes(self):
        self.assertTrue(is_excluded("web/package-lock.json", ["package-lock.json"]))
        self.assertTrue(is_excluded("docs/a.md", ["docs/*"]))
        self.assertFalse(is_excluded("src/a.py", ["docs/*"]))


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        commits = []
        # core.py muda muito e é complexo; config.json muda muito mas é trivial
        for d in range(10):
            commits.append(commit(d, "ana", ("src/core.py", 10), ("src/config.json", 1)))
        # api/routes.py e web/form.js sempre mudam juntos (acoplamento oculto)
        for d in range(10, 15):
            commits.append(commit(d, "bia", ("api/routes.py", 5), ("web/form.js", 5)))
        commits.append(commit(15, "bia", ("src/util.py", 3)))
        # caio fez o legacy.py há muito tempo e sumiu
        commits.insert(0, commit(-400, "caio", ("src/legacy.py", 200)))
        self.commits = commits
        self.files = {
            "src/core.py": cx(300, 900),
            "src/config.json": cx(20, 10),
            "api/routes.py": cx(100, 150),
            "web/form.js": cx(80, 120),
            "src/util.py": cx(30, 20),
            "src/legacy.py": cx(200, 300),
            "logo.png": None,
            "deleted_later.py": cx(10, 5),
        }
        self.report = analyze(self.commits, self.files, "demo", Options(min_shared=3))

    def test_summary(self):
        s = self.report["summary"]
        self.assertEqual(s["commits"], 17)
        self.assertEqual(s["authors"], 3)
        self.assertEqual(s["active_authors"], 2)
        self.assertEqual(s["files"], 6)  # sem binário e sem arquivo sem histórico

    def test_hotspot_ranking(self):
        top = self.report["hotspots"][0]
        self.assertEqual(top["path"], "src/core.py")
        self.assertEqual(top["score"], 100.0)
        scores = {h["path"]: h["score"] for h in self.report["hotspots"]}
        self.assertLess(scores["src/config.json"], scores["api/routes.py"])

    def test_hidden_coupling(self):
        pairs = {(c["a"], c["b"]): c for c in self.report["coupling"]}
        pair = pairs[("api/routes.py", "web/form.js")]
        self.assertEqual(pair["shared"], 5)
        self.assertEqual(pair["degree"], 1.0)
        self.assertTrue(pair["hidden"])
        self.assertFalse(pairs[("src/config.json", "src/core.py")]["hidden"])

    def test_orphaned_knowledge(self):
        self.assertEqual([h["path"] for h in self.report["orphaned"]], ["src/legacy.py"])
        self.assertEqual(self.report["orphaned"][0]["owner"], "caio")

    def test_insights(self):
        titles = " | ".join(i["title"] for i in self.report["insights"])
        self.assertIn("Principal hotspot: src/core.py", titles)
        self.assertIn("Acoplamento oculto", titles)
        self.assertIn("Conhecimento órfão em 1 arquivos", titles)
        levels = [i["level"] for i in self.report["insights"]]
        self.assertEqual(levels, sorted(levels, key=["alto", "medio", "info"].index))

    def test_max_changeset_ignores_mass_commits(self):
        big = [commit(20 + i, "ana", *[(f"f{j}.py", 1) for j in range(40)]) for i in range(5)]
        files = {f"f{j}.py": cx(10, 5) for j in range(40)}
        report = analyze(big, files, "x", Options(max_changeset=30))
        self.assertEqual(report["coupling"], [])

    def test_timeline_is_continuous(self):
        weeks = [t["week"] for t in self.report["timeline"]]
        self.assertEqual(len(weeks), len(set(weeks)))
        self.assertEqual(sum(t["commits"] for t in self.report["timeline"]), 17)

    def test_timeline_is_capped_at_two_years(self):
        commits = [commit(-1000, "ana", ("src/core.py", 1)), commit(0, "ana", ("src/core.py", 1))]
        report = analyze(commits, {"src/core.py": cx(10, 5)}, "x")
        self.assertEqual(len(report["timeline"]), 104)

    def test_no_commits(self):
        with self.assertRaises(ValueError):
            analyze([], {}, "x")


if __name__ == "__main__":
    unittest.main()
