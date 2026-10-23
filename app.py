#!/usr/bin/env python3
"""Serve a small local vocabulary browser for vocab.csv and spanish_data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "spanish_data"
SENTENCE_TAG_RE = re.compile(r":([^,:\s]+),([^:]+)")


def read_vocab(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"vocabulary CSV is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append({
                "rank": int(row["rank"]),
                "lemma": row["lemma"],
                "pos": row["part_of_speech"],
                "count": int(row["count"]),
                "observed_forms": row["observed_forms"],
            })
    return rows


def read_frequency() -> dict[tuple[str, str], list[dict]]:
    results: dict[tuple[str, str], list[dict]] = {}
    with (DATA / "frequency.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = (row["spanish"].strip().casefold(), row["pos"].strip())
            # Keep duplicate source entries available as a list rather than
            # hiding homographs that share a part-of-speech label.
            item = {
                "count": int(row["count"]),
                "flags": row["flags"],
                "usage": row["usage"],
            }
            results.setdefault(key, []).append(item)
    return results


def read_dictionary() -> dict[str, list[dict]]:
    """Read the useful headword/POS/gloss/usage fields from es-en.data."""
    entries: dict[str, list[dict]] = defaultdict(list)
    key = ""
    current: dict | None = None
    try:
        f = (DATA / "es-en.data").open(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return entries
    with f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line == "_____":
                continue
            if not line.startswith(" ") and not line.startswith("\t"):
                if line.startswith("pos: "):
                    if key:
                        current = {"pos": line[5:].strip(), "glosses": [], "usage": []}
                        entries[key].append(current)
                    continue
                key = line.strip().casefold()
                current = None
                continue
            if current is None:
                continue
            field = line.strip()
            if field.startswith("gloss: "):
                current["glosses"].append(field[7:])
            elif field.startswith("usage: "):
                current["usage"].append(field[7:].replace("\\n", "\n"))
    return entries


def read_story_examples(path: Path, vocab_path: Path) -> dict[tuple[str, str], list[dict]]:
    if path is None:
        return {}
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    vocab_hash = hashlib.sha256(vocab_path.read_bytes()).hexdigest()
    if payload.get("vocab_sha256") != vocab_hash:
        raise ValueError(f"sentence sidecar does not match vocabulary file: {path}")
    examples = {}
    for entry in payload.get("entries", []):
        key = (str(entry.get("lemma", "")).casefold(), str(entry.get("part_of_speech", "")))
        examples[key] = entry.get("examples", [])
    return examples


def build_sentence_index() -> dict[tuple[str, str], dict]:
    """Index bilingual examples by tagged lemma and part of speech."""
    index: dict[tuple[str, str], dict] = {}
    path = DATA / "sentences.tsv"
    if not path.exists():
        return index
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.reader(f, delimiter="\t"):
            if len(row) < 6:
                continue
            english, spanish, attribution, en_level, es_level, tags = row[:6]
            seen = set()
            for match in SENTENCE_TAG_RE.finditer(tags):
                pos = match.group(1).strip()
                # Values can contain a surface form and lemma separated by |;
                # phrase tags can contain spaces, so split on both delimiters.
                for value in re.split(r"[|,]", match.group(2)):
                    lemma = value.strip().casefold()
                    if lemma and " " not in lemma:
                        seen.add((lemma, pos))
            sentence = {
                "english": english,
                "spanish": spanish,
                "attribution": attribution,
                "english_level": en_level,
                "spanish_level": es_level,
            }
            for tag in seen:
                bucket = index.setdefault(tag, {"count": 0, "examples": []})
                bucket["count"] += 1
                if len(bucket["examples"]) < 12:
                    bucket["examples"].append(sentence)
    return index


class App:
    def __init__(self, vocab_path: Path, story_examples: dict[tuple[str, str], list[dict]] | None) -> None:
        self.vocab = read_vocab(vocab_path)
        self.frequency = read_frequency()
        self.dictionary = read_dictionary()
        self.story_examples = story_examples or {}
        self.has_story_examples = story_examples is not None
        self.sentences: dict[tuple[str, str], dict] | None = None
        self.by_rank = {row["rank"]: row for row in self.vocab}

    def entry(self, rank: int) -> dict | None:
        row = self.by_rank.get(rank)
        if row is None:
            return None
        lemma, pos = row["lemma"].casefold(), row["pos"]
        result = dict(row)
        result["story_examples"] = self.story_examples.get((lemma, pos), [])
        result["story_examples_available"] = self.has_story_examples
        result["general_frequency"] = self.frequency.get((lemma, pos), [])
        # Dictionary entries sometimes use a different POS vocabulary. Return
        # all entries for the spelling and let the reader see the alternatives.
        result["dictionary"] = self.dictionary.get(lemma, [])
        if self.sentences is None:
            self.sentences = build_sentence_index()
        matches = self.sentences.get((lemma, pos))
        if not matches and pos:
            matches = self.sentences.get((lemma, ""))
        result["examples"] = matches["examples"] if matches else []
        result["example_count"] = matches["count"] if matches else 0
        return result


class Handler(SimpleHTTPRequestHandler):
    server_version = "LangFreq/1.0"

    def __init__(self, *args, app: App, **kwargs):
        self.app = app
        super().__init__(*args, directory=str(ROOT / "ui"), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/vocab":
            self.send_json(self.app.vocab)
        elif parsed.path == "/api/entry":
            query = parse_qs(parsed.query)
            try:
                rank = int(query.get("rank", [""])[0])
            except ValueError:
                rank = -1
            entry = self.app.entry(rank)
            if entry is None:
                self.send_json({"error": "Vocabulary entry not found"}, 404)
            else:
                self.send_json(entry)
        elif parsed.path in {"/", "/index.html"}:
            self.path = "/index.html"
            super().do_GET()
        elif parsed.path.startswith("/static/"):
            self.path = parsed.path.removeprefix("/static/")
            super().do_GET()
        else:
            self.send_error(404)

    def send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--vocab", type=Path, default=ROOT / "vocab.csv",
                        help="vocabulary CSV to display (default: vocab.csv in this repo)")
    parser.add_argument("--examples", type=Path,
                        help="sentence sidecar JSON; defaults to <vocab>.examples.json when present")
    args = parser.parse_args()
    vocab_path = args.vocab.resolve()
    examples_path = args.examples.resolve() if args.examples else vocab_path.with_suffix(".examples.json")
    if args.examples and not examples_path.is_file():
        parser.error(f"examples sidecar not found: {examples_path}")
    if not args.examples and not examples_path.is_file():
        examples_path = None
    try:
        story_examples = read_story_examples(examples_path, vocab_path) if examples_path else None
        app = App(vocab_path, story_examples)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        if args.examples:
            parser.error(str(exc))
        print(f"Ignoring optional sentence sidecar: {exc}")
        app = App(vocab_path, None)
    server = ThreadingHTTPServer((args.host, args.port), lambda *a, **kw: Handler(*a, app=app, **kw))
    print(f"Vocabulary UI: http://{args.host}:{args.port}")
    print(f"Vocabulary: {vocab_path}")
    if examples_path and app.has_story_examples:
        print(f"Story examples: {examples_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping vocabulary UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
