#!/usr/bin/env python3
"""
iCloud Drive File Tagger (v2 — batched for speed)
Tags files in iCloud Drive using macOS Finder tags.
Uses the `tag` CLI tool (brew install tag).

Optimized: Groups files by tag-set and applies in batches.
~100x faster than per-file tagging.
"""

import os
import sys
import subprocess
import json
import logging
from datetime import datetime
from collections import defaultdict

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Optional: Pillow for image analysis
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("WARNING: Pillow not installed. Skipping transparency/resolution detection.")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ICLOUD_ROOT = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs"
)

LOG_DIR = os.path.expanduser("~/DEV/icloud-tagger/logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(
    LOG_DIR, f"tagger_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)

stats = defaultdict(int)

# Batch size for tag CLI calls
BATCH_SIZE = 50  # files per tag command

# ---------------------------------------------------------------------------
# Axis 1: Content Type
# ---------------------------------------------------------------------------

EXTENSION_TO_TYPE = {
    ".jpg": "Photo", ".jpeg": "Photo", ".png": "Photo", ".gif": "Photo",
    ".cr2": "Photo", ".webp": "Photo", ".heic": "Photo", ".tiff": "Photo",
    ".tif": "Photo", ".bmp": "Photo", ".raw": "Photo", ".nef": "Photo",
    ".arw": "Photo", ".dng": "Photo",
    ".pdf": "Document", ".doc": "Document", ".docx": "Document",
    ".txt": "Document", ".rtf": "Document", ".odt": "Document",
    ".pages": "Document",
    ".key": "Presentation", ".pptx": "Presentation", ".ppt": "Presentation",
    ".odp": "Presentation",
    ".mov": "Video", ".mp4": "Video", ".avi": "Video", ".mkv": "Video",
    ".m4v": "Video", ".wmv": "Video", ".flv": "Video",
    ".mp3": "Audio", ".m4a": "Audio", ".wav": "Audio", ".aac": "Audio",
    ".flac": "Audio", ".ogg": "Audio", ".wma": "Audio", ".aiff": "Audio",
    ".xls": "Spreadsheet", ".xlsx": "Spreadsheet", ".csv": "Spreadsheet",
    ".numbers": "Spreadsheet", ".ods": "Spreadsheet",
    ".psd": "Design", ".ai": "Design", ".indd": "Design", ".svg": "Design",
    ".sketch": "Design", ".fig": "Design", ".xd": "Design",
    ".afdesign": "Design", ".afphoto": "Design",
}

TYPE_TO_COLOR = {
    "Photo": "Blue", "Document": "Red", "Presentation": "Purple",
    "Video": "Green", "Audio": "Orange", "Spreadsheet": "Yellow",
    "Design": "Gray",
}

# ---------------------------------------------------------------------------
# Axis 2: Context/Project
# ---------------------------------------------------------------------------

FOLDER_TO_CONTEXT = [
    ("buisness elad", ("Business",)),
    ("my business", ("Business",)),
    ("business", ("Business",)),
    ("קורס אנבאונס", ("Course",)),
    ("קורס זוגיות", ("Course",)),
    ("לימוד קורסים", ("Course",)),
    ("course", ("Course",)),
    ("סידורים/ביטוח", ("Personal", "Finance")),
    ("סידורים/בנק", ("Personal", "Finance")),
    ("סידורים/בריאות", ("Personal",)),
    ("סידורים/רכישות", ("Personal",)),
    ("סידורים", ("Personal",)),
    ("בריאות", ("Personal",)),
    ("צהל", ("Personal", "Archive")),
    ("אוניברסיטה פתוחה", ("Personal", "Archive")),
    ("כספים", ("Finance",)),
    ("חשבונות", ("Finance",)),
    ("finance", ("Finance",)),
    ("tax", ("Finance",)),
    ("lecture-outreach", ("Lecture",)),
    ("image-bank", ("Lecture", "Graphic-Asset")),
    ("הרצאות", ("Lecture",)),
    ("מצגות סדנאות", ("Lecture",)),
    ("podcast", ("Podcast",)),
    ("icf", ("Podcast",)),
    ("לוגו", ("Graphic-Asset",)),
    ("logo", ("Graphic-Asset",)),
    ("graphics", ("Graphic-Asset",)),
    ("backgrounds", ("Graphic-Asset",)),
    ("templates", ("Graphic-Asset",)),
    ("archive", ("Archive",)),
    ("ארכיון", ("Archive",)),
    ("backup", ("Archive",)),
    ("documents - macbook air", ("Archive",)),
    ("סטנדאפ", ("Personal",)),
    ("pictures icloud", ("Personal",)),
    ("תמונות", ("Personal",)),
    ("music icloud", ("Personal",)),
    ("movies icloud", ("Personal",)),
    (".cmproj", ("Video", "Course")),
    ("zoom", ("Business",)),
    ("תמלול פגישות", ("Business",)),
]

# ---------------------------------------------------------------------------
# Technical detection
# ---------------------------------------------------------------------------

HI_RES_THRESHOLD = 2000
LO_RES_THRESHOLD = 800
RAW_EXTENSIONS = {".cr2", ".raw", ".nef", ".arw", ".dng"}
IMAGE_ANALYSIS_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg", ".gif",
                              ".tiff", ".tif", ".bmp", ".heic", ".psd"}

