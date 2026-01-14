$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto Patch Tool - Preparing to Patch Kernel"

"Fail" | Out-File "patch_status.log" -Encoding UTF8

if ($args.Count -lt 2 -or $args[1] -ne "-calledByMain") {
    Write-Host "[!] Missing parameters for patch section (kernel file path not received)" -ForegroundColor Red
    Write-Host "[!] Did you run patch.exe directly?" -ForegroundColor Red
    "[!] Did you run patch.exe directly?" | Out-File "patch_status.log" -Encoding UTF8
    exit 1
}

$TargetFile = $args[0]
$R2Path = ".\radare2.exe"

if (-not (Test-Path $TargetFile)) {
    Write-Host "[!] Kernel file not found: $TargetFile" -ForegroundColor Red
    "[!] Kernel file not found" | Out-File "patch_status.log" -Encoding UTF8
    exit 1
}

Write-Host ""
Write-Host "[*] Detecting kernel version..." -ForegroundColor Yellow

$bytes = [System.IO.File]::ReadAllBytes($TargetFile)
$ascii = [System.Text.Encoding]::ASCII.GetString($bytes)

$kernelVersion = $null
if ($ascii -match 'Linux version\s+([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z\-\+\._]*)') {
    $kernelVersion = $matches[1]
}

if ($kernelVersion) {
    Write-Host "[*] Detected kernel version: $kernelVersion" -ForegroundColor Green
    if ($kernelVersion -match '^([0-9]+)\.') {
        $mainVer = [int]$matches[1]
        Write-Host "[*] Kernel major version: $mainVer" -ForegroundColor Cyan
        if ($mainVer -ne 4) {
            Write-Host "[!] Warning: The kernel is not 4.x, compatibility is not guaranteed!" -ForegroundColor Red
        }
    }
} else {
    Write-Host "[!] Failed to detect kernel version, please verify manually if your kernel is 4.x!" -ForegroundColor Red
}

Write-Host ""

Write-Host "[?] Do you want to patch vivo do_mount_check?" -ForegroundColor Yellow
Write-Host "[*] Some devices do not require this patch. If Magisk fails to start when not patched, please try enabling this option." -ForegroundColor Yellow
Write-Host "[*] Solution by wuxianlin." -ForegroundColor Green
Write-Host "[*] 1. Do NOT patch"
Write-Host "[*] 2. Patch"
$choiceC = Read-Host "[*] Please enter a number (default is 1): "

switch ($choiceC) {
    "2" { $Env:PATCH_C = "1"; Write-Host "[*] Selected: Patch vivo do_mount_check" -ForegroundColor Green }
    default { $Env:PATCH_C = "0"; Write-Host "[*] Selected: Do NOT patch vivo do_mount_check" -ForegroundColor Yellow }
}

Write-Host ""

Write-Host "[?] Do you want to attempt the mount fix?" -ForegroundColor Yellow
Write-Host "[!] Please note: on some kernels, applying the mount patch may cause the device to fail to boot. If your phone won't boot after applying this patch, try choosing not to patch this address." -ForegroundColor Yellow
Write-Host "[*] 1. Do NOT apply patch"
Write-Host "[*] 2. Apply patch"
$choice = Read-Host "[*] Please enter a number (default is 1): "

switch ($choice) {
    "2" { $Env:PATCH_B = "1"; Write-Host "[*] Selected: Apply patch" -ForegroundColor Green }
    default { $Env:PATCH_B = "0"; Write-Host "[*] Selected: Do NOT apply patch" -ForegroundColor Yellow }
}

$tempSearchA = "temp_search_a.txt"
$tempSearchB = "temp_search_b.txt"
$tempSearchC = "temp_search_c.txt"

$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto Patch Tool - Searching for Patch Addresses"

Write-Host ""
Write-Host "[1/2] Searching for target addresses..." -ForegroundColor Yellow

@"
e asm.arch=arm
e asm.bits=64
e search.in=io.maps
oo+
s 0
/x .fc.0171....0054....4039.fd.0171....0054
q
"@ | Set-Content "temp_search_a.rc" -Encoding ASCII

