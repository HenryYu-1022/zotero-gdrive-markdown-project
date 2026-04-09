from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from paper_to_markdown.common import supporting_source_info
from paper_to_markdown.pipeline import looks_like_supporting_markdown


class SupportingDetectionTests(unittest.TestCase):
    def make_temp_dir(self) -> Path:
        return Path(tempfile.mkdtemp())

    def test_supporting_markdown_matches_compact_marker(self) -> None:
        temp_dir = self.make_temp_dir()
        markdown_path = temp_dir / "paper.md"
        markdown_path.write_text("# SupportingInformation\n\nDetails", encoding="utf-8")

        self.assertTrue(looks_like_supporting_markdown(markdown_path))

    def test_supporting_source_info_does_not_require_numeric_suffix(self) -> None:
        temp_dir = self.make_temp_dir()
        primary_pdf = temp_dir / "Paper.pdf"
        supporting_pdf = temp_dir / "Paper Supporting Information.pdf"
        primary_pdf.write_bytes(b"%PDF-1.4\n")
        supporting_pdf.write_bytes(b"%PDF-1.4\n")

        self.assertEqual(supporting_source_info(supporting_pdf), (primary_pdf, 1))

    def test_supporting_source_info_keeps_numeric_suffix_behavior(self) -> None:
        temp_dir = self.make_temp_dir()
        primary_pdf = temp_dir / "Paper.pdf"
        supporting_pdf = temp_dir / "Paper_2.pdf"
        primary_pdf.write_bytes(b"%PDF-1.4\n")
        supporting_pdf.write_bytes(b"%PDF-1.4\n")

        self.assertEqual(supporting_source_info(supporting_pdf), (primary_pdf, 2))

    def test_supporting_source_info_assigns_stable_index_without_numeric_suffix(self) -> None:
        temp_dir = self.make_temp_dir()
        primary_pdf = temp_dir / "Paper.pdf"
        first_supporting_pdf = temp_dir / "Paper SI A.pdf"
        second_supporting_pdf = temp_dir / "Paper SI B.pdf"
        primary_pdf.write_bytes(b"%PDF-1.4\n")
        first_supporting_pdf.write_bytes(b"%PDF-1.4\n")
        second_supporting_pdf.write_bytes(b"%PDF-1.4\n")

        self.assertEqual(supporting_source_info(first_supporting_pdf), (primary_pdf, 1))
        self.assertEqual(supporting_source_info(second_supporting_pdf), (primary_pdf, 2))


if __name__ == "__main__":
    unittest.main()
