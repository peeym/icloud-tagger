# Project: iCloud Tagger
# Agent: lobs
# Last updated: 2026-03-12

## CP-1: Phase 1 — Extension + Folder Tagging ✅
- [x] Build icloud_tagger.py with batched tag operations
- [x] Tag 46,376 files by content type (Photo, Document, Video, etc.)
- [x] Tag by folder context (Business, Finance, Lecture, Podcast, etc.)
- [x] Create Creative-Assets symlink structure
- completed: 2026-02-26
- agent: claude

## CP-2: Document Deep Tagging ✅ (built 2026-10-15)
Rebuilt from scratch on 2026-10-15 after the March assignment to Lobs never ran.
- [x] Scope fixed by Elad: 07 - אישי/סידורים, 07 - אישי/משפחה, 04 - תמונות/אלעד תמונות, 03 - חשבונאות ומסמכים, 02 - צור הדרכות (pdf, images, doc, xls)
- [x] `doc_index.py`: scan (rules from `rules.json`), apply (additive Finder tags + Hebrew description as Finder comment), queue, find, aliases, report, override, preview, weekly
- [x] Hebrew-safe search: bidi marks, niqqud and quote variants are ignored, so "תעודת זהות אלעד" finds bidi-named files
- [x] Central folder of Finder aliases (originals never move): `07 - אישי/מסמכים חשובים/<category>/`
- [x] Claude identified the files the rules could not (overrides in `data/overrides.json`, gitignored)
- [x] Weekly launchd agent `com.eladtzur.doc-index`, Sunday 09:15, new and changed files only
- [ ] Elad: spot-check the alias folder and the remaining queue (`doc_index.py queue`)
- needs_human: false
- agent: claude
- skip_permissions:
  - can_tag_files: true
  - can_move_files: false
  - can_delete_files: false
  - can_rename_files: false
  - can_create_reports: true

## CP-3: Video Organization 🔲
- [ ] Scan video files — categorize by project (Podcast, Lectures, Personal, Tourism)
- [ ] Apply project tags to video files
- [ ] Identify large unused videos (candidates for cleanup)
- [ ] Update Creative-Assets symlinks for videos
- [ ] Report: video inventory with sizes and tags
- needs_human: false
- agent: lobs
- skip_permissions:
  - can_tag_files: true
  - can_move_files: false
  - can_delete_files: false

## CP-4: Useful Photos Selection 🔲
- [ ] Identify photo folders with business/professional content
- [ ] Tag useful photos (headshots, lecture photos, course materials)
- [ ] Skip personal photo albums — only tag work-related images
- [ ] Generate report: useful photos by category and location
- needs_human: true
- reason: "Elad reviews which photos are 'useful' vs personal"
- agent: lobs

## CP-5: Audit & Cleanup Recommendations 🔲
- [ ] Generate full tagging report: files by type, tag coverage %
- [ ] Identify untagged files and suggest tags
- [ ] Identify duplicate files (same name/size in different locations)
- [ ] Suggest cleanup candidates (old, large, redundant files)
- [ ] Present to Elad — NO deletions without approval
- needs_human: true
- reason: "Elad decides what to delete/archive"
- agent: lobs
