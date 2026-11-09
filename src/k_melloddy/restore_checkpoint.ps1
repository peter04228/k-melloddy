param(
    [string]$DownloadDirectory = (Join-Path $env:USERPROFILE 'Downloads'),
    [string]$Destination = 'C:\dev\k-melloddy'
)
$ErrorActionPreference = 'Stop'
$archiveName = 'k-melloddy-liver-15860-checkpoint-20261109.zip'
$manifestPath = Join-Path $DownloadDirectory 'checkpoint_download.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema -ne 'k-melloddy-download-v1' -or $manifest.archive_name -ne $archiveName -or $manifest.parts.Count -lt 1) { throw 'Invalid checkpoint download manifest' }
$total = 0L
$index = 0
foreach ($part in $manifest.parts) {
    $index++
    if ($part.name -ne ($archiveName + ('.part{0:D3}' -f $index))) { throw 'Invalid checkpoint part order' }
    $partPath = Join-Path $DownloadDirectory $part.name
    if ((Get-Item -LiteralPath $partPath).Length -ne $part.bytes) { throw ('Part size mismatch: ' + $part.name) }
    if ((Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $part.sha256) { throw ('Part hash mismatch: ' + $part.name) }
    $total += $part.bytes
}
if ($total -ne $manifest.archive_bytes) { throw 'Combined size mismatch' }
$archivePath = Join-Path $DownloadDirectory $archiveName
if (-not (Test-Path -LiteralPath $archivePath)) {
    $output = [IO.File]::Open($archivePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        foreach ($part in $manifest.parts) {
            $inputStream = [IO.File]::OpenRead((Join-Path $DownloadDirectory $part.name))
            try { $inputStream.CopyTo($output) } finally { $inputStream.Dispose() }
        }
    } finally { $output.Dispose() }
}
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.archive_sha256) { throw 'ZIP hash mismatch; existing ZIP preserved for inspection' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$base = [IO.Path]::GetFullPath($Destination).TrimEnd('\')
$zip = [IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    $entry = $zip.GetEntry('CHECKPOINT_MANIFEST_20261109.json')
    if ($null -eq $entry) { throw 'Missing internal checkpoint manifest' }
    $reader = [IO.StreamReader]::new($entry.Open(), [Text.Encoding]::UTF8)
    try { $checkpoint = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
    if ($checkpoint.schema -ne 'k-melloddy-checkpoint-v1') { throw 'Invalid internal checkpoint manifest' }
    $expected = @{}
    foreach ($file in $checkpoint.files) {
        if ($expected.ContainsKey($file.path)) { throw 'Duplicate checkpoint identity' }
        $expected[$file.path] = $file
    }
    if ($zip.Entries.Count -ne ($expected.Count + 1)) { throw 'Unexpected ZIP members' }
    $seen = @{}
    # Preflight every member and existing destination before writing any file.
    foreach ($item in $zip.Entries) {
        $name = $item.FullName
        if ($seen.ContainsKey($name)) { throw 'Duplicate ZIP member' }
        $seen[$name] = $true
        if ($name -ne 'CHECKPOINT_MANIFEST_20261109.json' -and -not $expected.ContainsKey($name)) { throw 'Unlisted ZIP member' }
        $target = [IO.Path]::GetFullPath((Join-Path $base $name))
        if (-not $target.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'ZIP path escapes project' }
        $ancestor = $target
        while ($ancestor -and $ancestor.Length -ge $base.Length) {
            if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Destination contains a reparse point' }
            $ancestor = [IO.Path]::GetDirectoryName($ancestor)
        }
        if ($expected.ContainsKey($name) -and $item.Length -ne $expected[$name].bytes) { throw 'ZIP member size mismatch' }
        if (Test-Path -LiteralPath $target) {
            if ($name -eq 'CHECKPOINT_MANIFEST_20261109.json') { continue }
            if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[$name].sha256) { throw ('Existing file differs; preserved: ' + $target) }
        }
    }
    foreach ($item in $zip.Entries) {
        $target = [IO.Path]::GetFullPath((Join-Path $base $item.FullName))
        if (Test-Path -LiteralPath $target) { continue }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
        $inputStream = $item.Open()
        $output = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try { $inputStream.CopyTo($output) } finally { $output.Dispose(); $inputStream.Dispose() }
        if ($expected.ContainsKey($item.FullName) -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected[$item.FullName].sha256) { throw ('Restored file hash mismatch: ' + $target) }
    }
    Write-Output ('Checkpoint restored and verified: ' + $base)
} finally { $zip.Dispose() }
