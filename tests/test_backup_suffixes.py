"""
One list of backup file endings, three scripts (12.10.2026).

container2backup.py wrote SQL-only backups as .sql.zst / .sql.gz and
encrypted ones as .7z.gpg, but its own retention, server-readiness.py and
ownerp_state.py knew only .7z/.zip/.tar.gz/.tar.zst: those archives were
never deleted and never counted ("no archive found" on a server with a
fresh backup every day).

Run from the repository root:

    python3 -m unittest tests.test_backup_suffixes -v
"""

import os
import re
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


def _read(name):
    with open(os.path.join(SCRIPTS, name), encoding="utf-8") as handle:
        return handle.read()


def _tuple(source, name):
    match = re.search(rf"^{name} = \(([^)]*)\)", source, re.MULTILINE)
    return tuple(re.findall(r'"([^"]+)"', match.group(1))) if match else None


class BackupSuffixesTest(unittest.TestCase):

    def setUp(self):
        self.backup = _read("container2backup.py")
        self.suffixes = _tuple(self.backup, "BACKUP_SUFFIXES")

    def test_all_three_scripts_agree(self):
        self.assertIsNotNone(self.suffixes)
        self.assertEqual(_tuple(_read("server-readiness.py"), "BACKUP_ARCHIVE_SUFFIXES"), self.suffixes)
        self.assertEqual(_tuple(_read("ownerp_state.py"), "BACKUP_SUFFIXES"), self.suffixes)

    def test_every_written_ending_is_known(self):
        written = set(re.findall(r'output_file = f"\{output_file_base\}(\.[\w.]+)"', self.backup))
        self.assertIn(".sql.zst", written)          # the pattern still finds them
        if "'.gpg'" in self.backup or "+ '.gpg'" in self.backup:
            written |= {f"{ending}.gpg" for ending in written if ending == ".7z"}
        for ending in sorted(written):
            self.assertIn(ending, self.suffixes, ending)

    def test_retention_uses_the_list(self):
        self.assertNotIn("extensions = ['", self.backup)
        self.assertEqual(self.backup.count("extensions = BACKUP_SUFFIXES"), 2)


if __name__ == "__main__":
    unittest.main()
