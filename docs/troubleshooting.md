# Troubleshooting

## No word geometry found

Common causes:
- `pymupdf` is not installed, or cannot load the PDF
- the PDF has no usable text layer (scanned image-only)

Fixes:
- enable OCR (`--ocr 1` or `OCR_ENABLED=1`) and ensure Tesseract is installed
- verify the PDF opens in standard PDF readers (corrupt PDFs often fail silently)
- if you expect Vision rails, confirm `GOOGLE_APPLICATION_CREDENTIALS` is set and `VISION_RAILS_DISABLE` is not `1`

## Provider parsing fails

- confirm the provider integration is enabled (`ADE_ENABLED=1`)
- confirm required keys are present in `.env` / environment variables

## Overlays drift between runs

Geometry is only stable when:
- you build artifacts against the exact same PDF bytes, and
- the same OCR/settings are used.

If you regenerate an OCR'ed derivative PDF, treat it as a distinct input with a new `doc_hash`.