SKIPPED_DIRS = {".Trash", ".git", "__pycache__", "node_modules"}


def is_local_file(filepath):
    """Check if an iCloud file is actually downloaded locally (not a stub)."""
    try:
        # iCloud files that aren't downloaded have 0 data blocks
        stat = os.stat(filepath)
        # If file size > 0 but blocks = 0, it's a cloud-only stub
        if stat.st_size > 0 and stat.st_blocks == 0:
            return False
        return True
    except (OSError, AttributeError):
        return True  # Assume local if we can't check


def analyze_image(filepath, ext):
    """Analyze image for transparency and resolution. Returns extra tags."""
    if not HAS_PILLOW:
        return []

    # Skip cloud-only files (would hang trying to download)
    if not is_local_file(filepath):
        return []

    tags = []
    try:
        with Image.open(filepath) as img:
            w, h = img.size
            max_dim = max(w, h)

            # Resolution
            if max_dim >= HI_RES_THRESHOLD:
                tags.append("Hi-Res")
            elif max_dim < LO_RES_THRESHOLD:
                tags.append("Lo-Res")

            # Transparency (only PNG/WEBP)
            if ext in (".png", ".webp"):
                if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                    tags.append("Transparent")
    except Exception:
        pass
    return tags


# ---------------------------------------------------------------------------
# Phase 1: Collect all files and compute tags
# ---------------------------------------------------------------------------

