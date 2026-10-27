"""Errors with a code. Sinngam's routes turn them into the contract 05 error body and HTTP status."""


class IngestError(Exception):
    """An expected refusal: bad upload, illegal state change, missing object."""

    def __init__(self, code: str, http_status: int, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.detail}


# X1 (contract 10 section 3)
def unsupported_type(message: str) -> IngestError:
    return IngestError("UNSUPPORTED_TYPE", 422, message)


def file_too_large(size_mb: float, max_mb: int) -> IngestError:
    return IngestError("FILE_TOO_LARGE", 422, f"The file is {size_mb:.1f} MB; the limit is {max_mb} MB.")


def corrupt_file(message: str) -> IngestError:
    return IngestError("CORRUPT_FILE", 422, message)


def encrypted_pdf() -> IngestError:
    return IngestError("ENCRYPTED_PDF", 422, "The PDF is encrypted. Upload a copy without a password.")


def invalid_metadata(fields: dict[str, str]) -> IngestError:
    return IngestError("INVALID_METADATA", 422, "Some metadata fields are missing or wrong.", fields=fields)


def too_many_pages(message: str) -> IngestError:
    return IngestError("TOO_MANY_PAGES", 422, message)


def duplicate_document(document_id: str, title: str) -> IngestError:
    return IngestError("DUPLICATE_DOCUMENT", 409, f"This file is already indexed as '{title}'.",
                       document_id=document_id)


# lifecycle (contract 03)
def illegal_move(message: str) -> IngestError:
    return IngestError("ILLEGAL_MOVE", 409, message)


def not_found(what: str) -> IngestError:
    return IngestError("NOT_FOUND", 404, f"{what} not found.")
