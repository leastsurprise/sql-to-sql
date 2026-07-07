# sql-to-sql

A Python tool for migrating a SQL codebase from one dialect to another, using regex-driven function rewriting controlled by a JSON mapping file. It was built for a real-world **Impala → Snowflake** migration (including SQL embedded in SAS pass-through blocks), but the mapping is fully user-defined, so it can be adapted to other dialect pairs.

Rather than fully parsing SQL, `evolve.py` takes a pragmatic middle path: it masks the tricky parts of the text (strings, comments, quotes, bracketed identifiers), rewrites function calls according to your `migration_map.json`, iterates until the output stabilises, then unmasks everything. This makes it robust against the things that break naive find-and-replace — nested function calls, commas inside string literals, mixed quote styles, and functions that share a name across dialects.

## Repository contents

| File | Purpose |
| --- | --- |
| `evolve.py` | The migration engine and command-line interface. |
| `migration_map.json` | The control file describing how each source-dialect function maps to the destination dialect, plus ad-hoc regex rewrites. |

You will also need to create (not included in the repo):

| File | Purpose |
| --- | --- |
| `source_language_function_list.txt` | One source function name per line. Required only for the `-l` (scan/list) mode. |
| An ignore-list file (optional) | Like a `.gitignore`: filenames to skip, one per line, passed with `-x`. |

## Requirements

- Python 3 (standard library only — `re`, `json`, `getopt`, `base64`, `os`, `sys`).
- Input files with a `.sql` or `.sas` extension, UTF-8 encoded.

## Usage

```text
evolve.py -h                  Show help
evolve.py -l -i <inputpath>   Scan files and list which source-language functions they use
evolve.py -i <inputpath> -o <outputpath> [-t <tag text>] [-q <quote char>] [-x <ignore file>]
```

| Option | Meaning |
| --- | --- |
| `-i` | Input file **or** directory. If a directory, all `.sql` and `.sas` files in it are processed. |
| `-o` | Output file or directory. Must match the type of `-i` (file→file, dir→dir). |
| `-l` | List mode: report which functions from `source_language_function_list.txt` appear in the input. Useful for scoping the migration before you start. |
| `-t` | Optional tag text. Each migrated function is annotated with a `/* tag_FUNCTIONNAME */` comment so you can find and review every rewrite. Suppress per-function with `"SUPPRESS_TAG": "Y"` in the map. |
| `-q` | Force all string quotes in the output to a single character (single or double). Useful when the destination dialect only accepts one quote style. |
| `-x` | Path to an ignore-list file (like `.gitignore`) naming files to skip. |

Example — migrate a directory of Impala scripts to Snowflake, tagging each change with `MIG1`:

```bash
python evolve.py -i ./impala_src -o ./snowflake_out -t MIG1
```

## The migration map (`migration_map.json`)

The top-level keys are **uppercased source function names**. Each maps to an object with two required keys:

- **`DESTINATION_LANGUAGE_FUNCTION_TEMPLATE`** — a string containing the placeholder `_ARGS_`, e.g. `"CHARINDEX(_ARGS_)"`. Templates can nest destination functions: `"ABS(HASH(_ARGS_))"`.
- **`ARGUMENTS_AND_LITERALS_MAP`** — an array defining what goes in place of `_ARGS_`:
  - **Integers** are 1-based indexes into the source function's arguments. Arguments are harvested by parenthesis counting, so a whole nested expression like `f(g(3,44), 62)` counts as one argument.
  - **Strings** are inserted literally (e.g. `"'DAY'"`, `"MONTH"`).
  - The special value `"_SUPPRESS_COMMA_"` glues the next item to the previous one without an argument-separating comma.
  - Arguments may be reordered, dropped, or interleaved with literals. Example: `[3, "MY_LITERAL", 1]`.

Additional per-function keys: `"SUPPRESS_TAG": "Y"` (omit the review tag) and free-form `"COMMENT"` keys for documentation.

A worked example from the included map — Impala's `INSTR(haystack, needle, pos)` becomes Snowflake's `CHARINDEX(needle, haystack, pos)` by swapping the first two arguments:

```json
"INSTR": {
    "DESTINATION_LANGUAGE_FUNCTION_TEMPLATE": "CHARINDEX(_ARGS_)",
    "ARGUMENTS_AND_LITERALS_MAP": [2, 1, 3]
}
```

### ADHOC_REGEXP

The special top-level key `"ADHOC_REGEXP"` holds an array of `{"SEARCH_STR", "REPLACEMENT_STR"}` pairs applied (case-insensitively) as a final pass, after function migration and unmasking. Use it for anything that isn't a function call: schema/database renames, removing statements the destination doesn't need (`invalidate metadata`, `compute stats`), rewriting `create table` to `create or replace table`, macro-variable substitution, and general tidy-ups. The bundled map contains the author's Impala/SAS-specific rules — treat these as examples and replace them with your own.

## How it works

1. **Overreach protection** — text wrapped in `>>>=== ... ===<<<` markers is base64-encoded and emitted as `BASE64_DECODE_STRING('...')`. This shields SQL with unbalanced quotes/parens from fragile parsers in host languages (e.g. SAS pass-through).
2. **Interim-code switching** — `/* IF_MIGRATING_THEN_START ... IF_MIGRATING_THEN_FINISH */` blocks are uncommented in the output, and `/* IF_NOT_MIGRATING_THEN_START */ ... /* IF_NOT_MIGRATING_THEN_FINISH */` blocks are removed. This lets you keep source- and destination-dialect versions of tricky sections side by side in one codebase. Anything inside an `IF_MIGRATING` block is treated as hand-migrated and skipped by the function rewriter. (Don't nest `/* */` comments inside these blocks.)
3. **Masking** — quotes inside comments are neutralised; opening/closing quotes, quotes-within-quotes, commas inside strings and `[...]` brackets, and escaped parens are replaced with rare Unicode sentinel characters so the rewriter can't be fooled by them.
4. **Function rewriting** — for each function in the map, matches are found and replaced back-to-front (so offsets stay valid). Arguments are harvested by parenthesis counting (a leading `DISTINCT` is detected and preserved). A negative-lookahead regex and a "chain detachment" sentinel prevent runaway rewrites when the destination function has the same name as the source (see the `TO_DATE`/`TOD_ATE` trick in the map).
5. **Iteration** — because only the innermost call in a chain is rewritten per pass, the rewriter loops (up to 30 passes) until the text stops changing.
6. **Unmasking and cleanup** — sentinels are restored to real characters (optionally normalising all quotes via `-q`), double/leading/trailing commas left by dropped arguments are tidied, and the `ADHOC_REGEXP` rules run last.

## Limitations and caveats

- This is regex-based rewriting, not a SQL parser. It handles the common traps well, but always **diff and review the output** — the `-t` tag exists precisely so you can eyeball every rewrite.
- Argument harvesting scans at most 2,000 characters past a function's opening paren; extremely long argument lists may be truncated.
- The masking scheme uses uncommon Unicode characters (e.g. `©`, `®`, `«`, `»`, `⋒`, `∷`) as sentinels; if your source code legitimately contains these, they will be transformed.
- `migration_map.json` and `source_language_function_list.txt` are read from the working directory (or `.\SnowFlakeMigration` on Windows, an artifact of the author's multi-project repo layout — adjust `base_dir` in `evolve.py` to suit).
- The bundled `ADHOC_REGEXP` rules and some map entries are specific to the original Impala/SAS→Snowflake project; prune them before using the tool on your own codebase.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Michael T. Emslie.
