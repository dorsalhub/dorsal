# Changelog

## 0.12.0 (2026-10-20)

### Added
- `LocalFile.add_annotation(schema_id, record, *, schema_version=None, ...)` adds an annotation for any schema,
  including `open/ranking` and `open/temporal-segmentation`, which have no `add_*` helper.
- `add_classification`, `add_embedding`, `add_llm_output`, `add_location`, `add_transcription` and
  `add_regression` take a keyword-only `schema_version`. The annotation is validated against that OATS version
  and stamped with it. The default stays 0.5.0.
- Local search takes a `record_id:` field, matching a file's local Record ID.

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
