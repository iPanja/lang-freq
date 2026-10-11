#!/usr/bin/env python3
"""Build a Spanish word-family frequency list from one or more EPUB files.

Uses the es_allforms.csv file from doozan/spanish_data when supplied. The
observed token and family lemma are both retained, so ambiguous mappings and
unrecognized forms remain reviewable.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path


TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
SKIP_TAGS = {"script", "style", "svg", "head", "title", "noscript"}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in SKIP_TAGS:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def extract_epub(path: Path) -> str:
    pieces: list[str] = []
    try:
        with zipfile.ZipFile(path) as book:
            for name in book.namelist():
                if Path(name).suffix.lower() not in {".xhtml", ".html", ".htm"}:
                    continue
                parser = TextExtractor()
                parser.feed(book.read(name).decode("utf-8", errors="replace"))
                pieces.extend(parser.parts)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"cannot read EPUB {path}: {exc}") from exc
    return " ".join(pieces)


def read_lemmas(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Map lowercase surface form to (lemma, POS) candidates."""
    mapping: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3:
                continue
            form, pos = row[0].strip().lower(), row[1].strip()
            for lemma in row[2:]:
                lemma = lemma.strip().lower()
                if lemma and (lemma, pos) not in mapping[form]:
                    mapping[form].append((lemma, pos))
    return mapping


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("epub", nargs="+", type=Path, help="EPUB file(s) to analyze")
    ap.add_argument("-o", "--output", type=Path, default=Path("frequency.csv"),
                    help="output CSV path (default: frequency.csv)")
    ap.add_argument("--forms", type=Path,
                    help="path to spanish_data/es_allforms.csv for lemmatization")
    args = ap.parse_args()

    counts: Counter[str] = Counter()
    try:
        for path in args.epub:
            text = extract_epub(path)
            counts.update(m.group(0).lower() for m in TOKEN_RE.finditer(text))
        lemmas = read_lemmas(args.forms) if args.forms else {}
        families: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for form, count in counts.items():
            candidates = lemmas.get(form, [])
            if candidates:
                # Keep distinct homographic families visible; don't pretend the
                # form alone disambiguates their meaning.
                for lemma, pos in candidates:
                    families[(lemma, pos)][form] += count
            else:
                families[(form, "")][form] += count

        rows = []
        for (lemma, pos), forms in families.items():
            rows.append((sum(forms.values()), lemma, pos, forms))
        rows.sort(key=lambda row: (-row[0], row[1], row[2]))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["rank", "lemma", "part_of_speech", "count", "observed_forms"])
            for rank, (count, lemma, pos, forms) in enumerate(rows, 1):
                observed = "; ".join(f"{form} ({n})" for form, n in
                                      sorted(forms.items(), key=lambda kv: (-kv[1], kv[0])))
                writer.writerow([rank, lemma, pos, count, observed])
    except (OSError, ValueError, csv.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {len(rows)} word families from {sum(counts.values()):,} tokens to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