& $R2Path -qi temp_search_a.rc $TargetFile > $tempSearchA 2>&1

$addressesA = @()
Get-Content $tempSearchA | ForEach-Object {
    if ($_ -match '(0x[0-9a-fA-F]+)' -and $_ -notin $addressesA) {
        $addressesA += $matches[1]
        Write-Host "[*] (su) Address found !" -ForegroundColor Gray
    }
}

@"
e asm.arch=arm
e asm.bits=64
e search.in=io.maps
oo+
s 0
/x 085040b9....0034....4039
q
"@ | Set-Content "temp_search_b.rc" -Encoding ASCII

& $R2Path -qi temp_search_b.rc $TargetFile > $tempSearchB 2>&1

$targetAddr = $null
Get-Content $tempSearchB | ForEach-Object {
    if ($_ -match '(0x[0-9a-fA-F]+)' -and -not $targetAddr) {
        $targetAddr = "0x{0:x}" -f ([Convert]::ToInt64($matches[1].Substring(2),16) + 4)
        if ($Env:PATCH_B -eq "1") {
            Write-Host "[*] (mount fix) Address found !" -ForegroundColor Gray
        }
    }
}

@"
e asm.arch=arm
e asm.bits=64
e search.in=io.maps
oo+
s 0
/x 0092CFC2C9CDDDDA00
q
"@ | Set-Content "temp_search_c.rc" -Encoding ASCII

& $R2Path -qi temp_search_c.rc $TargetFile > $tempSearchC 2>&1

$addressC = $null
Get-Content $tempSearchC | ForEach-Object {
    if ($_ -match '(0x[0-9a-fA-F]+)' -and -not $addressC) {
        $addressC = $matches[1]
        if ($Env:PATCH_C -eq "1") {
            Write-Host "[*] (do_mount_check) Address found !" -ForegroundColor Gray
        }
    }
}

$doPatchA = ($addressesA.Count -gt 0)
$doPatchB = ($Env:PATCH_B -eq "1" -and $null -ne $targetAddr)
$doPatchC = ($Env:PATCH_C -eq "1" -and $null -ne $addressC)

if (-not ($doPatchA -or $doPatchB -or $doPatchC)) {
    Write-Host "[!] No valid addresses found. Kernel may be unsupported, corrupted, or already patched!" -ForegroundColor Red
    "[!] Address not found" | Out-File "patch_status.log" -Encoding UTF8
    Remove-Item $tempSearchA, $tempSearchB, $tempSearchC, `
        "temp_search_a.rc", "temp_search_b.rc", "temp_search_c.rc" `
        -Force -ErrorAction SilentlyContinue
    exit 1
}

$host.UI.RawUI.WindowTitle = "vivo 4.x Kernel Auto Patch Tool - Applying Patches"
Write-Host "[2/2] Patching kernel..." -ForegroundColor Yellow

$patchScript = @"
e asm.arch=arm
e asm.bits=64
e io.cache=false
e search.in=io.maps
oo+

"@

foreach ($addr in $addressesA) {
    $patchScript += "wx 3fdd0071 @ $addr`n"
    Write-Host "[*] (su) Patching address..." -ForegroundColor Green
}

if ($Env:PATCH_C -eq "1" -and $addressC) {
    $patchScript += "wx 0092CFC2C9CEC0DB00 @ $addressC`n"
    Write-Host "[*] (do_mount_check) Patching address..." -ForegroundColor Green
}

if ($Env:PATCH_B -eq "1" -and $targetAddr) {
    $patchScript += "wx 081f0035 @ $targetAddr`n"
    Write-Host "[*] (mount fix) Patching address..." -ForegroundColor Green
}

$patchScript += "wc`nq`n"
$patchScript | Set-Content "temp_apply_patch.rc" -Encoding ASCII
& $R2Path -w -q -i temp_apply_patch.rc $TargetFile *> $null

Remove-Item temp_search_*.txt, temp_search_*.rc, temp_apply_patch.rc -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "[SUCCESS] Kernel patch completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

"SUCCESS" | Out-File "patch_status.log" -Encoding UTF8
