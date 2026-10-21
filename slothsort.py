#!/usr/bin/env python3
"""slothsort — sort your mess while you sleep.

A local-first file tidier. Rules put files into type folders; an open-weight
model (any OpenAI-compatible endpoint, Ollama by default) reads the documents
that have meaningless names and gives them names a human would recognize.
Dry-run by default; every move is logged and can be undone.

Part of the Hacktoberfest Open-Source AI Challenge: Week 3 (Slow and Steady).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__version__ = "0.1.0"

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"  # Ollama's OpenAI-compatible API
DEFAULT_MODEL = "qwen2.5:3b"
LOG_DIR = ".slothsort"

MAX_FILES = 40      # per run: keeps a nightly pass short and predictable
SNIPPET_CHARS = 200

CATEGORIES = [
    "Documents",
    "Spreadsheets",
    "Presentations",
    "Images",
    "Screenshots",
    "Video",
    "Audio",
    "Archives",
    "Installers",
    "Code",
    "Ebooks",
    "Data",
    "Misc",
]

EXT_TO_CATEGORY = {
    # documents
    ".pdf": "Documents",
    ".doc": "Documents",
    ".docx": "Documents",
    ".odt": "Documents",
    ".rtf": "Documents",
    ".txt": "Documents",
    ".md": "Documents",
    # spreadsheets
    ".xls": "Spreadsheets",
    ".xlsx": "Spreadsheets",
    ".ods": "Spreadsheets",
    ".csv": "Spreadsheets",
    # presentations
    ".ppt": "Presentations",
    ".pptx": "Presentations",
    ".odp": "Presentations",
    ".key": "Presentations",
    # images
    ".jpg": "Images",
    ".jpeg": "Images",
    ".png": "Images",
    ".gif": "Images",
    ".webp": "Images",
    ".svg": "Images",
    ".heic": "Images",
    ".bmp": "Images",
    ".tiff": "Images",
    # video
    ".mp4": "Video",
    ".mkv": "Video",
    ".mov": "Video",
    ".webm": "Video",
    ".avi": "Video",
    # audio
    ".mp3": "Audio",
    ".flac": "Audio",
    ".wav": "Audio",
    ".ogg": "Audio",
    ".m4a": "Audio",
    ".opus": "Audio",
    # archives
    ".zip": "Archives",
    ".tar": "Archives",
    ".gz": "Archives",
    ".tgz": "Archives",
    ".zst": "Archives",
    ".7z": "Archives",
    ".rar": "Archives",
    ".bz2": "Archives",
    ".xz": "Archives",
    # installers
    ".deb": "Installers",
    ".rpm": "Installers",
    ".appimage": "Installers",
    ".exe": "Installers",
    ".msi": "Installers",
    ".dmg": "Installers",
    ".pkg": "Installers",
    ".apk": "Installers",
    # code
    ".py": "Code",
    ".js": "Code",
    ".ts": "Code",
    ".sh": "Code",
    ".json": "Code",
    ".yaml": "Code",
    ".yml": "Code",
    ".toml": "Code",
    ".rs": "Code",
    ".go": "Code",
    ".c": "Code",
    ".cpp": "Code",
    ".h": "Code",
    ".java": "Code",
    ".html": "Code",
    ".css": "Code",
    ".ipynb": "Code",
    # ebooks
    ".epub": "Ebooks",
    ".mobi": "Ebooks",
    ".fb2": "Ebooks",
    ".djvu": "Ebooks",
    ".azw3": "Ebooks",
    # data
    ".sql": "Data",
    ".db": "Data",
    ".sqlite": "Data",
    ".parquet": "Data",
    ".jsonl": "Data",
}

TEXT_EXTS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".js",
    ".ts",
    ".sh",
    ".html",
    ".css",
    ".sql",
    ".ipynb",
    ".log",
    ".ini",
    ".cfg",
}

IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".heic",
    ".svg",
}

# files we can read and therefore rename from content
READABLE_EXTS = {".pdf", ".docx", ".pptx", ".xlsx"} | TEXT_EXTS

# names that tell a human nothing
CRYPTIC = re.compile(
    r"(scan|img|dsc|photo|screenshot|untitled|document|file)[-_ ]?\d*"
    r"|final[ _-]?v?\d|\(\d+\)|copy",
    re.IGNORECASE,
)

NAME_PROMPT = (
    "Read the text and give this file a name a human would recognize. "
    "Reply with ONLY the new file name: kebab-case, 3-5 words, keep the same "
    "extension. Do not reuse the current name. No quotes, no explanation."
)


@dataclass
class FileItem:
    path: Path
    name: str
    ext: str
    size: int
    mtime: float


@dataclass
class PlanItem:
    file: FileItem
    category: str
    new_name: str
    decided_by: str  # "model", "tidy" or "rules"


@dataclass
class Options:
    base_url: str = os.environ.get("SLOTHSORT_BASE_URL", DEFAULT_BASE_URL)
    model: str = os.environ.get("SLOTHSORT_MODEL", DEFAULT_MODEL)
    api_key: str = os.environ.get("SLOTHSORT_API_KEY", "")
    offline: bool = False
    max_files: int = MAX_FILES


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def category_for(ext: str) -> str:
    return EXT_TO_CATEGORY.get(ext.lower(), "Misc")


def category_for_file(item: FileItem) -> str:
    """Type folders, plus the one name-based rule: screenshots are not photos."""
    if item.ext in IMAGE_EXTS and "screenshot" in item.name.lower():
        return "Screenshots"
    return category_for(item.ext)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:SNIPPET_CHARS]


def _pdf_text(path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-l", "2", "-q", str(path), "-"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return _clean(result.stdout) if result.returncode == 0 else ""


def _zip_text(path: Path, member: str) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read(member).decode("utf-8", "ignore")
    return _clean(re.sub(r"<[^>]+>", " ", xml))


def snippet(path: Path, ext: str) -> str:
    """First ~200 chars of a file's text, when we can get it without heavy deps."""
    try:
        if ext == ".pdf":
            return _pdf_text(path)
        if ext == ".docx":
            return _zip_text(path, "word/document.xml")
        if ext == ".pptx":
            return _zip_text(path, "ppt/slides/slide1.xml")
        if ext == ".xlsx":
            return _zip_text(path, "xl/sharedStrings.xml")
        if ext in TEXT_EXTS:
            with open(path, "rb") as handle:
                raw = handle.read(SNIPPET_CHARS * 4)
            return _clean(raw.decode("utf-8", "ignore"))
    except Exception:
        return ""
    return ""


