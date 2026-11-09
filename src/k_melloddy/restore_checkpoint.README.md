# Checkpoint restoration

Inputs: `checkpoint_download.json`, ordered ZIP parts, and a cloned project destination. Output: reconstructed ZIP in the download directory and the original research files under the project. Units: bytes, files, papers in the internal manifest; restoration never creates scientific decisions or HTTP evidence.

Algorithm/states: validate part names/order, sizes and SHA-256; concatenate; verify combined ZIP; preflight all archive paths, member identities, sizes, existing file hashes and destination reparse points; create missing files without overwriting existing content; verify restored hashes. Duplicate, unlisted and escaping members fail. Existing identical files are skipped for resume. All differing files are preserved and block restoration before extraction starts. No deletion is performed. Interruption during a file copy may leave a partial file that requires inspection before retry; it is never silently overwritten.

Command (Windows PowerShell, run from a trusted clone): `powershell -NoProfile -ExecutionPolicy Bypass -File C:\dev\k-melloddy\src\k_melloddy\restore_checkpoint.ps1`. Default download directory is the current user's Downloads; use `-DownloadDirectory` to specify another folder. Default destination is `C:\dev\k-melloddy`. Saved scientific records contain absolute paths: using another destination does not migrate those references.

Audit/validation: the download manifest binds all parts and the complete ZIP; `CHECKPOINT_MANIFEST_20261109.json` binds each archived file. Source SQLite/JSON/PRISMA and immutable revisions are preserved unchanged. No provider is configured. Limitations: Windows/PowerShell, sufficient free space for parts + merged ZIP + restored files, runtime installation remains separate. Download only the intended private release; hashes detect corruption, not the identity of an untrusted publisher.

Tests: synthetic archive smoke checks cover successful assembly/extraction, idempotent retry, existing-file preservation and rejected parent traversal. This tool restores bytes, not an actively running review process.
