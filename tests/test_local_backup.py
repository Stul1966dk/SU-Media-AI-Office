"""Tests for consistent local database backups."""

import sqlite3
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from core.local_backup import BACKUP_PREFIX, BACKUP_SUFFIX, create_backup


class LocalBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "affiliate_manager.db"
        self.backup_dir = self.root / "backups"
        connection = sqlite3.connect(self.source)
        connection.execute(
            "CREATE TABLE sales (id INTEGER PRIMARY KEY, note TEXT)"
        )
        connection.execute("INSERT INTO sales (note) VALUES ('salg-1')")
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _names(self) -> list[str]:
        pattern = f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"
        return sorted(path.name for path in self.backup_dir.glob(pattern))

    def test_backup_is_a_consistent_readable_copy(self) -> None:
        result = create_backup(self.source, self.backup_dir, keep=14)
        backup_path = result["backup_path"]

        self.assertTrue(backup_path.exists())
        connection = sqlite3.connect(backup_path)
        rows = connection.execute("SELECT note FROM sales").fetchall()
        connection.close()
        self.assertEqual([("salg-1",)], rows)

    def test_missing_source_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            create_backup(self.root / "mangler.db", self.backup_dir)

    def test_keep_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            create_backup(self.source, self.backup_dir, keep=0)

    def test_prunes_to_keep_newest(self) -> None:
        created = []
        for minute in range(5):
            result = create_backup(
                self.source,
                self.backup_dir,
                keep=3,
                now=datetime(2026, 8, 10, 12, minute, 0),
            )
            created.append(result["backup_path"].name)

        remaining = self._names()
        self.assertEqual(3, len(remaining))
        self.assertEqual(sorted(created[-3:]), remaining)

    def test_manual_backups_are_not_pruned(self) -> None:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        manual = self.backup_dir / "affiliate_manager_before_sprint3_test.db"
        manual.write_bytes(b"historik")

        for minute in range(5):
            create_backup(
                self.source,
                self.backup_dir,
                keep=2,
                now=datetime(2026, 8, 10, 12, minute, 0),
            )

        self.assertTrue(manual.exists())
        auto = [name for name in self._names() if name != manual.name]
        self.assertEqual(2, len(auto))


if __name__ == "__main__":
    unittest.main()
