# Changelog

## 0.14.0 (unreleased)

### Migrating from 0.13
- **New minimum versions:** `oatschema[validate]>=0.9.0.1,<0.10`, `oatschema-adapters>=0.2,<0.3`,
  `jsonschema-rs>=0.58`, `typer>=0.19.0` and `tomlkit>=0.13.3`. `oatschema` 0.8 can no longer be installed with
  Dorsal.
- **OATS 0.8.0 stays the default.** `oatschema` and `oatschema-adapters` now default to 0.9.0, so Dorsal passes its
  own version to them. Pass `schema_version="0.9.0"` (`--schema-version 0.9.0`) to build, validate, stamp, export or
  push 0.9.0 records. DorsalHub doesn't accept 0.9.0 annotations yet.
- **Stricter validation at every schema version, 0.8.0 included:** a string or key with an unpaired surrogate is
  invalid, and so is a malformed `date-time` (such as `generation_metadata.created`). A record nested too deeply
  for the validator no longer raises `TypeError`: it is validated, and an error in it raises
  `oatschema.ValidationError`. A record that used to validate can now fail, and isn't stamped.
- **Numbers are checked before a record is stamped.** Every OATS record from `run_model`, the pipeline,
  `LocalFile.add_*` and adapter parsers goes through `oatschema.check_numbers` at the version it will carry. A bad
  number is NaN, ±infinity, beyond ±9007199254740991, or outside its field's bounds. An optional one under a
  property is dropped. A required one, or one in a list, rejects the record. Lossless conversions are made: numpy
  values to Python ones, `-0.0` to `0.0`, a whole float in an integer field to an int, and from 0.9.0 an integer
  `seed` to its string. Nothing is rounded. At 0.8.0 a `seed` beyond ±9007199254740991 is dropped; at 0.9.0 it is
  kept as a string. `force=True` skips the check as it skips validation. A forced record is stamped only if it
  validates at that version, so one holding NaN or ±infinity never gets a `schema_version` and can't be pushed.
- **Pushes check records Dorsal didn't check.** Before anything is uploaded, an OATS annotation that Dorsal didn't
  make or check in this process (loaded with `LocalFile.from_json`, or built by hand and sent with `DorsalClient`)
  goes through `check_numbers(..., on_bad_number="raise")` at its `schema_version`, and is sent as the check
  converts it (`-0.0` to `0.0`, at 0.9.0 an integer `seed` to its string; a sharded record that would need
  converting is refused). If any fails, the push raises
  `RejectedAnnotationError` and nothing is sent. That includes a record added with `force=True` and an explicit
  `schema_version` that holds a bad number.

### Added
- What was dropped, converted or rejected for a bad number is reported. In Python: `RunModelResult.dropped`,
  `.converted` and `.rejected`; `LocalFile.number_changes` (from the scan and `add_*`; a record a bad number
  rejected is listed with its `rejected` reason); `number_changes` on the response of `LocalFile.push`,
  `dorsal.api.index_file` and `MetadataReader.index_file`; `number_changes` in the `index_directory` summary; and the
  `dropped` and `converted` attributes of the dict `parse_file` returns. On the CLI, `dorsal scan`, `dorsal push`
  (with `--create-collection` and `--dry-run` too), `dorsal index build`, `dorsal model run` and
  `dorsal adapter parse` print a warning on stderr and add the changes to `--json` output. The exit code is still 0.
- The local cache keeps each record's changes and reports them again when the record is read from it.
- `on_bad_number="raise"` rejects a record with any bad number instead of dropping it, on `run_model`,
  `run_or_install_model`, `dorsal.testing.run_model`, `ModelRunner`, `MetadataReader`, `LocalFile` (its pipeline
  and `add_*`), `LocalFileCollection`, `dorsal.api.scan_file`, `scan_directory`, `index_file`, `index_directory`
  and `parse_file`. On the CLI, `--on-bad-number raise` on `dorsal scan`, `dorsal push`, `dorsal index build`,
  `dorsal model run` and `dorsal adapter parse`. The default is `"drop"`. A cached record that had values dropped
  isn't reused in `raise` mode, and one from which `raise` mode rejected a record isn't reused in `drop` mode: the
  file is scanned again.
