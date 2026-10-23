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


def parse_observed_forms(value: str) -> list[tuple[str, int]]:
    forms = []
    for item in value.split(";"):
        match = re.match(r"^\s*(.*?)\s+\((\d+)\)\s*$", item)
        if match:
            forms.append((match.group(1), int(match.group(2))))
        elif item.strip():
            forms.append((item.strip(), 0))
    return forms


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


def index_form_frequency(frequency: dict[tuple[str, str], list[dict]]) -> dict[tuple[str, str, str], int]:
    """Return corpus counts for exact surface forms under lemma/POS analyses."""
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for (lemma, pos), entries in frequency.items():
        for entry in entries:
            for item in entry["usage"].split("|"):
                if ":" not in item:
                    continue
                count_text, form = item.split(":", 1)
                try:
                    count = int(count_text)
                except ValueError:
                    continue
                counts[(lemma, pos, form.casefold())] += count
    return counts


def resolve_vocab(rows: list[dict], form_frequency: dict[tuple[str, str, str], int],
                  dictionary: dict[str, list[dict]]) -> list[dict]:
    """Group same headwords and assign each surface form to at most one analysis.

    Where a form has several analyses, exact-form corpus usage supplies a likely
    choice. Ties and forms without corpus evidence stay visibly ambiguous.
    """
    candidates: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
    display_lemmas: dict[tuple[str, str], str] = {}
    form_counts: dict[str, int] = defaultdict(int)

    def warning_for(lemma: str) -> str:
        glosses = [gloss.casefold() for entry in dictionary.get(lemma.casefold(), [])
                   for gloss in entry.get("glosses", [])]
        if any("misspelling of" in gloss for gloss in glosses):
            return "The local dictionary labels this headword as a misspelling."
        return ""

    def alternative_record(option: dict) -> dict:
        alternative_glosses = [gloss for entry in dictionary.get(option["lemma"].casefold(), [])
                               for gloss in entry.get("glosses", [])]
        return {
            "lemma": option["lemma"],
            "pos": option["pos"],
            "forms": [],
            "corpus_form_count": option["corpus_form_count"],
            "glosses": list(dict.fromkeys(alternative_glosses))[:3],
            "warning": warning_for(option["lemma"]),
        }

    for row in rows:
        key = (row["lemma"].casefold(), row["pos"])
        display_lemmas[key] = row["lemma"]
        for form, count in parse_observed_forms(row["observed_forms"]):
            normalized = form.casefold()
            form_counts[normalized] = max(form_counts[normalized], count)
            candidate = candidates[normalized].setdefault(key, {"count": 0})
            candidate["count"] = max(candidate["count"], count)

    grouped: dict[str, dict] = {}

    def ensure_group(lemma: str) -> dict:
        normalized = lemma.casefold()
        if normalized not in grouped:
            grouped[normalized] = {
                "lemma": lemma,
                "pos_tags": set(),
                "forms": {},
                "possible_analyses": {},
            }
        return grouped[normalized]

    for form, form_candidates in candidates.items():
        options = []
        for key, data in form_candidates.items():
            lemma, pos = key
            options.append({
                "key": key,
                "lemma": display_lemmas[key],
                "pos": pos,
                "form_count": data["count"],
                "corpus_form_count": form_frequency.get((lemma, pos, form), 0),
            })
        highest = max((option["corpus_form_count"] for option in options), default=0)
        winners = [option for option in options if option["corpus_form_count"] == highest]
        if highest > 0 and len(winners) == 1:
            chosen = winners[0]
            group = ensure_group(chosen["lemma"])
            group["pos_tags"].add(chosen["pos"])
            group["forms"][form] = {"count": form_counts[form], "resolution": "corpus-prior"}
            alternatives = [option for option in options if option["key"] != chosen["key"]]
            for alternative in alternatives:
                alt_key = (alternative["lemma"].casefold(), alternative["pos"])
                item = group["possible_analyses"].setdefault(alt_key, alternative_record(alternative))
                if form not in item["forms"]:
                    item["forms"].append(form)
        elif len(options) == 1:
            chosen = options[0]
            group = ensure_group(chosen["lemma"])
            group["pos_tags"].add(chosen["pos"])
            group["forms"][form] = {"count": form_counts[form], "resolution": "unambiguous"}
        else:
            # No strong corpus winner: show the spelling itself once and retain
            # all lexicon candidates in its detail panel.
            group = ensure_group(form)
            group["forms"][form] = {"count": form_counts[form], "resolution": "unresolved"}
            group["ambiguous"] = True
            for option in options:
                alt_key = option["key"]
                item = group["possible_analyses"].setdefault(alt_key, alternative_record(option))
                if form not in item["forms"]:
                    item["forms"].append(form)

    output = []
    for group in grouped.values():
        forms = group["forms"]
        resolved_count = sum(data["count"] for data in forms.values()
                             if data["resolution"] == "unambiguous")
        likely_count = sum(data["count"] for data in forms.values()
                           if data["resolution"] == "corpus-prior")
        ambiguous_count = sum(data["count"] for data in forms.values()
                              if data["resolution"] == "unresolved")
        count = resolved_count + likely_count + ambiguous_count
        observed = "; ".join(
            f"{form} ({data['count']})"
            for form, data in sorted(forms.items(), key=lambda item: (-item[1]["count"], item[0]))
        )
        output.append({
            "lemma": group["lemma"],
            "pos": ", ".join(sorted(group["pos_tags"])) if group["pos_tags"] else "ambiguous",
            "pos_tags": sorted(group["pos_tags"]),
            "count": count,
            "resolved_count": resolved_count,
            "likely_count": likely_count,
            "ambiguous_count": ambiguous_count,
            "observed_forms": observed,
            "possible_analyses": sorted(group["possible_analyses"].values(),
                                        key=lambda item: (-item["corpus_form_count"], item["lemma"], item["pos"])),
            "ambiguous": ambiguous_count > 0,
        })
    output.sort(key=lambda row: (-row["count"], row["lemma"].casefold(), row["pos"]))
    for rank, row in enumerate(output, 1):
        row["rank"] = rank
    return output


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
        self.frequency = read_frequency()
        self.dictionary = read_dictionary()
        self.form_frequency = index_form_frequency(self.frequency)
        self.vocab = resolve_vocab(read_vocab(vocab_path), self.form_frequency, self.dictionary)
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
        analysis_keys = {(lemma, item) for item in row["pos_tags"]}
        analysis_keys.update((item["lemma"].casefold(), item["pos"])
                             for item in row["possible_analyses"])
        story_examples = []
        story_seen = set()
        for key in analysis_keys:
            for example in self.story_examples.get(key, []):
                if example.get("text") not in story_seen:
                    story_seen.add(example.get("text"))
                    story_examples.append(example)
        result["story_examples"] = story_examples[:12]
        result["story_examples_available"] = self.has_story_examples
        result["general_frequency"] = [
            entry for item in row["pos_tags"]
            for entry in self.frequency.get((lemma, item), [])
        ]
        # Dictionary entries sometimes use a different POS vocabulary. Return
        # all entries for the spelling and let the reader see the alternatives.
        result["dictionary"] = self.dictionary.get(lemma, [])
        result["form_resolution"] = {
            "unambiguous": row["resolved_count"],
            "corpus_prior": row["likely_count"],
            "unresolved": row["ambiguous_count"],
        }
        if self.sentences is None:
            self.sentences = build_sentence_index()
        community_examples = []
        community_seen = set()
        community_count = 0
        for key in analysis_keys:
            matches = self.sentences.get(key)
            if matches:
                community_count += matches["count"]
                for example in matches["examples"]:
                    if example["spanish"] not in community_seen:
                        community_seen.add(example["spanish"])
                        community_examples.append(example)
        result["examples"] = community_examples[:12]
        result["example_count"] = community_count
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
