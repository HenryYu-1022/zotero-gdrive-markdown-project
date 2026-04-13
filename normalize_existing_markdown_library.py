from __future__ import annotations

import argparse
from pathlib import Path

from paper_to_markdown.common import (
    bundle_dir_for_pdf,
    find_all_pdfs,
    load_config,
    manifest_path,
    markdown_root,
    pdf_fingerprint,
    raw_dir_for_pdf,
    relative_pdf_path,
    safe_rmtree,
    setup_logger,
    supporting_assets_dir_name,
    supporting_markdown_name,
    supporting_source_info,
    to_posix_path_str,
    update_frontmatter_fields,
)
from paper_to_markdown.pipeline import (
    ManifestStore,
    SUPPORTING_MARKDOWN_FILE_RE,
    _find_main_markdown_in_bundle,
    _iter_supporting_markdown_paths,
    _markdowns_are_near_duplicates,
    _merge_supporting_artifacts_into_bundle,
    _next_available_supporting_index,
    _path_match_key,
    _remove_supporting_markdown_artifacts,
    _repoint_manifest_output_markdown,
    build_manifest_runtime_metadata,
    dedupe_primary_markdown_bundle,
    dedupe_supporting_markdown_bundle,
    main_duplicate_group_pdfs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-time in-place migration for the existing markdown library.",
    )
    parser.add_argument(
        "--config",
        default="paper_to_markdown/settings.json",
        help="Path to settings.json.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only inspect the first N PDFs. Useful for testing.",
    )
    return parser


def rel_key_for_pdf(pdf_path: Path, input_root: Path) -> str:
    return str(relative_pdf_path(pdf_path, input_root)).replace("\\", "/")


def manifest_entry_for_pdf(manifest: ManifestStore, pdf_path: Path, input_root: Path) -> dict | None:
    return manifest.get(rel_key_for_pdf(pdf_path, input_root))


def resolve_canonical_main_pdf(
    pdf_path: Path,
    manifest: ManifestStore,
    input_root: Path,
) -> Path:
    current = pdf_path
    seen: set[Path] = set()

    while True:
        if current in seen:
            return current
        seen.add(current)

        entry = manifest_entry_for_pdf(manifest, current, input_root)
        if not entry or entry.get("status") != "success":
            return current

        canonical_source_pdf = str(entry.get("canonical_source_pdf", "")).strip()
        if not canonical_source_pdf:
            return current

        next_pdf = Path(canonical_source_pdf)
        if not next_pdf.exists():
            return current
        current = next_pdf


def resolve_canonical_main_output_pdf(
    pdf_path: Path,
    final_output_markdown: Path,
    manifest: ManifestStore,
    input_root: Path,
    config: dict,
) -> Path:
    final_output_key = _path_match_key(final_output_markdown)
    entry = manifest_entry_for_pdf(manifest, pdf_path, input_root)
    if entry and entry.get("status") == "success":
        canonical_source_pdf = str(entry.get("canonical_source_pdf", "")).strip()
        if canonical_source_pdf:
            candidate = Path(canonical_source_pdf)
            candidate_output = bundle_dir_for_pdf(candidate, input_root, config) / f"{candidate.stem}.md"
            if final_output_key == _path_match_key(candidate_output):
                return candidate

    own_output = bundle_dir_for_pdf(pdf_path, input_root, config) / f"{pdf_path.stem}.md"
    if final_output_key == _path_match_key(own_output):
        return pdf_path

    for candidate in main_duplicate_group_pdfs(pdf_path):
        candidate_output = bundle_dir_for_pdf(candidate, input_root, config) / f"{candidate.stem}.md"
        if final_output_key == _path_match_key(candidate_output):
            return candidate

    return pdf_path


