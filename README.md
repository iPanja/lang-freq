# EPUB Spanish frequency list

`frequency.py` reads text from EPUB XHTML/HTML documents and writes a CSV
frequency list. It uses only Python's standard library.

```sh
python frequency.py "book.epub" -o vocab.csv \
  --forms spanish_data/es_allforms.csv
```

Pass several EPUB paths to combine books into one list. The output has a
`lemma` word-family column, part of speech, total count, and the observed
surface forms with their counts. For example, when the supplied data maps
`hago` and `hice` to `hacer`, their counts contribute to the `hacer` family
while both forms remain listed. Without `--forms`, each spelling is treated
as its own family. Forms missing from the table also remain as their own
families.

The dictionary data can contain multiple lemma/POS candidates for one spelling.
The script lists each candidate as a separate family because the EPUB text
alone cannot determine which meaning was intended; in such cases the same
occurrence contributes to each candidate. Review those rows when making cards.
This is a lexicon lookup, not contextual morphological analysis, so coverage
and ambiguity depend on the supplied data.

The recommended mapping file comes from
[doozan/spanish_data](https://github.com/doozan/spanish_data), whose README
attributes `es_allforms.csv` to Wiktionary-derived data. Observe that
repository's license and attribution terms when redistributing derived lists.
