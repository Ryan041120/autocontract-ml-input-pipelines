"""Instantiate the P5V DTD split manifest without running profiling or training."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from PIL import Image


DOMAIN_SEPARATOR = "autocontract.p5v.dtd.partition1.split.v1"
EXPECTED_ARCHIVE_MD5 = "fff73e5086ae6bdbea199a49dfb8a4c1"
EXPECTED_AMENDMENT_SHA256 = "1ae35cf2f04b1822142485b942bf23c993861c0adc1ff14ad72cdc4cc92474ec"
EXPECTED_CLASSES = 47
EXPECTED_PER_OFFICIAL_SPLIT = 40
PROFILE_PER_CLASS = 10
EFFECT_PER_CLASS = 30


class ManifestError(RuntimeError):
    pass


def digest_file(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_official_list(path: Path) -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    seen = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, raw in enumerate(handle, start=1):
            relative = raw.strip().replace("\\", "/")
            if not relative or relative.startswith("/") or relative.count("/") != 1:
                raise ManifestError(f"invalid relative path at {path.name}:{line_number}")
            class_name, filename = relative.split("/", 1)
            if not class_name or not filename or class_name in {".", ".."} or ".." in filename.split("/"):
                raise ManifestError(f"unsafe relative path at {path.name}:{line_number}")
            if relative in seen:
                raise ManifestError(f"duplicate relative path in {path.name}: {relative}")
            seen.add(relative)
            rows.append((class_name, relative))
    return rows


def require_balanced(rows: Iterable[Tuple[str, str]], name: str) -> Dict[str, List[str]]:
    by_class: Dict[str, List[str]] = collections.defaultdict(list)
    for class_name, relative in rows:
        by_class[class_name].append(relative)
    if len(by_class) != EXPECTED_CLASSES:
        raise ManifestError(f"{name} class count {len(by_class)} != {EXPECTED_CLASSES}")
    bad = {key: len(value) for key, value in by_class.items() if len(value) != EXPECTED_PER_OFFICIAL_SPLIT}
    if bad:
        raise ManifestError(f"{name} is not 40-per-class: {bad}")
    return dict(by_class)


def split_key(class_name: str, canonical_relative_path: str) -> str:
    payload = "\0".join((DOMAIN_SEPARATOR, class_name, canonical_relative_path)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def image_record(
    images_root: Path,
    study_split: str,
    class_name: str,
    label: int,
    relative: str,
    key: str,
) -> dict:
    image_path = (images_root / relative).resolve(strict=True)
    image_path.relative_to(images_root.resolve(strict=True))
    size_bytes = image_path.stat().st_size
    sha256 = digest_file(image_path)
    with Image.open(image_path) as image:
        width, height = image.size
        image_format = image.format
        image_mode = image.mode
        image.verify()
    return {
        "study_split": study_split,
        "class_name": class_name,
        "label": label,
        "canonical_relative_path": relative,
        "split_key": key,
        "bytes": size_bytes,
        "sha256": sha256,
        "width": width,
        "height": height,
        "format": image_format,
        "source_mode": image_mode,
    }


def publish_write_once(output: Path, payload: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise ManifestError(f"refusing to replace existing output: {output}")
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=output.name + ".", suffix=".tmp", dir=output.parent, delete=False) as handle:
            temporary_name = handle.name
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_name, output)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def build_manifest(dataset_root: Path, archive: Path, amendment: Path) -> dict:
    dataset_root = dataset_root.resolve(strict=True)
    archive = archive.resolve(strict=True)
    amendment = amendment.resolve(strict=True)
    labels_root = dataset_root / "labels"
    images_root = dataset_root / "images"
    train_path = labels_root / "train1.txt"
    val_path = labels_root / "val1.txt"

    archive_md5 = digest_file(archive, "md5")
    if archive_md5 != EXPECTED_ARCHIVE_MD5:
        raise ManifestError(f"archive MD5 mismatch: {archive_md5}")
    amendment_sha256 = digest_file(amendment)
    if amendment_sha256 != EXPECTED_AMENDMENT_SHA256:
        raise ManifestError(f"amendment SHA-256 mismatch: {amendment_sha256}")

    train_by_class = require_balanced(read_official_list(train_path), "train1")
    val_by_class = require_balanced(read_official_list(val_path), "val1")
    classes = sorted(train_by_class)
    if classes != sorted(val_by_class):
        raise ManifestError("train1/val1 class sets differ")
    class_to_idx = {class_name: index for index, class_name in enumerate(classes)}

    records = []
    expected_paths = set()
    for class_name in classes:
        ranked = sorted(
            ((split_key(class_name, relative), relative) for relative in train_by_class[class_name]),
            key=lambda item: (item[0], item[1]),
        )
        profile = ranked[:PROFILE_PER_CLASS]
        effect = ranked[PROFILE_PER_CLASS:]
        if len(profile) != PROFILE_PER_CLASS or len(effect) != EFFECT_PER_CLASS:
            raise ManifestError(f"internal subdivision failed for {class_name}")
        for study_split, rows in (("profile_calibration", profile), ("effect_evaluation", effect)):
            for key, relative in rows:
                if relative in expected_paths:
                    raise ManifestError(f"relative path crosses splits: {relative}")
                expected_paths.add(relative)
                records.append(
                    image_record(images_root, study_split, class_name, class_to_idx[class_name], relative, key)
                )

    for class_name in classes:
        for relative in sorted(val_by_class[class_name]):
            if relative in expected_paths:
                raise ManifestError(f"relative path crosses splits: {relative}")
            expected_paths.add(relative)
            records.append(
                image_record(
                    images_root,
                    "task_validation",
                    class_name,
                    class_to_idx[class_name],
                    relative,
                    split_key(class_name, relative),
                )
            )

    pre_quarantine_counts = {"profile_calibration": 470, "effect_evaluation": 1410, "task_validation": 1880}
    actual_pre_counts = collections.Counter(record["study_split"] for record in records)
    if dict(actual_pre_counts) != pre_quarantine_counts:
        raise ManifestError(f"pre-quarantine study split counts differ: {dict(actual_pre_counts)}")

    by_content: Dict[str, List[dict]] = collections.defaultdict(list)
    for record in records:
        by_content[record["sha256"]].append(record)
    quarantine_groups = []
    quarantine_sha256 = set()
    for sha256, members in sorted(by_content.items()):
        member_splits = sorted({member["study_split"] for member in members})
        if len(member_splits) > 1:
            quarantine_sha256.add(sha256)
            quarantine_groups.append(
                {
                    "sha256": sha256,
                    "crosses_splits": member_splits,
                    "members": [
                        {
                            "study_split": member["study_split"],
                            "class_name": member["class_name"],
                            "label": member["label"],
                            "canonical_relative_path": member["canonical_relative_path"],
                        }
                        for member in members
                    ],
                }
            )
    records = [record for record in records if record["sha256"] not in quarantine_sha256]

    post_quarantine_counts = dict(collections.Counter(record["study_split"] for record in records))
    per_class_counts = {
        study_split: {
            class_name: sum(
                1
                for record in records
                if record["study_split"] == study_split and record["class_name"] == class_name
            )
            for class_name in classes
        }
        for study_split in pre_quarantine_counts
    }
    missing_classes = {
        study_split: [class_name for class_name, count in counts.items() if count == 0]
        for study_split, counts in per_class_counts.items()
        if any(count == 0 for count in counts.values())
    }
    if missing_classes:
        raise ManifestError(f"quarantine removed a class from an allowed split: {missing_classes}")

    post_content_owner: Dict[str, str] = {}
    for record in records:
        prior = post_content_owner.setdefault(record["sha256"], record["study_split"])
        if prior != record["study_split"]:
            raise ManifestError("cross-split content duplicate remains after quarantine")

    executable = Path(sys.executable).resolve(strict=True)
    generator = Path(__file__).resolve(strict=True)
    return {
        "schema_version": "autocontract.p5v-dtd-split-manifest.v1",
        "status": "instantiated_quarantined_no_profiling",
        "scientific_evidence": False,
        "profiling_executed": False,
        "training_executed": False,
        "test_accessed": False,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "dataset": {
            "name": "Describable Textures Dataset",
            "release": "r1.0.1",
            "official_partition": 1,
            "target": "category",
            "archive": {
                "name": archive.name,
                "bytes": archive.stat().st_size,
                "md5": archive_md5,
                "sha256": digest_file(archive),
            },
            "train1_sha256": digest_file(train_path),
            "val1_sha256": digest_file(val_path),
            "test1_policy": "forbidden_not_read",
        },
        "subdivision": {
            "domain_separator": DOMAIN_SEPARATOR,
            "algorithm": "per-class ascending (SHA256(domain+NUL+class+NUL+relative_path), relative_path)",
            "profile_per_class": PROFILE_PER_CLASS,
            "effect_per_class": EFFECT_PER_CLASS,
        },
        "duplicate_quarantine_amendment": {
            "path": "benchmark/final_v1/p5v_dtd_duplicate_quarantine_amendment_v1.json",
            "sha256": amendment_sha256,
            "rule": "quarantine every member of any exact content-SHA equivalence class crossing allowed splits; no move or replacement",
        },
        "class_to_idx": class_to_idx,
        "counts": {
            "pre_quarantine": pre_quarantine_counts,
            "post_quarantine": post_quarantine_counts,
            "post_quarantine_per_class": per_class_counts,
        },
        "quarantine": {
            "equivalence_class_count": len(quarantine_groups),
            "sample_count": sum(len(group["members"]) for group in quarantine_groups),
            "groups": quarantine_groups,
            "replacement_sampling": False,
            "samples_moved": False,
        },
        "isolation": {
            "allowed_splits_pairwise_disjoint": True,
            "allowed_splits_content_sha256_disjoint": True,
            "p5v_state_discard_required": True,
            "test_entries_included": False,
        },
        "generator": {
            "path": "experiments/autocontract_p5v_dtd_split_manifest.py",
            "sha256": digest_file(generator),
            "python_version": platform.python_version(),
            "python_executable": str(executable),
            "python_executable_sha256": digest_file(executable),
            "pillow_version": Image.__version__,
        },
        "samples": records,
        "claim_boundary": "Instantiated and duplicate-quarantined allowed-split identity manifest only; no P5V profiling, task training, test access, or scientific result.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--amendment", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = build_manifest(args.dataset_root, args.archive, args.amendment)
    publish_write_once(args.output.resolve(), payload)
    print(json.dumps({"output": str(args.output.resolve()), "samples": len(payload["samples"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
