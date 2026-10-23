#!/usr/bin/env python3
"""Build a Spanish word-family frequency list and optional sentence sidecar.

Uses the es_allforms.csv file from doozan/spanish_data when supplied. The
observed token and family lemma are both retained, so ambiguous mappings and
unrecognized forms remain reviewable. With --examples-output, a few matching
sentence excerpts are saved locally for each word family.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path


TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
SKIP_TAGS = {"script", "style", "svg", "head", "title", "noscript"}
BLOCK_TAGS = {"address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
              "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5",
              "h6", "hr", "li", "main", "ol", "p", "section", "table", "tr", "ul"}
MAX_EXAMPLES_PER_ENTRY = 5


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        elif not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def extract_epub_documents(path: Path):
    """Yield readable text sections with their EPUB member names."""
    try:
        with zipfile.ZipFile(path) as book:
            for name in book.namelist():
                if Path(name).suffix.lower() not in {".xhtml", ".html", ".htm"}:
                    continue
                parser = TextExtractor()
                parser.feed(book.read(name).decode("utf-8", errors="replace"))
                yield name, "".join(parser.parts)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"cannot read EPUB {path}: {exc}") from exc


def extract_epub(path: Path) -> str:
    """Extract EPUB text in a single string, preserving the old helper API."""
    return "\n".join(text for _, text in extract_epub_documents(path))


def iter_sentences(text: str):
    """Yield sentence-like text spans without crossing paragraph boundaries."""
    for paragraph in text.splitlines():
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        for sentence in SENTENCE_SPLIT_RE.split(paragraph):
            sentence = sentence.strip()
            if sentence and TOKEN_RE.search(sentence):
                yield sentence


def family_candidates(form: str, lemmas: dict[str, list[tuple[str, str]]]) -> list[tuple[str, str]]:
    candidates = lemmas.get(form, [])
    return candidates if candidates else [(form, "")]


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
    ap.add_argument("--examples-output", type=Path,
                    help="optional JSON sidecar for a few matching EPUB sentences per word family")
    args = ap.parse_args()

    lemmas: dict[str, list[tuple[str, str]]] = {}
    counts: Counter[str] = Counter()
    examples: dict[tuple[str, str], list[dict]] = defaultdict(list)
    example_seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    try:
        lemmas = read_lemmas(args.forms) if args.forms else {}
        for path in args.epub:
            for section, text in extract_epub_documents(path):
                counts.update(m.group(0).lower() for m in TOKEN_RE.finditer(text))
                if args.examples_output:
                    for sentence in iter_sentences(text):
                        matched_forms: dict[tuple[str, str], set[str]] = defaultdict(set)
                        for match in TOKEN_RE.finditer(sentence):
                            form = match.group(0).casefold()
                            for family in family_candidates(form, lemmas):
                                matched_forms[family].add(form)
                        for family, forms in matched_forms.items():
                            if (len(examples[family]) >= MAX_EXAMPLES_PER_ENTRY
                                    or sentence in example_seen[family]):
                                continue
                            examples[family].append({
                                "text": sentence,
                                "matched_forms": sorted(forms),
                                "section": section,
                                "source": path.name,
                            })
                            example_seen[family].add(sentence)

        families: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for form, count in counts.items():
            # Keep distinct homographic families visible; don't pretend the
            # form alone disambiguates the intended meaning.
            for family in family_candidates(form, lemmas):
                families[family][form] += count

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
        if args.examples_output:
            args.examples_output.parent.mkdir(parents=True, exist_ok=True)
            sidecar = {
                "version": 1,
                "vocab_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "sources": [path.name for path in args.epub],
                "entries": [
                    {
                        "lemma": lemma,
                        "part_of_speech": pos,
                        "examples": examples.get((lemma, pos), []),
                    }
                    for _, lemma, pos, _ in rows
                    if examples.get((lemma, pos))
                ],
            }
            with args.examples_output.open("w", encoding="utf-8") as f:
                json.dump(sidecar, f, ensure_ascii=False, indent=2)
                f.write("\n")
    except (OSError, ValueError, csv.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {len(rows)} word families from {sum(counts.values()):,} tokens to {args.output}")
    if args.examples_output:
        example_family_count = sum(
            bool(examples.get((lemma, pos))) for _, lemma, pos, _ in rows
        )
        print(f"Wrote sentence examples for {example_family_count:,} word families to {args.examples_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
