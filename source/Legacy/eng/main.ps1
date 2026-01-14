$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Please enter boot.img path"

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "               vivo 4.x Kernel Auto-Patch Tool" -ForegroundColor Cyan
Write-Host "              Tool Author: MyAngelAnchorage" -ForegroundColor Cyan
Write-Host "      Repository: https://github.com/4accccc/vivo-4.x-kernel-autopatch" -ForegroundColor Cyan
Write-Host "                   Solution Provider: romanovj" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan

$MagiskBoot = ".\magiskboot.exe"
$PatchEXE = ".\patch.exe"

if (-not (Test-Path $MagiskBoot)) {
    Write-Host "[!] magiskboot.exe not found. Aborting." -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}
if (-not (Test-Path $PatchEXE)) {
    Write-Host "[!] patch.exe not found. Aborting." -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}

$BootImg = Read-Host "[*] Please enter the full path of boot.img (e.g. D:\boot.img), preferably without quotes!"
$BootImg = $BootImg.Trim('"')

if ([string]::IsNullOrWhiteSpace($BootImg)) {
    Write-Host "[!] No boot.img entered. Aborting." -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}
if (-not (Test-Path $BootImg)) {
    Write-Host "[!] boot.img does not exist. Aborting." -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}
if ((Get-Item $BootImg).PSIsContainer) {
    Write-Host "[!] Input is a folder, not a file. Aborting." -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}
Write-Host "[*] Confirmed boot.img: $BootImg" -ForegroundColor Green

$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Enter output path for patched boot.img"

$UserSave = Read-Host "[*] Enter the full save path for the patched boot.img (leave blank = same folder as boot.img), preferably without quotes!"
$UserSave = $UserSave.Trim('"')

$BootDir = Split-Path $BootImg
$FallbackPath = Join-Path $BootDir "patched-boot.img"
$FinalOutputPath = $FallbackPath
$UseFallback = $false

if (-not [string]::IsNullOrWhiteSpace($UserSave)) {
    try {
        $targetDir = Split-Path $UserSave -ErrorAction Stop
        if (-not $targetDir) { throw "invalid" }

        if (-not (Test-Path $targetDir)) {
            Write-Host "[!] Specified directory does not exist. Saving to boot.img folder." -ForegroundColor Yellow
            $UseFallback = $true
        } else {
            $testFile = Join-Path $targetDir ".__write_test__.tmp"
            "test" | Out-File $testFile -ErrorAction Stop
            Remove-Item $testFile -Force

            $FinalOutputPath = $UserSave
        }
    } catch {
        Write-Host "[!] Specified path is not writable. Saving to boot.img folder." -ForegroundColor Yellow
        $UseFallback = $true
        $FinalOutputPath = $FallbackPath
    }
} else {
    Write-Host "[*] No output path entered. Saving to boot.img folder." -ForegroundColor Yellow
    $UseFallback = $true
    $FinalOutputPath = $FallbackPath
}

$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Unpacking boot.img"

Write-Host ""
Write-Host "[*] Unpacking boot.img ..." -ForegroundColor Yellow
& $MagiskBoot unpack $BootImg 2>&1 | Out-File "unpack_log.txt"

$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Searching for kernel file"

$kernelCandidates = @(".\kernel", ".\kernel.gz", ".\kernel.lz4", ".\kernel.lzma", ".\Image", ".\zImage", ".\Image.gz")
$KernelFile = $null
foreach ($c in $kernelCandidates) {
    if (Test-Path $c) {
        $KernelFile = $c
        break
    }
}

if (-not $KernelFile) {
    Write-Host "[!] Kernel file not found (check unpack_log.txt)." -ForegroundColor Red
    Read-Host "Press Enter to continue..."
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    exit 1
}

if ($KernelFile -match "\.gz$|\.lz4$|\.lzma$") {
    Write-Host "[*] Compressed kernel detected: $KernelFile  — decompressing..." -ForegroundColor Yellow
    $decTarget = ".\kernel_decompressed"
    & $MagiskBoot decompress $KernelFile $decTarget 2>&1 | Out-Null

    if (-not (Test-Path $decTarget)) {
        Write-Host "[!] Decompression failed." -ForegroundColor Red
        Read-Host "Press Enter to exit..."
        $keep = @("main.exe")
        Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
        Get-ChildItem -Directory | Remove-Item -Recurse -Force
        exit 1
    }
    $KernelFile = $decTarget
}

Write-Host "[+] Kernel file: $KernelFile" -ForegroundColor Green

Write-Host "[*] Patching kernel..." -ForegroundColor Yellow

Start-Process -FilePath $PatchEXE -ArgumentList @($KernelFile, "-calledByMain") -NoNewWindow -Wait
$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Kernel patched"

$status = "Fail"
if (Test-Path "patch_status.log") {
    $status = Get-Content "patch_status.log" -Raw
}

if ($status -match "Address not found") {
    $host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Patch Failed"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] Patch failed: no matching address found." -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Remove-Item "patch_status.log" -Force
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}
if ($status -match "Kernel file not found") {
    $host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Patch Failed"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] Kernel file not found by patcher." -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Remove-Item "patch_status.log" -Force
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}
if ($status -match "run patch.exe directly") {
    $host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Patch Failed"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] Parameter mismatch." -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Remove-Item "patch_status.log" -Force
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "Press Enter to exit..."
    exit 1
}

if ($status -notmatch "SUCCESS") {
    $host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Patch Failed"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] Kernel patch did not succeed (unknown reason)." -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Read-Host "Press Enter to exit..."
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    exit 1
}

Write-Host ""
$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Repacking boot.img"
Write-Host "[*] Patch succeeded. Repacking boot.img ..." -ForegroundColor Yellow
& $MagiskBoot repack $BootImg 2>&1 | Out-File "repack_log.txt"

if (-not (Test-Path ".\new-boot.img")) {
    Write-Host "[!] Repacking boot.img failed!" -ForegroundColor Red
    Read-Host "Press Enter to continue..."
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    exit 1
}

$TempPatched = ".\patched-boot.img"
Copy-Item ".\new-boot.img" $TempPatched -Force

try {
    $destDir = Split-Path $FinalOutputPath
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item $TempPatched $FinalOutputPath -Force

    Write-Host "[+] Patched boot.img saved to: $FinalOutputPath" -ForegroundColor Green
} catch {
    Write-Host "[!] Cannot save to target location. Using default path." -ForegroundColor Red
    $FinalOutputPath = $FallbackPath
}

$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto-Patch Tool  Completed"
Write-Host "========================================================================"
Write-Host "                    [SUCCESS] " -ForegroundColor Green
Write-Host "Patched boot.img bypassing SU restrictions has been repacked." -ForegroundColor Green
Write-Host "Please manually use the generated boot.img in Magisk!" -ForegroundColor Green
Write-Host "Output Path: $FinalOutputPath" -ForegroundColor Green
Write-Host "Please note: We have found that on some models, in addition to kernel" -ForegroundColor Yellow
Write-Host "restrictions, SELinux also imposes certain limitations." -ForegroundColor Yellow
Write-Host "This tool does not make any modifications related to SELinux." -ForegroundColor Yellow
$keep = @("main.exe")
Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
Get-ChildItem -Directory | Remove-Item -Recurse -Force
Write-Host "========================================================================"
Read-Host "Press Enter to exit..."