def collect_files(skip_image_analysis=False):
    """Walk iCloud Drive and compute tags for each file. No tagging yet."""
    logger.info(f"Phase 1: Collecting files from {ICLOUD_ROOT}")
    if skip_image_analysis:
        logger.info("  Image analysis SKIPPED (fast mode)")

    # tag_set_string -> [list of filepaths]
    tag_batches = defaultdict(list)
    file_count = 0
    analyzed_images = 0

    for root, dirs, files in os.walk(ICLOUD_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS and not d.startswith(".")]

        for filename in files:
            if filename.startswith(".") or filename == "Icon\r":
                continue
            if filename.endswith(".icloud"):
                stats["skipped_icloud"] += 1
                continue

            filepath = os.path.join(root, filename)

            try:
                size = os.path.getsize(filepath)
                if size < 100:
                    stats["skipped_small"] += 1
                    continue
            except OSError:
                continue

            file_count += 1
            ext = os.path.splitext(filename)[1].lower()
            rel_path = os.path.relpath(filepath, ICLOUD_ROOT).lower()

            tags = set()

            # --- Axis 1: Content Type ---
            content_type = EXTENSION_TO_TYPE.get(ext)
            if content_type:
                tags.add(content_type)
                color = TYPE_TO_COLOR.get(content_type)
                if color:
                    tags.add(color)
                stats[f"type_{content_type}"] += 1

            # --- Axis 2: Context/Project ---
            for pattern, context_tags in FOLDER_TO_CONTEXT:
                if pattern in rel_path:
                    tags.update(context_tags)
                    break

            # --- Axis 7: Technical (images) ---
            if not skip_image_analysis and content_type in ("Photo", "Design") and ext in IMAGE_ANALYSIS_EXTENSIONS:
                extra = analyze_image(filepath, ext)
                tags.update(extra)
                analyzed_images += 1
                for t in extra:
                    stats[f"tech_{t}"] += 1

            # --- Axis 8: Utility ---
            if ext in RAW_EXTENSIONS:
                tags.add("Raw")
                stats["raw"] += 1

            # Group by tag set for batching
            if tags:
                tag_key = ",".join(sorted(tags))
                tag_batches[tag_key].append(filepath)

            stats["files_processed"] += 1

            if file_count % 2000 == 0:
                logger.info(f"  Collected: {file_count} files, {analyzed_images} images analyzed...")
                print(f"  Collected: {file_count} files, {analyzed_images} images analyzed...")

    logger.info(f"Phase 1 complete: {file_count} files, {len(tag_batches)} unique tag combinations")
    print(f"\n  Phase 1 complete:")
    print(f"    Files collected: {file_count:,}")
    print(f"    Images analyzed: {analyzed_images:,}")
    print(f"    Unique tag combos: {len(tag_batches):,}")
    return tag_batches


# ---------------------------------------------------------------------------
# Phase 2: Batch-apply tags
# ---------------------------------------------------------------------------