- `dorsal push <dir> --dry-run --json` prints what would be pushed as JSON.
- `OpenSchemaValidator.check_numbers()`, also on the validator `make_schema_validator` returns for an OATS schema.

### Changed
- `oatschema-adapters` 0.2.0 changes some output (see its changelog). Document TSV gains a `polygon` column, and a
  polygon block's box columns hold its bounding box. Audio TSV with speakers gains `speaker_id` when an id differs
  from its name. Markdown parsing reads the frontmatter, including `producer` and `track_id`, so an integer
  `track_id` there now fails validation. A document record with no blocks exports to Markdown as "No content
  extracted from this document." instead of failing. `list_formats()` lists a `json` format for every OATS schema.
- With `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` set, `run_model`, the pipeline and `add_*` validate records against the
  override schema and don't check their numbers, and pushes don't check them either. Adapter parsing still checks
  them against the bundled schemas.
- `validate_dataset_records` validates records and doesn't check their numbers, since it keeps no records. Use
  `OpenSchemaValidator.check_numbers()` for that.

### Fixed
- `LocalFile.upgrade_file_record()` runs the file's own pipeline and `on_bad_number`, as do files from
  `MetadataReader.scan_directory`. It used to run the default pipeline in `drop` mode.

### Documentation
- `run_model`, `get_annotations` and `reassemble_record` say how to rebuild a record that was split into parts: join
  the parts' lists (such as `blocks`) in `source.execution_part` order. A part that was sharded for upload is
  reassembled in `group.index` order when it is read.

## 0.13.3 (2026-11-17)

### Fixed
- A `model_config.toml` option documented as a table without a `default` is no longer passed to the model by
  `dorsal run <namespace>/<name>`, `dorsal run <package>` and `run_or_install_model`, so the model's own default
  applies. Set it with `--opt` as before. A table under `[options]` is always a documented option: put a dict value
  in its `default`.
- The test written by `dorsal model init` reads `model_config.toml` from the project root, passes option defaults
  rather than the option tables, and checks every result `run_model` returns. New projects require
  `dorsalhub>=0.13.3`.

### Added
- `dorsal.testing.model_config_options(config=...)` returns the options a parsed `model_config.toml` passes to its
  model.
- Python 3.15 is supported and tested on Linux, macOS and Windows. `marisa-trie` (needed by `langcodes`) has no
  Python 3.15 wheel yet, so installing on 3.15 builds it from source, which needs a C++ compiler.

## 0.13.2 (2026-11-08)

### Changed
- PDF text extraction (`extract_pdf_layout_per_mille`, `extract_pdf_layout_normalized`, `extract_pdf_layout_pts`,
  and so the PDF extractor) asks pdfium for each text box's text once instead of twice, and reads `raw_text` from
  the page's existing text page instead of building a second one. Dense pages take about half the CPU time.
  The text, blocks and exports are unchanged.
- A record over its schema's list limit (such as more than 100,000 `blocks` in `document-extraction`) is split into
  parts without first being validated whole. Each part is still validated and records its `schema_version`. This
  cuts peak memory by about 40% on files that are split. If a part fails validation, the error is now that part's.

## 0.13.1 (2026-11-06)

### Changed
- Pushing to DorsalHub raises `UnversionedAnnotationError` (a `ValueError`) before any upload if an OATS annotation's
  `schema_version` is missing, `latest` or `published`. The whole push is refused, and the error lists each file,
  schema and model. Set `schema_version` on the model or pipeline step, then push with `--overwrite-cache`.

### Fixed
- A `schema_version` pin or argument is recorded only if the record validates against that version, including with
  a Pydantic validator, no validator or `force=True`. Otherwise the record has no version, and running still succeeds.

## 0.13.0 (2026-11-04)

### Migrating from 0.12
- **OATS 0.8.0 is the default** everywhere (was 0.5.0). Records keep the version stored with them or pinned by
  their model. A DorsalHub annotation with no stored version is read as 0.5.0 by `dorsal hub annotation get --export`
  and by `dorsal adapter export` on a saved annotation.
  Elsewhere, pass `schema_version="0.5.0"` (`--schema-version 0.5.0`) to keep validating older records at 0.5.0.
