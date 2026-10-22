# Project SOP: GitHub is the reference

Agreed 22 October 2026.

1. Keep current source, installers, model manifests, folder configuration, startup commands and PDFs together in this repository.
2. Update CURRENT_SETUP.md and affected instructions/PDF when the procedure changes. Identify the active approach and label older alternatives.
3. Commit changes, then check the published files. Local-only edits are not the shared current version.
4. Distinguish latest attempt, locally checked and verified working on a real pod. Record the tested commit, environment, checks and generated-output evidence before marking last known working.
5. Preserve the last verified working commit/tag while experimenting. Recover from that version and document changes tried.
6. Model binaries stay on persistent storage. GitHub stores exact model sources, revisions, filenames, byte counts, SHA256 hashes and destination folders. Keep private settings and access credentials out of the repository.
7. Start with manual Jupyter installers; combine them only after individual steps work. Preserve models and the separate 8189 service.

A GitHub update does not imply that a live pod has been updated or tested. Report both accurately.
