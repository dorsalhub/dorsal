# Dorsal

**A local-first metadata generation and management toolkit.**

[![PyPI version](https://badge.fury.io/py/dorsalhub.svg)](https://pypi.org/project/dorsalhub/)
[![Tests](https://github.com/dorsalhub/dorsal/actions/workflows/ci.yml/badge.svg)](https://github.com/dorsalhub/dorsal/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Dorsal** is a Python library and command line tool for generating, validating, and managing structured file metadata.

Dorsal has a fully configurable local metadata extraction pipeline. Metadata records can be exported to file or synced to **[DorsalHub](https://dorsalhub.com)** - a private-by-default platform for searching and tagging file metadata.

### Core Concepts

* **Local First:** Metadata extraction happens locally, not in the cloud. Use the CLI or python API to run the built-in extraction models or incorporate your own.
* **Strictly Validated:** All annotations are automatically checked against strict JSON Schemas and Pydantic models, ensuring predictability and easy downstream integration.
* **Annotate Any File:** No file-type restrictions, and out-of-the-box support for many common file types including PDFs, Office documents, Media files and more.
* **Extensible:** Support your own file types or annotation generation needs. Integrate your own models with arbitrary code.
-----

## Installation

Dorsal is available on pypi as `dorsalhub`.

```bash
pip install dorsalhub
```

## Authentication

To sync metadata records with DorsalHub, authenticate with an API Key (generate one on your DorsalHub settings page).

```bash
dorsal auth login
```

Alternatively, set the `DORSAL_API_KEY` environment variable.

-----

## CLI Usage

### 1. Scan a File

Generate a metadata record for a file using the default extraction pipeline.

```bash
dorsal file scan "docs/PDFSPEC.pdf"
```

**Output:**

```text
📄 Scanning metadata for PDFSPEC.pdf
╭───────────────────────────────── File Record: PDFSPEC.pdf ─────────────────────────────────╮
│                                                                                            │
│    Hashes                                                                                  │
│       SHA-256:  3383fb2ab568ca7019834d438f9a14b9d2ccaa2f37f319373848350005779368           │
│        BLAKE3:  9abdfb32750a278d5ca550b876e94a72cd8eec82d0e506a127dfb94bd56ca4b2           │
│          TLSH:  T13465D67BB4C61D6DF893CA46571C579B8B0D71533BAEA58604BDAF0AC6338029AC3F41   │
│                                                                                            │
│    File Info                                                                               │
│     Full Path:  /mnt/c/testdata/PDFSPEC.pdf                                                │
│      Modified:  2025-04-09 15:09:05                                                        │
│          Name:  PDFSPEC.pdf                                                                │
│          Size:  1 MiB                                                                      │
│    Media Type:  application/pdf                                                            │
│                                                                                            │
│    Tags                                                                                    │
│        No tags found.                                                                      │
│                                                                                            │
│    Pdf Info                                                                                │
│            author:  Tim Bienz, Richard Cohn, James R. Meehan                               │
│             title:  Portable Document Format Reference Manual (v 1.2)                      │
│           creator:  FrameMaker 5.1.1                                                       │
│          producer:  Acrobat Distiller 3.0 for Power Macintosh                              │
│           subject:  Description of the PDF file format                                     │
│          keywords:  Acrobat PDF                                                            │
│           version:  1.2                                                                    │
│        page_count:  394                                                                    │
│     creation_date:  1996-11-12T03:08:43                                                    │
│     modified_date:  1996-11-12T07:58:15                                                    │
│                                                                                            │
│                                                                                            │
╰────────────────────────────────────────────────────────────────────────────────────────────╯
```

-----

### 2. Push Metadata

Sync the metadata record to DorsalHub. By default, this creates a **private** record visible only to you.

```bash
dorsal file push "docs/PDFSPEC.pdf"
```

-----

## Python API

The `LocalFile` class runs the extraction pipeline on a specific file path.

### 1. Access Extracted Data

```python
from dorsal import LocalFile

# 1. Initialize (runs the pipeline)
lf = LocalFile("docs/PDFSPEC.pdf")

# 2. Access base attributes
print(f"Hash: {lf.hash}")
print(f"Type: {lf.media_type}")

# 3. Access format-specific attributes (if available)
if lf.pdf:
    print(f"Pages: {lf.pdf.page_count}")
    print(f"Title: {lf.pdf.title}")
```


### 2. Add Tags & Annotations

```python
# Add a simple key-value tag
lf.add_private_tag(name="project_id", value=12345)

# Add a structured annotation (validates against the 'open/classification' schema)
lf.add_classification(
    labels=[{"label": "urgent", "score": 1.0}],
    vocabulary=["urgent", "review"],
    private=True
)

# Sync the enriched record to DorsalHub
lf.push()
```



### 3. Batch Reporting

Generate self-contained HTML dashboards for local directories.

```python
from dorsal.api import generate_html_directory_report

generate_html_directory_report(
    dir_path="./projects",
    output_path="storage_audit.html",
    recursive=True
)
```

-----

## Custom Annotation Models

You can extend Dorsal by adding custom **Annotation Models** to the extraction pipeline. These are Python classes that define extraction logic and the output schema.

**Example: A "Hello Word" Model**
This model counts the top 5 words in a text file.

```python
from collections import Counter
from dorsal import AnnotationModel
from dorsal.testing import run_model
from dorsal.file.helpers import build_generic_record

class HelloWord(AnnotationModel):
    def main(self):
        with open(self.file_path, 'r') as f:
            words = f.read().split()
            
        data = {str(i+1): v[0] for i, v in enumerate(Counter(words).most_common(5))}
        
        return build_generic_record(
            file_hash=self.hash,
            description="Top 5 most common words",
            data=data
        )

# Validate the model
result = run_model(
    annotation_model=HelloWord,
    file_path="./path/to/test/file.txt",
    schema_id="open/generic"
)

assert result.error is None
```

You can add it to Dorsal's local file metadata extraction pipeline:
```python
from dorsal.api import register_model
from helloword import HelloWord

# Add the model to your pipeline
register_model(
    annotation_model=HelloWord,
    schema_id="open/generic"
)
```

-----

Now, each time you run `dorsal file scan` or `LocalFile()`, this model will execute automatically.

-----

## Resources

* **[Documentation](https://docs.dorsalhub.com)**: Full API reference, CLI guides, and tutorials.
* **[DorsalHub](https://dorsalhub.com)**: The hosted platform for managing your metadata.
* **[Issue Tracker](https://github.com/dorsalhub/dorsal/issues)**: Report bugs or request features.

## License

Dorsal is open source and provided under the Apache 2.0 license.