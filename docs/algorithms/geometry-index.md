# Geometry Index

The "geometry index" is a derived Phase 1 artifact that rearranges word/line geometry into a page-centric structure with stable IDs and a deterministic reading order.

Why it exists:
- resolvers and renderers usually operate page-by-page
- it is cheaper to consume than per-chunk geometry when mapping many highlights
- it provides a consistent place to attach metadata (chunk ids, sentence ids, etc.)

Key properties:
- stable, deterministic IDs (per-page line ids; global word ids)
- monotonic reading order (useful for windowing and debugging)
- bounding boxes are stored in absolute page coordinates; consumers can normalize as needed
