param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
$configBytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $ConfigPath).Path)
$compressedConfig = New-Object System.IO.MemoryStream
$gzipStream = New-Object System.IO.Compression.GZipStream($compressedConfig, [System.IO.Compression.CompressionMode]::Compress, $true)
try {
    $gzipStream.Write($configBytes, 0, $configBytes.Length)
} finally {
    $gzipStream.Dispose()
}
$encodedConfig = [Convert]::ToBase64String($compressedConfig.ToArray())
$compressedConfig.Dispose()
if ($encodedConfig.Length -gt 48 * 1024) {
    throw 'Compressed config exceeds the GitHub Secret size limit. Remove unused nodes or rules first.'
}
Set-Clipboard -Value $encodedConfig
Write-Host "Copied compressed config to clipboard ($($encodedConfig.Length) characters). Paste into the MIHOMO_CONFIG_B64 repository Secret."