def find_existing_output_markdown(
    pdf_path: Path,
    manifest: ManifestStore,
    input_root: Path,
    config: dict,
) -> Path | None:
    entry = manifest_entry_for_pdf(manifest, pdf_path, input_root)
    if entry and entry.get("status") == "success":
        output_markdown = str(entry.get("output_markdown", "")).strip()
        if output_markdown:
            output_path = Path(output_markdown)
            if output_path.exists():
                return output_path

    supporting_info = supporting_source_info(pdf_path)
    if supporting_info:
        standalone_bundle = bundle_dir_for_pdf(pdf_path, input_root, config)
        source_main_md = _find_main_markdown_in_bundle(standalone_bundle, pdf_path.stem)
        if source_main_md is not None and source_main_md.exists():
            return source_main_md

        primary_pdf, supporting_index = supporting_info
        canonical_primary_pdf = resolve_canonical_main_pdf(primary_pdf, manifest, input_root)
        primary_bundle = bundle_dir_for_pdf(canonical_primary_pdf, input_root, config)
        preferred_target = primary_bundle / supporting_markdown_name(supporting_index)
        if preferred_target.exists():
            return preferred_target

        candidates = _iter_supporting_markdown_paths(primary_bundle)
        if len(candidates) == 1:
            return candidates[0]
        return None

    bundle_dir = bundle_dir_for_pdf(pdf_path, input_root, config)
    return _find_main_markdown_in_bundle(bundle_dir, pdf_path.stem)


def update_supporting_frontmatter(
    markdown_path: Path,
    pdf_path: Path,
    primary_pdf: Path,
    supporting_index: int,
    input_root: Path,
) -> None:
    update_frontmatter_fields(
        markdown_path,
        {
            "document_role": "supporting",
            "supporting_index": supporting_index,
            "primary_source_pdf": to_posix_path_str(primary_pdf),
            "primary_source_relpath": to_posix_path_str(relative_pdf_path(primary_pdf, input_root)),
            "primary_source_filename": primary_pdf.name,
        },
    )


def move_standalone_supporting_bundle(
    pdf_path: Path,
    primary_pdf: Path,
    supporting_index: int,
    manifest: ManifestStore,
    input_root: Path,
    config: dict,
    logger,
    summary: dict[str, int],
) -> Path | None:
    source_bundle_dir = bundle_dir_for_pdf(pdf_path, input_root, config)
    target_bundle_dir = bundle_dir_for_pdf(primary_pdf, input_root, config)
    if source_bundle_dir == target_bundle_dir or not source_bundle_dir.exists():
        return None

    target_bundle_dir.mkdir(parents=True, exist_ok=True)
    source_main_md = _find_main_markdown_in_bundle(source_bundle_dir, pdf_path.stem)
    final_md: Path | None = None

    if source_main_md is not None and source_main_md.exists():
        normalized_cache: dict[Path, str] = {}
        matched_target: Path | None = None

        preferred_target = target_bundle_dir / supporting_markdown_name(supporting_index)
        if preferred_target.exists() and _markdowns_are_near_duplicates(
            source_main_md, preferred_target, normalized_cache,
        ):
            matched_target = preferred_target
        else:
            for candidate in _iter_supporting_markdown_paths(target_bundle_dir):
                if _markdowns_are_near_duplicates(source_main_md, candidate, normalized_cache):
                    matched_target = candidate
                    break

        if matched_target is not None:
            _repoint_manifest_output_markdown(manifest, source_main_md, matched_target)
            _remove_supporting_markdown_artifacts(source_main_md, config)
            final_md = matched_target
            summary["supporting_deduped"] += 1
            logger.info(
                "Merged standalone supporting markdown into existing supporting file: %s -> %s",
                source_main_md,
                matched_target,
            )
        else:
            target_index = supporting_index
            target_md = target_bundle_dir / supporting_markdown_name(target_index)
            target_assets = target_bundle_dir / supporting_assets_dir_name(target_index)
            if target_md.exists() or target_assets.exists():
                target_index = _next_available_supporting_index(target_bundle_dir)
                target_md = target_bundle_dir / supporting_markdown_name(target_index)
                target_assets = target_bundle_dir / supporting_assets_dir_name(target_index)

            source_assets = source_main_md.with_name(source_main_md.stem + "_assets")
            source_main_md.rename(target_md)
            if source_assets.exists():
                source_assets.rename(target_assets)

            update_supporting_frontmatter(
                target_md,
                pdf_path=pdf_path,
                primary_pdf=primary_pdf,
                supporting_index=target_index,
                input_root=input_root,
            )
            _repoint_manifest_output_markdown(manifest, source_main_md, target_md)
            final_md = target_md
            summary["supporting_moved"] += 1
            logger.info(
                "Moved standalone supporting markdown into primary bundle: %s -> %s",
                source_main_md,
                target_md,
            )

    _merge_supporting_artifacts_into_bundle(
        source_bundle_dir,
        target_bundle_dir,
        config,
        manifest,
        logger,
    )
    if source_bundle_dir.exists():
        safe_rmtree(source_bundle_dir, markdown_root(config))
        summary["bundles_removed"] += 1
        logger.info("Removed migrated standalone supporting bundle: %s", source_bundle_dir)

    if final_md is None:
        candidates = _iter_supporting_markdown_paths(target_bundle_dir)
        if candidates:
            final_md = candidates[0]

    if final_md is not None:
        final_md = dedupe_supporting_markdown_bundle(
            target_bundle_dir,
            final_md,
            config,
            manifest,
            logger,
        )
    return final_md


