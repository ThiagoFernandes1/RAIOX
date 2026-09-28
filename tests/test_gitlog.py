import unittest
from datetime import datetime, timedelta, timezone

from raiox.gitlog import MARK, SEP, Commit, FileChange, parse_log, resolve_renames, split_rename, remote_name


def header(sha, author, date, subject="msg"):
    return f"{MARK}{sha}{SEP}{author}{SEP}{author.lower()}@x.com{SEP}{date}{SEP}{subject}"


class ParseLogTest(unittest.TestCase):
    def test_parses_commits_and_numstat(self):
        text = "\n".join([
            header("a1", "Ana", "2024-03-01T10:00:00-03:00", "primeiro"),
            "10\t2\tsrc/app.py",
            "-\t-\tlogo.png",
            "",
            header("b2", "Bruno", "2024-03-02T10:00:00Z", "segundo"),
            "3\t0\tREADME.md",
        ])
        commits = parse_log(text)
        self.assertEqual([c.sha for c in commits], ["a1", "b2"])
        self.assertEqual(commits[0].changes[0], FileChange("src/app.py", 10, 2, False))
        self.assertTrue(commits[0].changes[1].binary)
        self.assertEqual(commits[1].date.tzinfo, timezone.utc)
        self.assertEqual(commits[0].email, "ana@x.com")

    def test_ignores_empty_input(self):
        self.assertEqual(parse_log(""), [])


class RenameTest(unittest.TestCase):
    def test_split_rename_variants(self):
        self.assertEqual(split_rename("src/{a => b}/x.py"), ("src/a/x.py", "src/b/x.py"))
        self.assertEqual(split_rename("src/{ => core}/x.py"), ("src/x.py", "src/core/x.py"))
        self.assertEqual(split_rename("{old => new}.py"), ("old.py", "new.py"))
        self.assertEqual(split_rename("a.py => b.py"), ("a.py", "b.py"))
        self.assertEqual(split_rename("plain.py"), (None, "plain.py"))

    def test_history_follows_renames(self):
        t = datetime(2024, 1, 1, tzinfo=timezone.utc)

        def commit(i, *paths):
            return Commit(str(i), "Ana", "a@x", t + timedelta(days=i), "", [FileChange(p, 1, 0) for p in paths])

        # do mais novo ao mais antigo, como no git log
        commits = [
            commit(4, "c.py"),              # c.py atual
            commit(3, "b.py => c.py"),
            commit(2, "{a => b}.py"),
            commit(1, "a.py"),
        ]
        resolve_renames(commits)
        self.assertEqual({ch.path for c in commits for ch in c.changes}, {"c.py"})

    def test_recreated_file_is_not_merged_with_renamed_one(self):
        t = datetime(2024, 1, 1, tzinfo=timezone.utc)
        commits = [
            Commit("3", "Ana", "a@x", t, "", [FileChange("a.py", 1, 0)]),          # novo a.py
            Commit("2", "Ana", "a@x", t, "", [FileChange("a.py => b.py", 0, 0)]),
            Commit("1", "Ana", "a@x", t, "", [FileChange("a.py", 1, 0)]),          # a.py antigo, hoje b.py
        ]
        resolve_renames(commits)
        self.assertEqual([c.changes[0].path for c in commits], ["a.py", "b.py", "b.py"])


class RemoteNameTest(unittest.TestCase):
    def test_remote_name(self):
        self.assertEqual(remote_name("https://github.com/pallets/flask.git"), "flask")
        self.assertEqual(remote_name("https://github.com/pallets/flask/"), "flask")
        self.assertEqual(remote_name("git@github.com:user/repo.git"), "repo")


if __name__ == "__main__":
    unittest.main()