- **Schema ids:** use bare OATS names such as `document-extraction`, or the `oats/` form
  (`oats/document-extraction`). `open/document-extraction` still works but warns (`DeprecationWarning`, or a
  warning on stderr from the CLI and `dorsal.toml`) and will be removed. `arxiv` is accepted for `dorsal/arxiv`.
- **Exports use `oatschema-adapters`** instead of `dorsalhub-adapters`. Import adapters from `oatschema_adapters`
  with bare names; Dorsal's own `dorsal/arxiv` formats register with it on first use of `dorsal.api.adapters`.
  Format options are checked: an unknown one raises, and string values such as `"false"` are converted.
- **Validation errors:** `.validate` on an OATS validator raises `oatschema.ValidationError` (a `ValueError`)
  instead of `jsonschema_rs.ValidationError`. Catch `ValueError` to handle both. Validators for other schemas
  are unchanged.
- **Dense embeddings** over 16,384 values are rejected with an error naming the limit: `add_embedding`,
  `add_annotation` (`force=True` included) and `chunk_record` raise `EmbeddingTooLargeError` (a `ValueError`),
  `run_model` returns it as the result's error, and an `Annotation` with an `embedding` schema id holding one fails
  validation. An `Annotation` with no `schema_id` isn't checked. `chunk_record` no longer splits dense vectors.
  Reduce the dimensions or store a sparse vector.
- **`dorsal.toml`:** `register_model` and `dorsal model install` write bare schema names. Dorsal 0.12 and earlier
  reject them, and then every scan fails with "Invalid config for pipeline step", so don't share a `dorsal.toml`
  (such as the global `~/.dorsal/dorsal.toml`) between 0.13 and an earlier version. `ModelRunnerPipelineStep`
  dumps its `schema_id` as the bare name.
- `run_model` raises `ValueError` when the OATS schema is not in the requested `schema_version`, instead of
  running without validation.

### Changed
- Export output differs from `dorsalhub-adapters` 0.4.3 only by these fixes: TSV cells that would run as
  formulas start with `'`; YAML frontmatter values are quoted where needed; WebVTT and Markdown times round to
  the millisecond; parsing Markdown reads millisecond times and gives events to the segment that follows them;
  WebVTT cue text is escaped; hOCR `normalized` and `per_mille` boxes are scaled to the page;
  hOCR names `oatschema-adapters` as its OCR system; theme CSS comments are renamed; HTML `gap_x`/`gap_y` work.
- `dorsal adapter parse` writes the bare schema name and the `schema_version` it validated against.

### Added
- `export_record`, `export_record_to_file`, `parse_file` and `parse_file_from_path` take a keyword-only
  `schema_version`; the CLI passes each record's version, and `dorsal adapter export`/`parse` take
  `--schema-version`.
- `make_schema_validator(..., schema_version=...)` for OATS schemas.
- Local index extractors and CLI views for `embedding`, `ranking` and `temporal-segmentation`.

### Fixed
- `dorsal run --export-opt validate=...` no longer raises `TypeError`.
- The `dorsal/arxiv` Markdown and RIS exporters read `validate="false"` as off.

## 0.12.1 (2026-10-30)

### Fixed
- PDF layout boxes are correct on rotated pages and on pages whose CropBox or MediaBox doesn't start at 0,0.
- Pages smaller than 1 pt report a size of 1, so their `document-extraction` records validate.
- Chunking: `open/classification` and `open/regression` split at the schema's `maxItems` (10,000);
  `open/ranking` and `open/temporal-segmentation` can be chunked; `open/entity-extraction` relations are no longer
  copied into every chunk; `open/audio-transcription` chunks validate on OATS 0.6.0+ and rejoin text unchanged.
- `add_transcription(track_id=<int>)` validates against OATS 0.7.0+.
- First access to an attribute of `dorsal.file.validators` no longer raises `RecursionError`.
- The model options debug log redacts secret-looking values at any depth.

### Changed
- CLI output is borderless and emoji-free by default. Opt back in with `--borders rounded` and `--icons emoji`.
  Global configs created by earlier versions keep borders and emoji; to switch, run
  `dorsal theme set --borders none --icons none --global`.
- `dorsal scan` shows a spinner on stderr instead of printing "Scanning metadata for ..." to stdout.
- `DorsalClient` no longer sleeps through a `Retry-After` longer than 60 seconds; it raises `RateLimitError`.
  When retries run out, it raises the last response's error instead of `NetworkError`.