def normalize_manifest_entry(
    pdf_path: Path,
    output_markdown: Path,
    manifest: ManifestStore,
    input_root: Path,
    config: dict,
) -> None:
    old_entry = manifest_entry_for_pdf(manifest, pdf_path, input_root) or {}
    supporting_info = supporting_source_info(pdf_path)
    canonical_source_pdf = None if supporting_info else resolve_canonical_main_output_pdf(
        pdf_path, output_markdown, manifest, input_root, config,
    )

    if supporting_info:
        mirror_paths: list[str] = []
    elif canonical_source_pdf is not None and canonical_source_pdf != pdf_path:
        mirror_paths = []
    else:
        mirror_paths = list(old_entry.get("mirror_paths", []))

    metadata = build_manifest_runtime_metadata(
        pdf_path,
        input_root,
        output_markdown,
        mirror_paths,
        config,
        canonical_source_pdf=canonical_source_pdf,
    )
    manifest.mark_success(
        rel_key=rel_key_for_pdf(pdf_path, input_root),
        fingerprint=pdf_fingerprint(pdf_path, use_sha256=config.get("compute_sha256", False)),
        source_pdf=pdf_path,
        output_markdown=output_markdown,
        raw_dir=raw_dir_for_pdf(pdf_path, input_root, config),
        metadata=metadata,
    )


