from __future__ import annotations

import io
import json
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import PROJECT_ROOT


class RunError(ValueError):
    pass


class RunManager:
    def __init__(self, config):
        self.active_run_id = None
        self.set_config(config)

    def set_config(self, config):
        self.config = config
        self.root = resolve_project_path(config["paths"]["runs_dir"])
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self):
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        run_dir = self._run_dir(run_id)
        pages_dir = run_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=False)
        manifest = {
            "run_id": run_id,
            "status": "open",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "pages": [],
            "errors": [],
        }
        self._write_manifest(run_id, manifest)
        self.active_run_id = run_id
        return manifest

    def get_run(self, run_id):
        manifest_path = self._manifest_path(run_id)
        if not manifest_path.exists():
            raise RunError("run not found")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def list_runs(self):
        """Summarise every run on disk, newest first.

        Sorted on created_at, not run_id: run_id only carries second
        resolution, so two runs made in the same second would tie on the
        timestamp and fall through to the random uuid suffix. A corrupt or
        half-written manifest is skipped rather than breaking the listing for
        every other run.
        """
        summaries = []
        for run_dir in self.root.iterdir():
            manifest_path = run_dir / "manifest.json"
            if not run_dir.is_dir() or not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            summaries.append(
                {
                    "run_id": manifest.get("run_id", run_dir.name),
                    "status": manifest.get("status", "unknown"),
                    "page_count": len(manifest.get("pages", [])),
                    "error_count": len(manifest.get("errors", [])),
                    "created_at": manifest.get("created_at"),
                    "updated_at": manifest.get("updated_at"),
                }
            )
        summaries.sort(key=lambda run: (run["created_at"] or "", run["run_id"]), reverse=True)
        return summaries

    def delete_all_runs(self):
        root = self.root.resolve()
        runs = []
        for run_dir in self.root.iterdir():
            manifest_path = run_dir / "manifest.json"
            if not run_dir.is_dir() or not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            resolved = run_dir.resolve()
            if resolved.parent != root:
                raise RunError("refusing to delete path outside runs directory")
            runs.append((run_dir, manifest.get("run_id", run_dir.name)))

        run_ids = [run_id for _, run_id in runs]
        for run_dir, _ in runs:
            shutil.rmtree(run_dir)
        self.active_run_id = None
        return {"deleted": len(run_ids), "run_ids": run_ids}

    def next_capture_path(self, run_id):
        manifest = self.get_run(run_id)
        if manifest["status"] not in {"open", "complete"}:
            raise RunError(f"run is {manifest['status']}")
        page_number = len(manifest["pages"]) + 1
        return self._pages_dir(run_id) / f"page_{page_number:03d}.jpg"

    def add_page(self, run_id, image_path):
        manifest = self.get_run(run_id)
        page_number = len(manifest["pages"]) + 1
        relative_path = str(image_path.relative_to(self._run_dir(run_id))).replace("\\", "/")
        manifest["pages"].append(
            {
                "page_number": page_number,
                "filename": image_path.name,
                "path": relative_path,
                "captured_at": utc_now(),
            }
        )
        manifest["status"] = "open"
        manifest["updated_at"] = utc_now()
        self._write_manifest(run_id, manifest)
        return manifest

    def add_error(self, run_id, operation, message):
        """Record a failed operation against the run.

        page_number is the page that was being attempted, matching
        next_capture_path()'s numbering.
        """
        manifest = self.get_run(run_id)
        manifest["errors"].append(
            {
                "operation": operation,
                "message": message,
                "page_number": len(manifest["pages"]) + 1,
                "occurred_at": utc_now(),
            }
        )
        self._write_manifest(run_id, manifest)
        return manifest

    def complete_run(self, run_id):
        manifest = self.get_run(run_id)
        if not manifest["pages"]:
            raise RunError("run has no captured pages")

        manifest["status"] = "complete"
        manifest["updated_at"] = utc_now()
        self._write_manifest(run_id, manifest)

        if self.active_run_id == run_id:
            self.active_run_id = None
        return manifest

    def build_archive(self, run_id):
        manifest = self.get_run(run_id)
        if not manifest["pages"]:
            raise RunError("run has no captured pages")

        buffer = io.BytesIO()
        # JPEGs are already compressed, so storing beats deflating on a Pi.
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            for page in manifest["pages"]:
                page_path = self._run_dir(run_id) / page["path"]
                if not page_path.exists():
                    raise RunError(f"missing page file: {page['filename']}")
                archive.write(page_path, f"{run_id}/{page['filename']}")
        return buffer.getvalue()

    def archive_filename(self, run_id):
        return f"{run_id}.zip"

    def public_manifest(self, run_id):
        return decorate_manifest(self.get_run(run_id))

    def _run_dir(self, run_id):
        if "/" in run_id or "\\" in run_id or run_id in {"", ".", ".."}:
            raise RunError("invalid run ID")
        return self.root / run_id

    def _pages_dir(self, run_id):
        return self._run_dir(run_id) / "pages"

    def _manifest_path(self, run_id):
        return self._run_dir(run_id) / "manifest.json"

    def _write_manifest(self, run_id, manifest):
        manifest["updated_at"] = utc_now()
        self._manifest_path(run_id).write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )


def decorate_manifest(manifest):
    """Add the response-only fields to a manifest.

    Shared by GET and POST response paths so the two shapes cannot drift.
    """
    manifest["page_count"] = len(manifest["pages"])
    if manifest["pages"]:
        manifest["archive_url"] = f"/api/runs/{manifest['run_id']}/archive"
    return manifest


def resolve_project_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def utc_now():
    return datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat()
