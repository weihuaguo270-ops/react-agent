#!/usr/bin/env pwsh
# PowerShell script to clean temporary directories

param(
    [switch]$DryRun,
    [switch]$KeepCache,
    [switch]$Help
)

if ($Help) {
    Write-Host "Usage: .\cleanup.ps1 [-DryRun] [-KeepCache] [-Help]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -DryRun      Show what would be deleted without actually deleting"
    Write-Host "  -KeepCache   Keep .cache/tmp/ structure (only clean root-level temp dirs)"
    Write-Host "  -Help        Show this help message"
    exit 0
}

$projectRoot = $PSScriptRoot

# Temporary directory patterns to remove
$tempPatterns = @(
    ".pytest-tmp*",
    ".tmp-*",
    ".evidence_tmp",
    ".release-*",
    ".pytest-basetemp"
)

$removedCount = 0

Write-Host "Scanning for temporary directories..."

foreach ($pattern in $tempPatterns) {
    $dirs = Get-ChildItem -Path $projectRoot -Directory -Filter $pattern -ErrorAction SilentlyContinue

    foreach ($dir in $dirs) {
        $relPath = $dir.FullName.Replace($projectRoot + "\", "")

        if ($DryRun) {
            Write-Host "Would remove: $relPath" -ForegroundColor Yellow
        } else {
            Write-Host "Removing: $relPath" -ForegroundColor Green
            Remove-Item -Path $dir.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
        $removedCount++
    }
}

# Clean up .cache/tmp/ if not keeping cache
$cacheTmp = Join-Path $projectRoot ".cache\tmp"
if ((Test-Path $cacheTmp) -and -not $KeepCache) {
    $relPath = ".cache\tmp"

    if ($DryRun) {
        Write-Host "Would remove: $relPath" -ForegroundColor Yellow
    } else {
        Write-Host "Removing: $relPath" -ForegroundColor Green
        Remove-Item -Path $cacheTmp -Recurse -Force -ErrorAction SilentlyContinue
    }
    $removedCount++
}

if ($removedCount -eq 0) {
    Write-Host "No temporary directories found." -ForegroundColor Cyan
} else {
    $action = if ($DryRun) { "Would remove" } else { "Removed" }
    $plural = if ($removedCount -eq 1) { "y" } else { "ies" }
    Write-Host ""
    Write-Host "$action $removedCount temporary director$plural." -ForegroundColor Green
}
