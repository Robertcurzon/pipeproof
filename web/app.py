"""Starlette web application for PipeProof."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from pipeproof.pipeline import run_pipeline
from pipeproof.store import ArtifactStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.getenv("PIPEPROOF_DATA_DIR", PROJECT_ROOT / "data/runtime"))
STORE_ROOT = RUNTIME_ROOT / "runs"
UPLOAD_ROOT = RUNTIME_ROOT / "uploads"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {".csv", ".parquet", ".json", ".jsonl"}

templates = Jinja2Templates(directory=PROJECT_ROOT / "web/templates")
store = ArtifactStore(STORE_ROOT)


def ensure_demo() -> None:
    """Create one deterministic incident replay for first-time visitors."""

    if store.list_runs():
        return
    run_pipeline(
        PROJECT_ROOT / "data/sample/nyc_311_incident.csv",
        PROJECT_ROOT / "data/sample/nyc_311_baseline.csv",
        store_root=STORE_ROOT,
        dataset_name="nyc_311_service_requests",
    )


def _view_model(run_id: str | None = None) -> dict[str, Any]:
    runs = store.list_runs()
    if not runs:
        return {"runs": [], "selected": None}
    selected_id = run_id or runs[0]["run_id"]
    try:
        selected = store.load_run(selected_id)
    except FileNotFoundError:
        selected = store.load_run(runs[0]["run_id"])
    validation = selected["validation"]
    selected["failed_checks"] = [item for item in validation["checks"] if not item["passed"]]
    selected["passed_checks"] = sum(item["passed"] for item in validation["checks"])
    selected["total_checks"] = len(validation["checks"])
    return {"runs": runs, "selected": selected}


async def homepage(request: Request) -> Response:
    """Render the latest or selected reliability run."""

    ensure_demo()
    model = _view_model(request.query_params.get("run"))
    return templates.TemplateResponse(request, "index.html", model)


async def _save_upload(upload: UploadFile, prefix: str) -> Path:
    filename = Path(upload.filename or "upload.csv").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Unsupported upload type: {suffix}")
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Uploads are limited to 25 MB in the public demo.")
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_ROOT / f"{prefix}-{secrets.token_hex(5)}{suffix}"
    destination.write_bytes(content)
    return destination


async def analyze(request: Request) -> Response:
    """Analyze uploaded baseline and current files."""

    form = await request.form()
    current = form.get("current")
    baseline = form.get("baseline")
    if not isinstance(current, UploadFile) or not current.filename:
        raise HTTPException(400, "Choose a current batch to analyze.")
    current_path = await _save_upload(current, "current")
    baseline_path = None
    if isinstance(baseline, UploadFile) and baseline.filename:
        baseline_path = await _save_upload(baseline, "baseline")
    dataset_name = str(form.get("dataset_name") or "uploaded_batch").strip()[:80]
    try:
        result = run_pipeline(
            current_path,
            baseline_path,
            store_root=STORE_ROOT,
            dataset_name=dataset_name,
        )
    finally:
        current_path.unlink(missing_ok=True)
        if baseline_path:
            baseline_path.unlink(missing_ok=True)
    return RedirectResponse(f"/?run={result.run_id}", status_code=303)


async def api_runs(request: Request) -> Response:
    """Return run manifests as JSON."""

    ensure_demo()
    return JSONResponse({"runs": store.list_runs()})


async def api_run(request: Request) -> Response:
    """Return one complete run report as JSON."""

    try:
        return JSONResponse(store.load_run(request.path_params["run_id"]))
    except FileNotFoundError as exc:
        raise HTTPException(404, "Run not found") from exc


async def download_artifact(request: Request) -> Response:
    """Download an accepted, quarantined, or contract artifact."""

    try:
        path = store.artifact_path(
            request.path_params["run_id"], request.path_params["filename"]
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, "Artifact not found") from exc
    return FileResponse(path, filename=path.name)


async def health(request: Request) -> Response:
    """Return a deploy-platform health response."""

    return JSONResponse({"status": "ok", "service": "pipeproof"})


routes = [
    Route("/", homepage),
    Route("/analyze", analyze, methods=["POST"]),
    Route("/api/runs", api_runs),
    Route("/api/runs/{run_id:str}", api_run),
    Route("/artifacts/{run_id:str}/{filename:str}", download_artifact),
    Route("/health", health),
    Mount("/static", app=StaticFiles(directory=PROJECT_ROOT / "web/static"), name="static"),
]

app = Starlette(
    debug=os.getenv("PIPEPROOF_DEBUG", "false").lower() == "true",
    routes=routes,
    middleware=[Middleware(GZipMiddleware, minimum_size=1000)],
)