def migrate_existing_markdown_library(config_path: str, limit: int | None = None) -> dict[str, int]:
    config = load_config(config_path)
    logger = setup_logger(config, logger_name="paper_to_markdown.normalize_existing")
    input_root = Path(config["input_root"])
    manifest = ManifestStore(manifest_path(config))

    pdfs = find_all_pdfs(input_root)
    if limit is not None:
        pdfs = pdfs[:limit]

    summary = {
        "pdfs_seen": len(pdfs),
        "main_groups_checked": 0,
        "main_groups_merged": 0,
        "supporting_moved": 0,
        "supporting_deduped": 0,
        "supporting_bundles_checked": 0,
        "bundles_removed": 0,
        "manifest_entries_normalized": 0,
        "missing_outputs": 0,
    }

    processed_duplicate_roots: set[Path] = set()
    for pdf_path in pdfs:
        if supporting_source_info(pdf_path):
            continue

        group = main_duplicate_group_pdfs(pdf_path)
        group_root = group[0].resolve()
        if group_root in processed_duplicate_roots:
            continue
        processed_duplicate_roots.add(group_root)
        summary["main_groups_checked"] += 1

        existing_group_markdowns: list[tuple[Path, Path]] = []
        for candidate_pdf in group:
            candidate_md = find_existing_output_markdown(candidate_pdf, manifest, input_root, config)
            if candidate_md is None or not candidate_md.exists():
                continue
            if SUPPORTING_MARKDOWN_FILE_RE.fullmatch(candidate_md.name):
                continue
            existing_group_markdowns.append((candidate_pdf, candidate_md))

        if len(existing_group_markdowns) < 2:
            continue

        anchor_pdf, anchor_md = existing_group_markdowns[0]
        before_existing = {
            bundle_dir_for_pdf(candidate_pdf, input_root, config)
            for candidate_pdf, _candidate_md in existing_group_markdowns
            if bundle_dir_for_pdf(candidate_pdf, input_root, config).exists()
        }
        final_md, canonical_pdf = dedupe_primary_markdown_bundle(
            current_pdf=anchor_pdf,
            current_markdown_path=anchor_md,
            input_root=input_root,
            config=config,
            manifest=manifest,
            logger=logger,
        )
        after_existing = {
            bundle_dir_for_pdf(candidate_pdf, input_root, config)
            for candidate_pdf, _candidate_md in existing_group_markdowns
            if bundle_dir_for_pdf(candidate_pdf, input_root, config).exists()
        }
        if canonical_pdf != anchor_pdf or len(after_existing) < len(before_existing):
            summary["main_groups_merged"] += 1
            logger.info("Main duplicate group normalized to canonical markdown: %s", final_md)

    for pdf_path in pdfs:
        supporting_info = supporting_source_info(pdf_path)
        if not supporting_info:
            continue

        summary["supporting_bundles_checked"] += 1
        primary_pdf, supporting_index = supporting_info
        canonical_primary_pdf = resolve_canonical_main_pdf(primary_pdf, manifest, input_root)
        move_standalone_supporting_bundle(
            pdf_path=pdf_path,
            primary_pdf=canonical_primary_pdf,
            supporting_index=supporting_index,
            manifest=manifest,
            input_root=input_root,
            config=config,
            logger=logger,
            summary=summary,
        )

    supporting_bundle_dirs: set[Path] = set()
    for pdf_path in pdfs:
        supporting_info = supporting_source_info(pdf_path)
        if not supporting_info:
            continue
        primary_pdf, _supporting_index = supporting_info
        canonical_primary_pdf = resolve_canonical_main_pdf(primary_pdf, manifest, input_root)
        supporting_bundle_dirs.add(bundle_dir_for_pdf(canonical_primary_pdf, input_root, config))

    for bundle_dir in sorted(supporting_bundle_dirs):
        candidates = _iter_supporting_markdown_paths(bundle_dir)
        if len(candidates) < 2:
            continue
        dedupe_supporting_markdown_bundle(
            bundle_dir,
            candidates[-1],
            config,
            manifest,
            logger,
        )

    for pdf_path in pdfs:
        output_markdown = find_existing_output_markdown(pdf_path, manifest, input_root, config)
        if output_markdown is None or not output_markdown.exists():
            summary["missing_outputs"] += 1
            logger.warning("Could not determine normalized markdown output for PDF: %s", pdf_path)
            continue

        normalize_manifest_entry(
            pdf_path=pdf_path,
            output_markdown=output_markdown,
            manifest=manifest,
            input_root=input_root,
            config=config,
        )
        summary["manifest_entries_normalized"] += 1

    logger.info("Existing markdown library normalization finished: %s", summary)
    return summary


def main() -> None:
    args = build_parser().parse_args()
    summary = migrate_existing_markdown_library(args.config, limit=args.limit)
    print(summary)


if __name__ == "__main__":
    main()
