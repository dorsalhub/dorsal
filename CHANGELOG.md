# Changelog

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
