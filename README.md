# iCloud Tagger

Automatically tag files in iCloud Drive using macOS Finder tags. Handles large libraries (46,000+ files) with batched operations (~100x faster than per-file tagging).

## Features

- **Auto-tagging** by content type (Photo, Document, Video, Audio, etc.)
- **Context tags** (Business, Finance, Lecture, Podcast, etc.)
- **Technical tags** (Hi-Res, Lo-Res, Transparent, Raw)
- **Finder color labels** via macOS integration
- **Batched operations** — processes 50 files at a time for speed
- **Creative Assets folder** — creates organized `~/Creative-Assets/` symlink structure

## How It Works

1. **Collect** — Walks iCloud Drive, computes tag sets per file based on path, extension, and content analysis
2. **Apply** — Batch applies tags using the `tag` CLI tool
3. **Aliases** — Creates `~/Creative-Assets/` symlink structure organized by workflow category

## Requirements

- macOS
- Python 3.6+
- `tag` CLI (`brew install tag`)
- Optional: `Pillow` for image resolution/transparency detection

## Usage

```bash
# Tag all files in iCloud Drive
python3 icloud_tagger.py

# Dry run (show what would be tagged)
python3 icloud_tagger.py --dry-run
```

## License

MIT
