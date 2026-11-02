"""Extraction error that says where in the PDF the problem occurred."""

EXCERPT_LIMIT = 200


class ExtractionError(ValueError):
    """A layout or content problem tied to a place in the PDF.

    Location fields may be filled in by a caller further up the stack, so the
    message is built lazily.
    """

    def __init__(
        self,
        message: str,
        *,
        page: int | None = None,
        pages: list[int] | None = None,
        requirement_id: str | None = None,
        column: str | None = None,
        excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.page = page
        self.pages = pages
        self.requirement_id = requirement_id
        self.column = column
        self.excerpt = excerpt

    def __str__(self) -> str:
        location = []

        if self.page is not None:
            location.append(f"PDF page {self.page}")
        elif self.pages:
            location.append(
                f"PDF pages {self.pages[0]}-{self.pages[-1]}"
                if len(self.pages) > 1
                else f"PDF page {self.pages[0]}"
            )

        if self.requirement_id is not None:
            location.append(f"requirement {self.requirement_id}")

        if self.column is not None:
            location.append(f"{self.column} column")

        text = (
            f"{', '.join(location)}: {self.message}"
            if location
            else self.message[:1].upper() + self.message[1:]
        )

        if self.excerpt is not None:
            excerpt = self.excerpt
            if len(excerpt) > EXCERPT_LIMIT:
                excerpt = excerpt[:EXCERPT_LIMIT] + "..."
            text += f"\n  text: {excerpt!r}"

        return text


class ChunkingError(ValueError):
    """An extracted record that cannot be turned into chunks without losing text."""

    def __init__(self, message: str, *, requirement_id: str | None = None) -> None:
        super().__init__(message)
        self.requirement_id = requirement_id

    def __str__(self) -> str:
        prefix = (
            f"requirement {self.requirement_id}: "
            if self.requirement_id is not None
            else ""
        )
        return prefix + super().__str__()
