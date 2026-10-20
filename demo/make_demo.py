#!/usr/bin/env python3
"""Build a messy demo folder for slothsort — realistic files, no network."""

from __future__ import annotations

import base64
import gzip
import shutil
import tarfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MESSY = HERE / "messy"

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AVN//2Q=="
)


def write_pdf(path: Path, lines: list[str]) -> None:
    """A minimal one-page PDF with Helvetica text — enough for pdftotext."""
    content = "BT /F1 12 Tf 50 750 Td 16 TL\n" + "".join(
        f"({line.replace(chr(92), chr(92) * 2).replace('(', chr(92) + '(').replace(')', chr(92) + ')')}) Tj T*\n"
        for line in lines
    ) + "ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n{obj}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n"
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path.write_bytes(out.encode("latin-1"))


def write_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr("word/document.xml", document)


def main() -> None:
    if MESSY.exists():
        shutil.rmtree(MESSY)
    MESSY.mkdir(parents=True)

    write_pdf(
        MESSY / "scan_001.pdf",
        [
            "ACME ENERGY",
            "Electricity bill",
            "Account: 4417-2290",
            "Billing period: 01-30 September 2026",
            "Amount due: 84.20 BYN",
            "Due date: 2026-10-15",
        ],
    )
    write_pdf(
        MESSY / "contract_2026.pdf",
        [
            "SERVICE AGREEMENT",
            "Between Brightline Studio and Acme Energy",
            "Signed: 2026-09-12",
            "Term: 12 months, renews automatically",
            "Monthly fee: 1,200 BYN",
        ],
    )
    write_docx(
        MESSY / "report_final_v2 (1).docx",
        [
            "Q3 2026 report",
            "Revenue grew 18% quarter over quarter.",
            "Churn fell to 2.1%.",
            "Hiring plan for Q4: two engineers, one designer.",
        ],
    )
    (MESSY / "receipt_2026-10-03.txt").write_text(
        "Receipt 2026-10-03\nCoffee beans 24.50 BYN\nGrinder 189.00 BYN\n"
        "Total 213.50 BYN\nPaid by card\n",
        encoding="utf-8",
    )
    (MESSY / "notes.md").write_text(
        "# Week 3 ideas\n\n- nightly digest\n- file tidier with qwen2.5:3b\n"
        "- keep it local, no cloud\n",
        encoding="utf-8",
    )
    (MESSY / "data.csv").write_text(
        "date,orders,revenue\n2026-09-01,12,840.00\n2026-09-02,9,610.50\n"
        "2026-09-03,15,1020.00\n",
        encoding="utf-8",
    )
    (MESSY / "main.py").write_text(
        "def add(a, b):\n    return a + b\n\n\nprint(add(2, 3))\n", encoding="utf-8"
    )
    (MESSY / "Screenshot from 2026-10-18 14-22-31.png").write_bytes(PNG)
    (MESSY / "IMG_2041.jpg").write_bytes(JPEG)
    (MESSY / "photo_2026-09-30.jpg").write_bytes(JPEG)
    (MESSY / "song.mp3").write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 512)
    with zipfile.ZipFile(MESSY / "backup.zip", "w") as archive:
        archive.writestr("notes.txt", "old notes\n")
    with tarfile.open(MESSY / "archive_old.tar.gz", "w:gz") as archive:
        archive.add(MESSY / "notes.md", arcname="notes.md")
    (MESSY / "Qoder-linux-amd64.deb").write_bytes(b"!<arch>\ndebian-binary   ")

    print(f"demo folder: {MESSY}")
    for path in sorted(MESSY.iterdir()):
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
