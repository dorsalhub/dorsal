<p align="center">
  <img src="https://dorsalhub.com/static/img/dorsal-logo.png" alt="Dorsal" width="520">
</p>

<p align="center">
  <strong>A local-first file metadata generation and management toolkit.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/dorsalhub/">
    <img src="https://img.shields.io/pypi/v/dorsalhub?color=0ea5e9" alt="PyPI version">
  </a>
  <a href="https://pypi.org/project/dorsalhub/">
    <img src="https://img.shields.io/pypi/pyversions/dorsalhub?color=0ea5e9" alt="Python versions">
  </a>
  <a href="https://opensource.org/licenses/Apache-2.0">
    <img src="https://img.shields.io/badge/license-Apache_2.0-0ea5e9" alt="License">
  </a>
  <a href="https://docs.dorsalhub.com">
    <img src="https://img.shields.io/badge/docs-dorsalhub.com-0ea5e9" alt="Documentation">
  </a>
  <br>
  <a href="https://github.com/dorsalhub/dorsal/actions/workflows/ci.yml">
    <img src="https://github.com/dorsalhub/dorsal/actions/workflows/ci.yml/badge.svg" alt="Tests">
  </a>
  <a href="https://codecov.io/gh/dorsalhub/dorsal">
    <img src="https://codecov.io/gh/dorsalhub/dorsal/graph/badge.svg" alt="codecov">
  </a>
</p>

**Dorsal** is an extensible, local-first framework and command line tool for **generating, validating, and managing structured file metadata**.

Dorsal provides configurable extraction and annotation pipelines for files.

### Annotation Models

Annotation Models are **plug and play** packages for Dorsal which perform **file extraction**, **annotation** or **conversion**.

[Explore](https://dorsalhub.com/models/explore) the models available on [dorsalhub.com](https://dorsalhub.com) or follow a [tutorial to build your own](https://docs.dorsalhub.com/python/hello-word/).

You can run and install models directly from the command line:

#### Whisper example

```console
$ dorsal run dorsalhub/whisper /home/video/test.mkv --export=srt
1
00:00:01,970 --> 00:00:05,970
You might be wondering how I ended up in this situation.

2
00:00:05,970 --> 00:00:08,970
Yeah that's me. A young subtitle.

3
00:00:08,970 --> 00:00:18,590
Little did I know what life had in store for me.


Outputs saved successfully:
  ↳ /home/user/sandbox/test.dorsal.json
  ↳ /home/user/sandbox/test.srt
```

### Dorsal is...

* **Local First:** Metadata extraction happens locally, not in the cloud. Use the CLI or python API to run the built-in extraction models or incorporate your own.
* **Strictly Validated:** All annotations are automatically checked against strict JSON Schemas and Pydantic models, ensuring predictability and easy downstream integration.
* **Batteries Included:** No file-type restrictions, and out-of-the-box support for core metadata extraction for many common file types including PDFs, Office documents, Media files and more.
* **Extensible:** Support your own file types and metadata annotation needs. Integrate your own models easily.
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

### 3. Run Annotation Models

You can install and run annotation models from the CLI:

```bash
dorsal run dorsalhub/pdf-extractor "path/to/document.pdf"
```

You can also export to any format supported by [Dorsal Adapters](https://github.com/dorsalhub/dorsal-adapters):

```bash
dorsal run dorsalhub/pdf-extractor "path/to/document.pdf" --export=html
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

### 4. Parse, Validate, and Export

Dorsal has two companion libraries to handle data structure and interoperability:

* **[Open Validation Schemas](https://github.com/dorsalhub/open-validation-schemas):** Dorsal annotations are strictly validated against these versioned, source-agnostic JSON schemas (e.g., `open/classification`, `open/document-extraction`). This ensures predictable outputs.

* **[Dorsal Adapters](https://github.com/dorsalhub/dorsal-adapters):** A bundled utility that converts between strictly validated JSON records and standard file formats.

**Example: Parse a standard file into a validated JSON record:**

```bash
$ dorsal adapter parse OSR_uk_000_0020_8k.srt audio-transcription
```

**Example: List available export formats for a schema:**

```bash
$ dorsal adapter list open/document-extraction
```

#### Supported Export Formats

You can currently export validated records into the following formats:

**Document Extraction** (`open/document-extraction`):

- Markdown (`.md`)
- HTML (`.html`)
- hOCR (`.hocr.html`)
- TSV (`.tsv`)
- Plain Text (`.txt`)

**Audio Transcription** (`open/audio-transcription`):

- SRT (`.srt`)
- WebVTT (`.vtt`)
- Markdown (`.md`)
- TSV (`.tsv`)
- Plain Text (`.txt`)


-----

## Custom Annotation Models

You can extend Dorsal by adding custom **Annotation Models** to the extraction pipeline. These are Python classes that define extraction logic and the output schema.

**Example: A "Hello Word" Model**

This toy model counts the top 5 words in a text file.

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
            description="Top 5 most common words",
            data=data
        )

# Validate the model
result = run_model(
    annotation_model=HelloWord,
    file_path="./path/to/test/file.txt",
    schema_id="open/generic"
)

assert not result.error
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