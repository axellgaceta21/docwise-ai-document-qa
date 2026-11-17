from dataclasses import dataclass

import pymupdf
from fastapi import HTTPException, UploadFile

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGES = 100


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


async def extract_pdf(upload: UploadFile) -> list[PageText]:
    if not upload.filename or not upload.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")
    data = await upload.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF exceeds the 10 MB limit")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "File is not a PDF")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
        with document:
            if document.is_encrypted:
                raise HTTPException(400, "Encrypted PDFs are not supported")
            if document.page_count > MAX_PAGES:
                raise HTTPException(413, "PDF exceeds the 100 page limit")
            return [PageText(page=index + 1, text=page.get_text("text")) for index, page in enumerate(document)]
    except HTTPException:
        raise
    except (pymupdf.FileDataError, ValueError) as exc:
        raise HTTPException(400, "PDF could not be read") from exc
