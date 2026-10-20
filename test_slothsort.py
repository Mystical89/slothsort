"""Tests for slothsort — no network, no model required."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import slothsort

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "slothsort.py"


def make_file(folder: Path, name: str, data: bytes = b"x") -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TempFolder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class RulesTest(unittest.TestCase):
    def test_category_by_extension(self):
        self.assertEqual(slothsort.category_for(".pdf"), "Documents")
        self.assertEqual(slothsort.category_for(".DEB"), "Installers")
        self.assertEqual(slothsort.category_for(".jpg"), "Images")
        self.assertEqual(slothsort.category_for(".zip"), "Archives")
        self.assertEqual(slothsort.category_for(".xyz"), "Misc")

    def test_sanitize_name(self):
        self.assertEqual(slothsort.sanitize_name("../evil.pdf", ".pdf"), "evil.pdf")
        self.assertEqual(slothsort.sanitize_name("a/b/c.pdf", ".pdf"), "c.pdf")
        self.assertEqual(
            slothsort.sanitize_name('name:with*chars.pdf', ".pdf"),
            "name-with-chars.pdf",
        )
        self.assertEqual(slothsort.sanitize_name("noext", ".png"), "noext.png")
        self.assertEqual(slothsort.sanitize_name("", ".pdf"), "")
        self.assertEqual(slothsort.sanitize_name("..", ".pdf"), "")

    def test_tidy_name(self):
        self.assertEqual(
            slothsort.tidy_name("Screenshot from 2026-10-18 14-22-31.png"),
            "screenshot-from-2026-10-18-14-22-31.png",
        )
        self.assertEqual(
            slothsort.tidy_name("report_final_v2 (1).docx"), "report-final-v2.docx"
        )
        self.assertEqual(slothsort.tidy_name("IMG_2041.jpg"), "IMG_2041.jpg")
        self.assertEqual(slothsort.tidy_name("invoice.pdf"), "invoice.pdf")

    def test_is_cryptic(self):
        self.assertTrue(slothsort.is_cryptic("scan_001.pdf"))
        self.assertTrue(slothsort.is_cryptic("IMG_2041.jpg"))
        self.assertTrue(slothsort.is_cryptic("Screenshot from 2026-10-18.png"))
        self.assertTrue(slothsort.is_cryptic("report_final_v2.docx"))
        self.assertFalse(slothsort.is_cryptic("invoice-march.pdf"))
        self.assertFalse(slothsort.is_cryptic("notes.md"))

    def test_unique_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            target = folder / "a.pdf"
            self.assertEqual(slothsort.unique_path(target), target)
            target.write_bytes(b"x")
            self.assertEqual(slothsort.unique_path(target).name, "a (2).pdf")
            (folder / "a (2).pdf").write_bytes(b"x")
            self.assertEqual(slothsort.unique_path(target).name, "a (3).pdf")


class CollectTest(TempFolder):
    def test_skips_hidden_symlinks_dirs_and_log(self):
        make_file(self.folder, "b.pdf")
        make_file(self.folder, "a.jpg")
        make_file(self.folder, ".hidden.pdf")
        (self.folder / "subdir").mkdir()
        (self.folder / slothsort.LOG_DIR).mkdir()
        (self.folder / "link.pdf").symlink_to(self.folder / "a.jpg")
        names = [item.name for item in slothsort.collect_files(self.folder)]
        self.assertEqual(names, ["a.jpg", "b.pdf"])

    def test_limit(self):
        for index in range(5):
            make_file(self.folder, f"f{index}.txt")
        self.assertEqual(len(slothsort.collect_files(self.folder, limit=3)), 3)


class NameReplyTest(unittest.TestCase):
    def test_plain_name(self):
        self.assertEqual(
            slothsort.clean_name_reply("electricity-bill-0926.pdf", ".pdf"),
            "electricity-bill-0926.pdf",
        )

    def test_prefixed_and_fenced(self):
        self.assertEqual(
            slothsort.clean_name_reply("name: q3-2026-report.docx", ".docx"),
            "q3-2026-report.docx",
        )
        self.assertEqual(
            slothsort.clean_name_reply("```electricity-bill-0926.pdf```", ".pdf"),
            "electricity-bill-0926.pdf",
        )

    def test_prose_rejected(self):
        self.assertEqual(
            slothsort.clean_name_reply("Sure! Here is the name I propose: bill.pdf", ".pdf"),
            "",
        )
        self.assertEqual(slothsort.clean_name_reply("", ".pdf"), "")
        self.assertEqual(slothsort.clean_name_reply("ab", ".pdf"), "")


class PlanTest(TempFolder):
    def test_offline_plan_uses_rules(self):
        make_file(self.folder, "invoice.pdf")
        make_file(self.folder, "setup.deb")
        files = slothsort.collect_files(self.folder)
        plan, used = slothsort.build_plan(files, slothsort.Options(offline=True))
        self.assertFalse(used)
        self.assertEqual([item.category for item in plan], ["Documents", "Installers"])
        self.assertTrue(all(item.new_name == item.file.name for item in plan))

    def test_model_renames_readable_cryptic_file(self):
        make_file(self.folder, "scan_001.pdf", b"%PDF-1.4 fake")
        make_file(self.folder, "IMG_2.jpg")
        files = slothsort.collect_files(self.folder)

        def fake_chat(base_url, model, api_key, messages, timeout=300):
            return "electricity-bill-0926.pdf"

        with mock.patch.object(slothsort, "model_available", return_value=True), mock.patch.object(
            slothsort, "snippet", return_value="ACME ENERGY Electricity bill"
        ):
            plan, used = slothsort.build_plan(files, slothsort.Options(), chat=fake_chat)

        self.assertTrue(used)
        by_name = {item.file.name: item for item in plan}
        self.assertEqual(by_name["scan_001.pdf"].new_name, "electricity-bill-0926.pdf")
        self.assertEqual(by_name["scan_001.pdf"].decided_by, "model")
        self.assertEqual(by_name["IMG_2.jpg"].new_name, "IMG_2.jpg")
        self.assertEqual(by_name["IMG_2.jpg"].decided_by, "rules")

    def test_model_failure_falls_back_to_rules(self):
        make_file(self.folder, "scan_001.pdf", b"%PDF-1.4 fake")
        files = slothsort.collect_files(self.folder)

        def broken_chat(*args, **kwargs):
            raise OSError("connection refused")

        with mock.patch.object(slothsort, "model_available", return_value=True), mock.patch.object(
            slothsort, "snippet", return_value="some text"
        ):
            plan, used = slothsort.build_plan(files, slothsort.Options(), chat=broken_chat)

        self.assertFalse(used)
        self.assertEqual(plan[0].new_name, "scan_001.pdf")
        self.assertEqual(plan[0].decided_by, "rules")

    def test_offline_tidies_screenshot_name(self):
        make_file(self.folder, "Screenshot from 2026-10-18 14-22-31.png")
        files = slothsort.collect_files(self.folder)
        plan, _ = slothsort.build_plan(files, slothsort.Options(offline=True))
        self.assertEqual(plan[0].new_name, "screenshot-from-2026-10-18-14-22-31.png")
        self.assertEqual(plan[0].decided_by, "tidy")


class ApplyUndoTest(TempFolder):
    def test_apply_moves_files_and_logs(self):
        make_file(self.folder, "invoice.pdf")
        make_file(self.folder, "photo.jpg")
        files = slothsort.collect_files(self.folder)
        plan, _ = slothsort.build_plan(files, slothsort.Options(offline=True))
        log_path = slothsort.apply_plan(self.folder, plan)

        self.assertTrue((self.folder / "Documents" / "invoice.pdf").is_file())
        self.assertTrue((self.folder / "Images" / "photo.jpg").is_file())
        self.assertFalse((self.folder / "invoice.pdf").exists())
        self.assertTrue(log_path.is_file())
        data = json.loads(log_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 2)

    def test_apply_dedupes_existing_target(self):
        (self.folder / "Documents").mkdir()
        make_file(self.folder / "Documents", "invoice.pdf", b"old")
        make_file(self.folder, "invoice.pdf", b"new")
        files = slothsort.collect_files(self.folder)
        plan, _ = slothsort.build_plan(files, slothsort.Options(offline=True))
        slothsort.apply_plan(self.folder, plan)
        self.assertEqual((self.folder / "Documents" / "invoice.pdf").read_bytes(), b"old")
        self.assertEqual(
            (self.folder / "Documents" / "invoice (2).pdf").read_bytes(), b"new"
        )

    def test_undo_restores_files(self):
        make_file(self.folder, "invoice.pdf")
        make_file(self.folder, "photo.jpg")
        files = slothsort.collect_files(self.folder)
        plan, _ = slothsort.build_plan(files, slothsort.Options(offline=True))
        slothsort.apply_plan(self.folder, plan)
        rc = slothsort.undo_last_run(self.folder)

        self.assertEqual(rc, 0)
        self.assertTrue((self.folder / "invoice.pdf").is_file())
        self.assertTrue((self.folder / "photo.jpg").is_file())
        self.assertFalse((self.folder / "Documents" / "invoice.pdf").exists())

    def test_undo_without_runs(self):
        self.assertEqual(slothsort.undo_last_run(self.folder), 1)


class CliTest(TempFolder):
    def test_dry_run_moves_nothing(self):
        make_file(self.folder, "invoice.pdf")
        result = run_cli(str(self.folder), "--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run", result.stdout)
        self.assertIn("Documents/", result.stdout)
        self.assertTrue((self.folder / "invoice.pdf").is_file())

    def test_json_plan(self):
        make_file(self.folder, "invoice.pdf")
        result = run_cli(str(self.folder), "--offline", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["files"][0]["category"], "Documents")

    def test_apply_then_undo(self):
        make_file(self.folder, "invoice.pdf")
        result = run_cli(str(self.folder), "--offline", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.folder / "Documents" / "invoice.pdf").is_file())

        result = run_cli(str(self.folder), "--undo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.folder / "invoice.pdf").is_file())

    def test_unreachable_model_falls_back_to_rules(self):
        make_file(self.folder, "invoice.pdf")
        result = run_cli(
            str(self.folder),
            "--base-url",
            "http://127.0.0.1:9/v1",
            "--apply",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("offline rules", result.stdout)
        self.assertTrue((self.folder / "Documents" / "invoice.pdf").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
