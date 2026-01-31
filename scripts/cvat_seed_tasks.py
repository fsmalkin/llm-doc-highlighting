"""
Seed CVAT tasks for GT correction with per-doc prompts.

Default: parse docs/eval-review-2.md (bad cases) and create one task per doc.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List
import urllib.request
from urllib.parse import urlparse


def _api_request(method: str, url: str, user: str, password: str, payload: dict | None = None) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("utf-8")
    req.add_header("Authorization", f"Basic {token}")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        if not body:
            return {}
        return json.loads(body)


def _find_project(server: str, user: str, password: str, name: str) -> dict | None:
    data = _api_request("GET", f"{server}/api/projects?page_size=200", user, password)
    for proj in data.get("results", []):
        if proj.get("name") == name:
            return proj
    return None


def _list_tasks_for_project(server: str, user: str, password: str, project_id: int) -> List[int]:
    data = _api_request(
        "GET", f"{server}/api/tasks?page_size=200&project_id={project_id}", user, password
    )
    return [item.get("id") for item in data.get("results", []) if item.get("id")]


def _parse_eval_review(path: Path) -> Dict[str, List[dict]]:
    cases: List[dict] = []
    current: dict | None = None
    run_name = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("Run:"):
            m = re.search(r"`([^`]+)`", line)
            if m:
                run_name = m.group(1)
        m = re.match(r"^\d+\)\s+(.*)$", line)
        if m:
            if current:
                cases.append(current)
            current = {
                "field_label": m.group(1).strip(),
                "run": run_name,
            }
            continue
        if not current:
            continue
        if line.startswith("- Doc:"):
            current["doc_id"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Example id:"):
            current["example_id"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Expected:"):
            current["expected"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Raw:"):
            current["raw"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Indexed:"):
            current["indexed"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Link:"):
            current["link"] = line.split(":", 1)[1].strip()
    if current:
        cases.append(current)

    grouped: Dict[str, List[dict]] = {}
    for case in cases:
        doc_id = case.get("doc_id")
        if not doc_id:
            continue
        grouped.setdefault(doc_id, []).append(case)
    return grouped


def _find_image_path(images_dir: Path, doc_id: str) -> Path | None:
    for ext in [".png", ".jpg", ".jpeg", ".tif", ".tiff"]:
        candidate = images_dir / f"{doc_id}{ext}"
        if candidate.exists():
            return candidate
    # fallback: any file with doc_id prefix
    for candidate in images_dir.glob(f"{doc_id}.*"):
        if candidate.is_file():
            return candidate
    return None


def _build_guide(doc_id: str, cases: List[dict], base_guide: str) -> str:
    header = [
        "# Document prompt",
        "",
        f"Document: {doc_id}",
        "",
        "Your task: find the correct VALUE for each field label below.",
        "Draw one box around the value text (not the label) and fill in the attributes.",
        "",
    ]
    lines = header
    for idx, case in enumerate(cases, start=1):
        lines.append(f"## Prompt {idx}")
        lines.append(f"Field label: {case.get('field_label', '').strip()}")
        if case.get("expected"):
            lines.append(f"Expected (GT): {case.get('expected')}")
        if case.get("raw"):
            lines.append(f"Raw answer: {case.get('raw')}")
        if case.get("indexed"):
            lines.append(f"Indexed answer: {case.get('indexed')}")
        if case.get("example_id"):
            lines.append(f"Example id: {case.get('example_id')}")
        if case.get("run"):
            lines.append(f"Run: {case.get('run')}")
        if case.get("link"):
            lines.append(f"Eval link: {case.get('link')}")
        lines.append("")

    return base_guide.rstrip() + "\n\n---\n\n" + "\n".join(lines).strip() + "\n"


def _run_cli(args: List[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    out = (result.stdout or "").strip()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed CVAT tasks with per-doc prompts")
    ap.add_argument("--server", default="http://localhost:8080", help="CVAT server URL")
    ap.add_argument("--user", default="admin", help="CVAT username")
    ap.add_argument("--password", default="CvatAdmin123!", help="CVAT password")
    ap.add_argument("--project-name", default="FUNSD GT Corrections", help="CVAT project name")
    ap.add_argument(
        "--eval-review",
        default="docs/eval-review-2.md",
        help="Path to eval review markdown with cases",
    )
    ap.add_argument(
        "--images-dir",
        default="data/funsd/raw/dataset/testing_data/images",
        help="Directory containing FUNSD images",
    )
    ap.add_argument(
        "--labels",
        default="data/cvat/labels.json",
        help="Label spec JSON for CVAT project",
    )
    ap.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing tasks in the project before creating new ones",
    )
    args = ap.parse_args()

    server = args.server.rstrip("/")
    parsed = urlparse(server)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    user = args.user
    password = args.password

    project = _find_project(server, user, password, args.project_name)
    if not project:
        labels_path = Path(args.labels)
        if not labels_path.exists():
            raise SystemExit(f"Labels file not found: {labels_path}")
        out = _run_cli(
            [
                "cvat-cli",
                "--server-host",
                host,
                "--server-port",
                str(port),
                "--auth",
                f"{user}:{password}",
                "project",
                "create",
                args.project_name,
                "--labels",
                str(labels_path),
            ]
        )
        project_id = int(out.splitlines()[-1])
    else:
        project_id = int(project["id"])

    if args.reset:
        task_ids = _list_tasks_for_project(server, user, password, project_id)
        for task_id in task_ids:
            _run_cli(
                [
                    "cvat-cli",
                    "--server-host",
                    host,
                    "--server-port",
                    str(port),
                    "--auth",
                    f"{user}:{password}",
                    "task",
                    "delete",
                    str(task_id),
                ]
            )

    cases_by_doc = _parse_eval_review(Path(args.eval_review))
    images_dir = Path(args.images_dir)
    base_guide = Path("docs/cvat-guide.md").read_text(encoding="utf-8")

    for doc_id, cases in cases_by_doc.items():
        img_path = _find_image_path(images_dir, doc_id)
        if not img_path:
            print(f"Skipping {doc_id}: image not found in {images_dir}")
            continue
        task_name = f"FUNSD GT fix - {doc_id}"
        out = _run_cli(
            [
                "cvat-cli",
                "--server-host",
                host,
                "--server-port",
                str(port),
                "--auth",
                f"{user}:{password}",
                "task",
                "create",
                task_name,
                "local",
                str(img_path),
                "--project_id",
                str(project_id),
                "--image_quality",
                "100",
            ]
        )
        task_id = int(out.splitlines()[-1])
        guide_markdown = _build_guide(doc_id, cases, base_guide)
        _api_request(
            "POST",
            f"{server}/api/guides",
            user,
            password,
            {"task_id": task_id, "markdown": guide_markdown},
        )
        print(f"Created task {task_id} for {doc_id}")


if __name__ == "__main__":
    main()
