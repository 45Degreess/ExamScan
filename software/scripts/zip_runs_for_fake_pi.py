"""
Zip up a folder of raw run directories (run_id/pages/*.jpg, as produced by the
real Pi rig or software/runs.py) into <run_id>.zip archives that
scripts/fake_pi_server.py can serve.

fake_pi_server.py only looks for *.zip files directly inside the folder you
point it at; this converts a folder of unzipped run directories into that
shape, one flat zip per run (images directly at the top level, ZIP_STORED
since JPEGs are already compressed).

Usage:
    python3 scripts/zip_runs_for_fake_pi.py <src_dir_of_run_folders> <dest_dir_for_zips>

Example:
    python3 scripts/zip_runs_for_fake_pi.py sample_images/tester sample_images/tester_zips
    make collect-runs SESSION_CODE=Poster RUNS_FOLDER=sample_images/tester_zips
"""
import sys
import zipfile
from pathlib import Path

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def zip_run(run_dir: Path, dest_dir: Path) -> Path:
    pages_dir = run_dir / "pages"
    source_dir = pages_dir if pages_dir.is_dir() else run_dir
    images = sorted(
        p for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )
    if not images:
        raise ValueError(f"No images found under {source_dir}")

    zip_path = dest_dir / f"{run_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for img in images:
            zf.write(img, arcname=img.name)
    return zip_path


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    src_dir = Path(sys.argv[1])
    dest_dir = Path(sys.argv[2])
    if not src_dir.is_dir():
        print(f"Not a directory: {src_dir}")
        sys.exit(1)
    dest_dir.mkdir(parents=True, exist_ok=True)

    run_dirs = sorted(p for p in src_dir.iterdir() if p.is_dir())
    if not run_dirs:
        print(f"No run subdirectories found in {src_dir}")
        sys.exit(1)

    zipped = 0
    for run_dir in run_dirs:
        try:
            zip_path = zip_run(run_dir, dest_dir)
        except ValueError as exc:
            print(f"skipped {run_dir.name}: {exc}")
            continue
        print(f"wrote {zip_path}")
        zipped += 1

    print(f"\n{zipped}/{len(run_dirs)} run(s) zipped into {dest_dir}")


if __name__ == "__main__":
    main()
