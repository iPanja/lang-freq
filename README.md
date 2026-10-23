# EPUB Spanish frequency list

`frequency.py` reads text from EPUB XHTML/HTML documents and writes a CSV
frequency list. It uses only Python's standard library.

```sh
python frequency.py "book.epub" -o vocab.csv \
  --forms spanish_data/es_allforms.csv \
  --examples-output vocab.examples.json
```

Pass several EPUB paths to combine books into one list. The output has a
`lemma` word-family column, part of speech, total count, and the observed
surface forms with their counts. For example, when the supplied data maps
`hago` and `hice` to `hacer`, their counts contribute to the `hacer` family
while both forms remain listed. Without `--forms`, each spelling is treated
as its own family. Forms missing from the table also remain as their own
families.

The dictionary data can contain multiple lemma/POS candidates for one spelling.
The browser groups the same headword across parts of speech and counts each
observed spelling once. When a spelling has multiple lemma candidates, the
general frequency list is used as a likely-analysis prior; ties or missing
evidence stay under the spelling itself with the candidate analyses shown for
review. Corpus frequency is not contextual disambiguation, so check the story
sentence before relying on an analysis.

The recommended mapping file comes from
[doozan/spanish_data](https://github.com/doozan/spanish_data), whose README
attributes `es_allforms.csv` to Wiktionary-derived data. Observe that
repository's license and attribution terms when redistributing derived lists.

## Browse the generated vocabulary

After generating `vocab.csv`, start the local browser UI from the repository
root:

```sh
python3 app.py
```

Open <http://127.0.0.1:8000>. The UI searches and filters the story vocabulary,
then enriches a selected entry with dictionary glosses, general Spanish
frequency, observed forms, and bilingual example sentences from `spanish_data`.
When generated, `vocab.examples.json` adds a few sentence excerpts from the
source EPUB. The app auto-loads this companion file; both files remain local.
For another vocabulary list, pass `--vocab path/to/other.csv`. To use a
sidecar with a different name or location, also pass
`--examples path/to/examples.json`.
Use **Copy fields** to copy the headword, part of speech, story count, and
observed forms. Save a word with the star, or mark it Learning/Known. These
markers and the known-word story coverage estimate are stored in this
browser's local storage. The **Needs review** filter shows entries with
alternative analyses. Press `/` to focus search and `Esc` to clear it. The app
supports ↑/↓ to move through the visible list, Enter to open the selected
entry, K/L/U to set Known/Learning/clear status, S to save, and C to copy its
fields. These shortcuts are inactive while typing in a field. The app uses
only Python's standard library and serves data from the local checkout.

The sentence sidecar is optional and contains at most five distinct excerpts
per lemma/POS entry, including the EPUB section heading when available. It only
includes snippets matched during frequency-list generation; it does not
contain the full EPUB text.
