"""Constants describing the PCI DSS v4.0.1 PDF layout."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = PROJECT_ROOT / "data" / "PCI-DSS-v4_0_1.pdf"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

DOCUMENT_VERSION = "4.0.1"

REQUIREMENT_HEADER = "Defined Approach Requirements"
TESTING_HEADER = "Defined Approach Testing Procedures"
RUNNING_TITLE = "Requirements and Testing Procedures"

# Supports IDs such as 1.2.3 and 3.5.1.2.
ID_PATTERN = r"\d+(?:\.\d+){2,}"

# Reviewed continuation-label corrections for this PDF.
# (PDF page number, extracted label ID): actual requirement ID
CONTINUATION_CORRECTIONS = {
    (169, "7.1.2"): "7.2.1",
}

# Maps the heading printed at the top of a field to its output key.
COLUMN_HEADINGS = {
    "requirement": {
        REQUIREMENT_HEADER: "defined_requirement",
        "Customized Approach Objective": "customized_approach_objective",
        "Applicability Notes": "applicability_notes",
    },
    "testing": {
        TESTING_HEADER: "testing_procedures",
    },
    "guidance": {
        "Purpose": "purpose",
        "Good Practice": "good_practice",
        "Definitions": "definitions",
        "Examples": "examples",
        "Further Information": "further_information",
    },
}

# Horizontal text boundaries of the three table columns. Expanded to include
# the text boundaries observed on pages 97–98.
COLUMN_BOUNDS = {
    "requirement": (48, 294),
    "testing": (294, 508),
    "guidance": (508, 744),
}

# Vertical limits of the page body in points. The running header ends near
# y=97 and the footer starts near y=542; introduction pages have no table
# header band, so their body starts higher.
TABLE_BODY_TOP = 100
INTRODUCTION_BODY_TOP = 65
BODY_BOTTOM = 535

# Include the table header text, which sits slightly above the matched rect.
TABLE_HEADER_MARGIN = 2

BODY_LEFT = COLUMN_BOUNDS["requirement"][0]
BODY_RIGHT = COLUMN_BOUNDS["guidance"][1]
