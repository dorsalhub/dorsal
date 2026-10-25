# Changelog

## 0.12.1 (unreleased)

### Fixed
- PDF layout boxes from `extract_pdf_layout_per_mille`, `extract_pdf_layout_normalized` and
  `extract_pdf_layout_pts` are in the page as a PDF viewer displays it: CropBox and `/Rotate` applied, top-left
  origin, as in PDF.js's viewport. The reported page width and height are the displayed size. Before, pages
  rotated by 90, 180 or 270 degrees, and pages whose CropBox or MediaBox does not start at 0,0, got boxes in the
  unrotated, uncropped page, often clamped to `y` 0 and height 0. Unrotated pages whose visible box starts at 0,0
  give exactly the same output as before, and token text and order are unchanged on every page. Text outside
  the displayed page, such as in a cropped-away margin, is left out, and boxes are clipped to the page.
- A page smaller than 1 pt reports a width or height of 1, not 0, so `document-extraction` records built from it
  validate. Other page sizes are still whole points, as before.
- `open/classification` labels and `open/regression` points are chunked at 10,000 items, the schemas' `maxItems`,
  not 100,000. A record with more labels or points than that no longer fails validation as a single chunk.
  Chunk limits are now read from the schema at the version in use.
- `open/ranking` and `open/temporal-segmentation` records can be chunked and sharded. An oversize record of
  either was pushed unsplit and rejected.
- `open/entity-extraction` `relations` are no longer copied into every chunk and shard. Each relation goes with
  the entity it starts from (else the one it points to), and relations that do not fit there spill into shards
  of their own. Reassembled relations are grouped by entity, not in their original order. Groups sharded by
  0.12.0, which carry every relation in every shard, still reassemble correctly.
- `reassemble_record` uses the chunks' `schema_id` when they have one, and tells `open/temporal-segmentation`
  from `open/audio-transcription` (both shard on `segments`) by the shape of the segments.
- `open/audio-transcription` chunks that only carry overflow text no longer get `segments: []`, which fails OATS
  0.6.0 and later, and chunks that only carry segments no longer get `text: ""`.
- Merging `open/audio-transcription` chunks joins their `text` as it was split, without adding a newline between
  chunks, so a transcript split at the 262,144-character limit comes back unchanged.
- `add_transcription(..., track_id=<int>)` writes the id as a string for schema versions whose `track_id` only
  accepts strings (OATS 0.7.0 and later), so `track_id=1, schema_version="0.8.0"` validates. Earlier versions
  keep the integer. `build_transcription_record` takes a keyword-only `schema_version` for the same purpose.
- Reading an attribute of `dorsal.file.validators` in a fresh interpreter, before
  `dorsal.file.validators.open_schema` was imported, recursed until `RecursionError`.
- The debug log of a model's options redacts secret-looking values at any depth, such as pdf-extractor's
  `password`. An option is redacted when a word of its name is `key`, `token`, `auth`, `authorization`,
  `bearer`, `cookie`, `pwd` or `credential(s)`, or ends in `password`, `passwd`, `passphrase`, `secret`, `token`,
  `apikey`, `accesskey`, `privatekey`, `secretkey` or `credential(s)`. Names like `max_keypoints` are not.

### Changed
- `DorsalClient` no longer sleeps through a long rate limit. A 429 whose `Retry-After` is longer than 60 seconds
  (`DORSAL_API_MAX_RETRY_AFTER`) is not retried, and raises `RateLimitError` with its `retry_after` at once.
  The same applies to a 413 or 503 with a long `Retry-After`, and a malformed `Retry-After` is ignored.
  Before, GET, HEAD, OPTIONS, PUT and DELETE requests slept for the whole `Retry-After`, which can be hours at a
  daily limit. Shorter `Retry-After` values are still retried as before.
- When the client's retries run out on a 429 or 5xx, it raises the error for the last response
  (`RateLimitError`, `APIError`, ...) instead of a `NetworkError` wrapping `requests`' `RetryError`.
- CLI output is borderless and emoji-free by default. Records and summaries are printed as headed sections with
  left-aligned keys, nested values are indented, and lists of nested values are marked with `-`. Borders are
  opt-in with `--borders rounded` (or `DORSAL_BORDERS`, or `borders` under `[ui]` in `dorsal.toml`), and emoji
  with `--icons emoji`. `--help` pages keep their borders. A global config created by an earlier version sets
  `borders = "rounded"` and `icons = "emoji"`; run `dorsal theme set --borders none --icons none --global` to
  switch.
- `dorsal scan` on a single file shows a spinner on stderr while scanning, instead of printing "Scanning metadata
  for ..." to stdout. Core annotations (`file/pdf`, `file/mediainfo`, ...) are headed by name alone (`PDF`,
  `MediaInfo`), like the base file info. Other annotations are headed by schema id, with the model that produced
  them alongside.

### Added
- `chunk_record(record, schema_id, schema_version=None)` takes the schema version to read chunk limits from.
- A test that imports every Dorsal symbol DorsalHub, dorsal-worker, FileSushi, pdf-extractor, dorsal-whisper and
  dorsalhub-adapters rely on, from the module each one uses.

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