def collect_files(root: Path, limit: int = MAX_FILES) -> list[FileItem]:
    files: list[FileItem] = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if path.name.startswith(".") or path.name == LOG_DIR:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        files.append(
            FileItem(
                path=path,
                name=path.name,
                ext=path.suffix.lower(),
                size=stat.st_size,
                mtime=stat.st_mtime,
            )
        )
        if len(files) >= limit:
            break
    return files


def sanitize_name(raw: str, ext: str) -> str:
    """Keep a model-proposed name inside the target folder and the same type."""
    raw = (raw or "").strip().strip("\"'`")
    raw = raw.replace("\\", "/").split("/")[-1]
    raw = re.sub(r'[\x00-\x1f:*?"<>|]', "-", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" .-")
    if not raw:
        return ""
    stem = Path(raw).stem.strip(" .-") or "file"
    stem = stem[:80].rstrip(" .-")
    return f"{stem}{ext}" if ext else stem


def tidy_name(name: str) -> str:
    """Deterministic cleanup: 'Screenshot from 2026-10-18 (1).png' -> kebab-case."""
    stem, ext = Path(name).stem, Path(name).suffix
    if not re.search(r"[ (]", stem):
        return name
    cleaned = re.sub(r"\s*\(\d+\)$", "", stem)
    cleaned = re.sub(r"[_\s]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    cleaned = cleaned.strip(" .-").lower()
    if not cleaned or cleaned == stem.lower():
        return name
    return f"{cleaned}{ext.lower()}"


def is_cryptic(name: str) -> bool:
    return bool(CRYPTIC.search(Path(name).stem))


def unique_path(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    for index in range(2, 1000):
        candidate = dest.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find a free name for {dest}")


def post_chat(
    base_url: str, model: str, api_key: str, messages: list[dict], timeout: int = 300
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 60,
        }
    ).encode()
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def model_available(opts: Options) -> bool:
    try:
        urllib.request.urlopen(opts.base_url.rstrip("/") + "/models", timeout=3)
        return True
    except Exception:
        return False


def clean_name_reply(reply: str, ext: str) -> str:
    """Turn a chatty model reply into a safe file name, or '' if unusable."""
    line = next((ln.strip() for ln in reply.splitlines() if ln.strip()), "")
    line = re.sub(r"^(name|filename)\s*[:=-]\s*", "", line, flags=re.IGNORECASE)
    line = line.strip("`*_ ")
    if not line or len(line) > 120 or len(line.split()) > 5:
        return ""
    name = sanitize_name(line, ext)
    stem = Path(name).stem
    if len(stem) < 3 or stem.isdigit():
        return ""
    return name


def ask_name(item: FileItem, text: str, opts: Options, chat=post_chat) -> str:
    reply = chat(
        opts.base_url,
        opts.model,
        opts.api_key,
        [
            {"role": "system", "content": NAME_PROMPT},
            {"role": "user", "content": f"current name: {item.name}\ntext: {text}"},
        ],
    )
    return clean_name_reply(reply, item.ext)


def build_plan(
    files: list[FileItem], opts: Options, chat=post_chat
) -> tuple[list[PlanItem], bool]:
    """Sort by rules; ask the model to rename documents whose names say nothing."""
    plan = [PlanItem(f, category_for_file(f), f.name, "rules") for f in files]
    use_model = not opts.offline and bool(files) and model_available(opts)
    used_model = False

    for item in plan:
        if not is_cryptic(item.file.name):
            continue
        if not use_model:
            tidied = tidy_name(item.file.name)
            if tidied != item.file.name:
                item.new_name, item.decided_by = tidied, "tidy"
            continue
        if item.file.ext not in READABLE_EXTS:
            tidied = tidy_name(item.file.name)
            if tidied != item.file.name:
                item.new_name, item.decided_by = tidied, "tidy"
            continue
        text = snippet(item.file.path, item.file.ext)
        if not text:
            continue
        try:
            proposed = ask_name(item.file, text, opts, chat)
        except Exception as exc:
            sys.stderr.write(f"slothsort: model call failed for {item.file.name} ({exc})\n")
            continue
        if proposed and proposed != item.file.name:
            item.new_name, item.decided_by = proposed, "model"
            used_model = True

    return plan, used_model


def print_plan(root: Path, plan: list[PlanItem]) -> None:
    total = sum(item.file.size for item in plan)
    print(f"slothsort · {root}  ({plural(len(plan), 'file')}, {human_size(total)})")
    print()
    by_category: dict[str, list[PlanItem]] = {}
    for item in plan:
        by_category.setdefault(item.category, []).append(item)
    for category in CATEGORIES:
        items = by_category.get(category)
        if not items:
            continue
        print(f"  {category}/")
        for item in items:
            if item.new_name != item.file.name:
                line = f"    {item.file.name}  →  {item.new_name}"
            else:
                line = f"    {item.file.name}"
            print(f"{line:<74} [{item.decided_by}]")
    renamed = sum(1 for item in plan if item.new_name != item.file.name)
    folders = len(by_category)
    print()
    print(
        f"Plan: {plural(len(plan), 'file')} → {plural(folders, 'folder')}, "
        f"{plural(renamed, 'rename')}. Dry run — nothing moved. Use --apply."
    )


def plan_as_json(root: Path, plan: list[PlanItem]) -> str:
    return json.dumps(
        {
            "root": str(root),
            "files": [
                {
                    "path": str(item.file.path),
                    "category": item.category,
                    "new_name": item.new_name,
                    "decided_by": item.decided_by,
                }
                for item in plan
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def apply_plan(root: Path, plan: list[PlanItem]) -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = root / LOG_DIR / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    created = []
    for item in plan:
        target_dir = root / item.category
        destination = unique_path(target_dir / item.new_name)
        if destination == item.file.path:
            continue
        if not target_dir.exists():
            target_dir.mkdir()
            created.append(str(target_dir.relative_to(root)))
        shutil.move(str(item.file.path), str(destination))
        entries.append(
            {
                "src": str(item.file.path.relative_to(root)),
                "dst": str(destination.relative_to(root)),
            }
        )
    log_path = run_dir / f"{run_id}.json"
    log_path.write_text(
        json.dumps(
            {
                "run": run_id,
                "root": str(root),
                "started": datetime.now().isoformat(timespec="seconds"),
                "entries": entries,
                "created": created,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return log_path


def undo_last_run(root: Path) -> int:
    run_dir = root / LOG_DIR / "runs"
    runs = (
        sorted(
            path
            for path in run_dir.glob("*.json")
            if not path.name.endswith(".undone.json")
        )
        if run_dir.is_dir()
        else []
    )
    if not runs:
        sys.stderr.write(f"slothsort: no runs to undo in {root / LOG_DIR}\n")
        return 1
    log_path = runs[-1]
    data = json.loads(log_path.read_text(encoding="utf-8"))
    restored = 0
    for entry in reversed(data.get("entries", [])):
        destination = root / entry["dst"]
        source = root / entry["src"]
        if not destination.exists():
            sys.stderr.write(f"slothsort: missing {entry['dst']}, skipped\n")
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(unique_path(source)))
        restored += 1
    if restored == 0:
        sys.stderr.write("slothsort: nothing to undo — the files are already back\n")
        return 1
    removed_dirs = 0
    for name in data.get("created", []):
        folder = root / name
        try:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                removed_dirs += 1
        except OSError:
            pass
    log_path.rename(log_path.with_suffix(".undone.json"))
    move_word = "move" if restored == 1 else "moves"
    print(f"Undone {restored} {move_word} from run {data.get('run', log_path.stem)}.")
    if removed_dirs:
        plural = "folder" if removed_dirs == 1 else "folders"
        print(f"Removed {removed_dirs} empty {plural}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slothsort",
        description="Sort a messy folder into clean ones and rename documents "
        "with an open-weight model.",
    )
    parser.add_argument("path", nargs="?", default=".", help="folder to tidy (default .)")
    parser.add_argument(
        "--apply", action="store_true", help="actually move files (default: dry run)"
    )
    parser.add_argument(
        "--undo", action="store_true", help="revert the last run in this folder"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip the model: sort by file type, clean names with rules",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"OpenAI-compatible endpoint (default {DEFAULT_BASE_URL}, "
        "or set SLOTHSORT_BASE_URL)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"model name (default {DEFAULT_MODEL}, or set SLOTHSORT_MODEL)",
    )
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    parser.add_argument(
        "--max", type=int, default=MAX_FILES, help=f"files per run (default {MAX_FILES})"
    )
    parser.add_argument("--version", action="version", version=f"slothsort {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        sys.stderr.write(f"slothsort: not a folder: {root}\n")
        return 2
    if args.undo:
        return undo_last_run(root)

    files = collect_files(root, max(1, args.max))
    if not files:
        print(f"Nothing to sort in {root}.")
        return 0

    opts = Options(
        base_url=args.base_url,
        model=args.model,
        offline=args.offline,
        max_files=args.max,
    )
    started = time.monotonic()
    plan, used_model = build_plan(files, opts)

    if args.json:
        print(plan_as_json(root, plan))
    else:
        print_plan(root, plan)

    if not args.apply:
        return 0

    log_path = apply_plan(root, plan)
    elapsed = time.monotonic() - started
    print(
        f"\nDone in {elapsed:.1f} s: {plural(len(plan), 'file')}, "
        f"{'model ' + opts.model if used_model else 'offline rules'}."
    )
    print(f"Log:  {log_path}")
    print(f"Undo: slothsort --undo {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