def apply_tags_batched(tag_batches, dry_run=False):
    """Apply tags in batches. Each unique tag-set is one batch."""
    logger.info(f"Phase 2: Applying tags ({'DRY RUN' if dry_run else 'LIVE'})")

    total_files = sum(len(files) for files in tag_batches.values())
    tagged_count = 0
    batch_count = 0

    for tag_str, filepaths in tag_batches.items():
        # Split into sub-batches of BATCH_SIZE
        for i in range(0, len(filepaths), BATCH_SIZE):
            batch = filepaths[i:i + BATCH_SIZE]
            batch_count += 1

            if dry_run:
                tagged_count += len(batch)
                continue

            try:
                cmd = ["tag", "-a", tag_str] + batch
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    tagged_count += len(batch)
                    stats["tags_applied"] += len(batch)
                else:
                    # Fallback: try one by one
                    for fp in batch:
                        try:
                            r = subprocess.run(
                                ["tag", "-a", tag_str, fp],
                                capture_output=True, text=True, timeout=5
                            )
                            if r.returncode == 0:
                                tagged_count += 1
                                stats["tags_applied"] += 1
                            else:
                                stats["errors"] += 1
                        except Exception:
                            stats["errors"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.warning(f"Batch error: {e}")

            if batch_count % 100 == 0:
                pct = tagged_count / total_files * 100 if total_files else 0
                logger.info(f"  Progress: {tagged_count:,}/{total_files:,} ({pct:.0f}%)")
                print(f"  Progress: {tagged_count:,}/{total_files:,} ({pct:.0f}%)")

    logger.info(f"Phase 2 complete: {tagged_count:,} files tagged in {batch_count} batches")
    print(f"\n  Phase 2 complete:")
    print(f"    Files tagged: {tagged_count:,}")
    print(f"    Batches: {batch_count:,}")
    print(f"    Errors: {stats['errors']:,}")


# ---------------------------------------------------------------------------
# Phase 3: Alias creation
# ---------------------------------------------------------------------------

CREATIVE_ASSETS_ROOT = os.path.expanduser("~/Creative-Assets")

ALIAS_STRUCTURE = {
    "Keynote": [
        "Logos", "Backgrounds", "Headshots", "Icons-Graphics",
        "Templates", "Photos-Content"
    ],
    "Video-Editing": [
        "Logos", "Backgrounds", "Music", "Sound-FX",
        "Lower-Thirds", "Intros-Outros", "B-Roll", "Motion-Projects"
    ],
    "Lectures": [
        "Speaker-Photos", "Slides", "Handouts",
        "Certificates", "Promo-Materials"
    ],
    "Web-Content": [
        "Featured-Images", "Thumbnails", "Banners", "Social-Media"
    ],
    "Podcast": [
        "Cover-Art", "Guest-Photos", "Episode-Assets", "Promo"
    ],
    "Finance-Course": [
        "Slides", "Handouts", "Marketing", "Certificates"
    ],
    "Social-Media": [
        "Templates", "Quotes", "Thumbnails", "Brand-Elements"
    ],
    "Documents": [
        "Business-CV", "Contracts", "Insurance", "Tax", "Certificates"
    ],
}


def create_alias_structure():
    """Create ~/Creative-Assets/ directory tree."""
    created = 0
    for workflow, subfolders in ALIAS_STRUCTURE.items():
        for subfolder in subfolders:
            path = os.path.join(CREATIVE_ASSETS_ROOT, workflow, subfolder)
            os.makedirs(path, exist_ok=True)
            created += 1
    logger.info(f"Created {created} alias directories")
    print(f"  Created {created} alias directories under ~/Creative-Assets/")
    return created


def create_symlink(source, alias_dir):
    """Create a symbolic link (faster than macOS Finder alias)."""
    alias_name = os.path.basename(source)
    alias_path = os.path.join(alias_dir, alias_name)

    if os.path.exists(alias_path) or os.path.islink(alias_path):
        return False

    try:
        os.symlink(source, alias_path)
        stats["aliases_created"] += 1
        return True
    except Exception as e:
        logger.warning(f"Symlink error for {source}: {e}")
        stats["alias_errors"] += 1
        return False


def find_files_by_tag(tag_name):
    """Find files with a specific tag using `tag -f`."""
    try:
        result = subprocess.run(
            ["tag", "-f", tag_name, ICLOUD_ROOT],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return []
    except Exception:
        return []


def populate_aliases():
    """Populate alias folders based on tags."""
    logger.info("Phase 3: Populating alias folders...")
    print("\n  Phase 3: Populating alias folders...")

    CA = CREATIVE_ASSETS_ROOT

    # --- Known high-value assets from lecture-outreach/image-bank ---
    image_bank = os.path.expanduser("~/DEV/lecture-outreach/image-bank")
    if os.path.isdir(image_bank):
        for root, dirs, files in os.walk(image_bank):
            for fname in files:
                if fname.startswith(".") or fname.endswith(".md"):
                    continue
                fpath = os.path.join(root, fname)
                subfolder = os.path.basename(root)

                if subfolder == "profile":
                    create_symlink(fpath, f"{CA}/Lectures/Speaker-Photos")
                    create_symlink(fpath, f"{CA}/Keynote/Headshots")
                    create_symlink(fpath, f"{CA}/Web-Content/Featured-Images")
                elif subfolder == "lectures":
                    create_symlink(fpath, f"{CA}/Lectures/Promo-Materials")
                    create_symlink(fpath, f"{CA}/Keynote/Photos-Content")
                elif subfolder == "documents":
                    create_symlink(fpath, f"{CA}/Lectures/Handouts")
                    create_symlink(fpath, f"{CA}/Documents/Business-CV")
                elif subfolder == "presentations":
                    create_symlink(fpath, f"{CA}/Lectures/Slides")
                    create_symlink(fpath, f"{CA}/Finance-Course/Slides")

    # --- Tag-based alias population ---
    print("  Searching for Graphic-Asset files...")
    graphic_files = find_files_by_tag("Graphic-Asset")
    print(f"    Found {len(graphic_files)} Graphic-Asset files")
    for f in graphic_files:
        ext = os.path.splitext(f)[1].lower()
        if ext in (".png", ".webp", ".svg"):
            create_symlink(f, f"{CA}/Keynote/Logos")
            create_symlink(f, f"{CA}/Video-Editing/Logos")
            create_symlink(f, f"{CA}/Social-Media/Brand-Elements")
        if ext in (".psd", ".ai", ".svg"):
            create_symlink(f, f"{CA}/Keynote/Icons-Graphics")
        if ext in (".jpg", ".jpeg", ".png") and "background" in f.lower():
            create_symlink(f, f"{CA}/Keynote/Backgrounds")
            create_symlink(f, f"{CA}/Video-Editing/Backgrounds")

    print("  Searching for Lecture files...")
    lecture_files = find_files_by_tag("Lecture")
    print(f"    Found {len(lecture_files)} Lecture files")
    for f in lecture_files:
        ext = os.path.splitext(f)[1].lower()
        ct = EXTENSION_TO_TYPE.get(ext, "")
        if ct == "Presentation":
            create_symlink(f, f"{CA}/Lectures/Slides")
            create_symlink(f, f"{CA}/Keynote/Templates")
        elif ct == "Document":
            create_symlink(f, f"{CA}/Lectures/Handouts")
        elif ct == "Photo":
            create_symlink(f, f"{CA}/Lectures/Speaker-Photos")
            create_symlink(f, f"{CA}/Keynote/Headshots")

    print("  Searching for Course files...")
    course_files = find_files_by_tag("Course")
    print(f"    Found {len(course_files)} Course files")
    for f in course_files:
        ext = os.path.splitext(f)[1].lower()
        ct = EXTENSION_TO_TYPE.get(ext, "")
        if ct == "Presentation":
            create_symlink(f, f"{CA}/Finance-Course/Slides")
        elif ct == "Document":
            create_symlink(f, f"{CA}/Finance-Course/Handouts")
        elif ct == "Video":
            create_symlink(f, f"{CA}/Video-Editing/B-Roll")

    print("  Searching for Business documents...")
    business_files = find_files_by_tag("Business")
    print(f"    Found {len(business_files)} Business files")
    for f in business_files:
        ext = os.path.splitext(f)[1].lower()
        ct = EXTENSION_TO_TYPE.get(ext, "")
        bn = os.path.basename(f).lower()
        if ct == "Document":
            if any(kw in bn for kw in ["cv", "resume", "קורות"]):
                create_symlink(f, f"{CA}/Documents/Business-CV")
            elif any(kw in bn for kw in ["contract", "חוזה", "הסכם"]):
                create_symlink(f, f"{CA}/Documents/Contracts")

    print("  Searching for Finance documents...")
    finance_files = find_files_by_tag("Finance")
    print(f"    Found {len(finance_files)} Finance files")
    for f in finance_files:
        ext = os.path.splitext(f)[1].lower()
        ct = EXTENSION_TO_TYPE.get(ext, "")
        rel = os.path.relpath(f, ICLOUD_ROOT).lower()
        if ct == "Document":
            if any(kw in rel for kw in ["ביטוח", "insurance", "פוליס"]):
                create_symlink(f, f"{CA}/Documents/Insurance")
            elif any(kw in rel for kw in ["מס", "tax"]):
                create_symlink(f, f"{CA}/Documents/Tax")

    # Audio for video editing
    print("  Searching for Audio files...")
    audio_files = find_files_by_tag("Audio")
    print(f"    Found {len(audio_files)} Audio files")
    for f in audio_files:
        bn = os.path.basename(f).lower()
        rel = os.path.relpath(f, ICLOUD_ROOT).lower()
        if any(kw in bn or kw in rel for kw in ["jingle", "intro", "outro", "opening", "פתיחה", "סגירה"]):
            create_symlink(f, f"{CA}/Video-Editing/Intros-Outros")
        elif any(kw in rel for kw in ["music", "מוזיקה"]):
            create_symlink(f, f"{CA}/Video-Editing/Music")

    # Cinemagraph / motion projects
    print("  Searching for motion projects...")
    for root, dirs, files in os.walk(ICLOUD_ROOT):
        for d in dirs:
            if d.endswith(".cmproj"):
                create_symlink(
                    os.path.join(root, d),
                    f"{CA}/Video-Editing/Motion-Projects"
                )

    print(f"\n  Phase 3 complete: {stats['aliases_created']} aliases created")
    logger.info(f"Phase 3 complete: {stats['aliases_created']} aliases created")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report():
    print("\n" + "=" * 60)
    print("  iCloud Drive Tagger — Summary Report")
    print("=" * 60)
    print(f"  Files processed:    {stats['files_processed']:,}")
    print(f"  Files tagged:       {stats.get('tags_applied', 0):,}")
    print(f"  Aliases created:    {stats['aliases_created']:,}")
    print(f"  Errors:             {stats['errors']:,}")
    print(f"  Skipped (iCloud):   {stats['skipped_icloud']:,}")
    print(f"  Skipped (small):    {stats['skipped_small']:,}")
    print()
    print("  By content type:")
    for key, val in sorted(stats.items()):
        if key.startswith("type_"):
            print(f"    {key[5:]:20s} {val:,}")
    print()
    print("  Technical detections:")
    for key, val in sorted(stats.items()):
        if key.startswith("tech_"):
            print(f"    {key[5:]:20s} {val:,}")
    if stats["raw"]:
        print(f"    {'Raw':20s} {stats['raw']:,}")
    print("=" * 60)
    logger.info(f"Final stats: {dict(stats)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global logger

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger(__name__)

    print("=" * 60)
    print("  iCloud Drive Tagger v2 (batched)")
    print("=" * 60)
    print(f"  Root:    {ICLOUD_ROOT}")
    print(f"  Log:     {LOG_FILE}")
    print(f"  Pillow:  {'Yes' if HAS_PILLOW else 'No (image analysis disabled)'}")
    print()

    mode = sys.argv[1] if len(sys.argv) > 1 else "help"

    if mode == "dry-run":
        print("  Mode: DRY RUN\n")
        batches = collect_files()
        apply_tags_batched(batches, dry_run=True)
        print_report()

    elif mode == "tag-fast":
        print("  Mode: TAG FAST (no image analysis)\n")
        batches = collect_files(skip_image_analysis=True)
        apply_tags_batched(batches, dry_run=False)
        print_report()

    elif mode == "tag":
        print("  Mode: TAG (with image analysis)\n")
        batches = collect_files(skip_image_analysis=False)
        apply_tags_batched(batches, dry_run=False)
        print_report()

    elif mode == "aliases":
        print("  Mode: ALIASES ONLY\n")
        create_alias_structure()
        populate_aliases()
        print_report()

    elif mode == "full":
        print("  Mode: FULL (fast tag + aliases)\n")
        batches = collect_files(skip_image_analysis=True)
        apply_tags_batched(batches, dry_run=False)
        create_alias_structure()
        populate_aliases()
        print_report()

    elif mode == "full-deep":
        print("  Mode: FULL DEEP (tag with image analysis + aliases)\n")
        batches = collect_files(skip_image_analysis=False)
        apply_tags_batched(batches, dry_run=False)
        create_alias_structure()
        populate_aliases()
        print_report()

    else:
        print("  Usage:")
        print("    python3 icloud_tagger.py dry-run     # Scan + count, no changes")
        print("    python3 icloud_tagger.py tag-fast     # Tag by extension+folder (fast)")
        print("    python3 icloud_tagger.py tag          # Tag + image analysis (slower)")
        print("    python3 icloud_tagger.py aliases      # Create alias folders + populate")
        print("    python3 icloud_tagger.py full          # Fast tag + aliases")
        print("    python3 icloud_tagger.py full-deep     # Full analysis + tag + aliases")
        print()

    stats_file = os.path.join(LOG_DIR, "last_run_stats.json")
    with open(stats_file, "w") as f:
        json.dump(dict(stats), f, indent=2)
    print(f"\n  Stats: {stats_file}")


if __name__ == "__main__":
    main()