### Added
- `chunk_record` takes a `schema_version`.

## 0.12.0 (2026-10-20)

### Added
- `LocalFile.add_annotation(schema_id, record, *, schema_version=None, ...)` adds an annotation for any schema,
  including `open/ranking` and `open/temporal-segmentation`, which have no `add_*` helper.
- `add_classification`, `add_embedding`, `add_llm_output`, `add_location`, `add_transcription` and
  `add_regression` take a keyword-only `schema_version`. The annotation is validated against that OATS version
  and stamped with it. The default stays 0.5.0.
- Local search takes a `record_id:` field, matching a file's local Record ID.
- `dorsal.file.schemas.open_schema_versions(name)` lists the schema versions, oldest first, in which the installed
  `oatschema` package provides an open schema.

### Fixed
- `dorsal get <Record ID>` finds the record. A 16-character Record ID was looked up as a hash and never matched.
- `dorsal search` and `dorsal get` show the modified time in local time, as `dorsal scan` does. They showed UTC
  without saying so. `dorsal get --json` still gives UTC with its `+00:00` offset.
- Pydantic validation errors no longer carry whole record values. In logs, raised messages, `str()`, `repr()`
  and tracebacks, each error keeps its `loc` and `type`, `input` becomes a preview of about 100 characters,
  `msg` is capped, and at most 20 errors are kept. This covers model output validated by a Pydantic model,
  manual annotations, data quality linters, merged file records, annotation entries in a `FileRecord`, tags,
  URLs, sharded groups, and DorsalHub responses that fail validation.
- `ApiDataValidationError`, `AnnotationValidationError`, `DataQualityError` and `PipelineIntegrityError` raised
  for record or response content no longer chain the Pydantic error as `__cause__`, whose text grows with the
  number of errors. The error stays available as `original_exception`.
- Adding an `open/*` annotation in a schema version that does not contain it, such as `open/ranking` at the
  default 0.5.0, raises `ValueError` that names the versions that have it, in place of a `RuntimeError`.
- Logs no longer format a whole record or API response just to cut it to a snippet.

## 0.11.0 (2026-10-19)

### Added
- Every OATS schema version from 0.4.0 to 0.8.0 can be loaded and validated against, through the `oatschema`
  package (`get_open_schema(name, version)`, `get_open_schema_validator(name, version)`). The default stays 0.5.0.
- New open schema names: `temporal-segmentation` (OATS 0.7.0 and later) and `ranking` (OATS 0.8.0 and later).
- `OpenSchemaValidator`, the `JsonSchemaValidator` subclass `get_open_schema_validator` now returns. It adds
  `schema_name`, `schema_version` and `first_error()`.
- `IndexResultAnnotation` has optional `schema_id` and `schema_version` fields.

### Changed
- Dorsal no longer bundles its own copies of the OATS schemas. It depends on `oatschema[validate]>=0.8.0.1,<0.9`.
- A model's `schema_version` pin is honoured: its output is validated against that version and the record is
  stamped with it. Models with no pin are validated against 0.5.0, as before. A pin to a version `oatschema` does
  not have fails that model's step with an import error.
- Records are stamped with a schema's `x-version` (OATS 0.8.0 and later) or `version` (earlier releases).
- Validation errors no longer contain values from the record: values show as `…`, and messages, `str()` and
  `repr()` are capped at about 1,000 characters. `JsonSchemaValidator.validate` still raises
  `jsonschema_rs.ValidationError`.
- `json_schema_validate_records` reports the failing keyword and the validator's own message, in place of the
  "limit of … was exceeded" text used for every keyword, and builds `record_preview` without formatting the whole
  record. Its return shape is unchanged.
- When a file record is too large to push in one request, each annotation the hub rejects is now listed in the
  response's `results[].annotations` with its `name`, `status`, `detail`, `schema_id` and `schema_version`,
  whether or not `strict` is set. Annotations the hub answers with an error result are counted as errors.

### Fixed
- Loading an OATS 0.8.0 schema no longer raises "Critical Package Integrity Error".

### Notes
- `DORSAL_OPEN_VALIDATION_SCHEMAS_DIR` still works. When it is set, `<dir>/<name>.json` replaces the `oatschema`
  copy for every version, and a version mismatch is only logged.
