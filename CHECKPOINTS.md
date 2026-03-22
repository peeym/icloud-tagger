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

## CP-2: Document Deep Tagging ← CURRENT
- [ ] Identify important document subfolders in iCloud Drive
- [ ] Add project-specific tags to documents (Finance, Insurance, Tax, Contracts)
- [ ] Tag PDFs by content where possible (bank statements, invoices, certificates)
- [ ] Run icloud_tagger.py full-deep for image analysis pass
- [ ] Verify Creative-Assets/Documents/ symlinks are correct
- needs_human: false
- agent: lobs
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
