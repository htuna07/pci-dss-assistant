# PCI DSS RAG — Step 1: Load PDF

This starter project loads the provided PCI DSS v4.0.1 PDF with PyMuPDF, reports the page count, and extracts a text preview from a selected page. It does **not** create embeddings or perform RAG yet.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## Run

```bash
python src/main.py
python src/main.py --page 44 --max-chars 1500
```

Note: `--page` refers to the PDF viewer's 1-based page number, not the printed page number inside the document. These are different because of the front matter.
