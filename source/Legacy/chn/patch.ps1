$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 准备修补内核"

"Fail" | Out-File "patch_status.log" -Encoding UTF8

if ($args.Count -lt 2 -or $args[1] -ne "-calledByMain") {
    Write-Host "[!] patch 部分缺少参数（未接收到 kernel 文件路径）" -ForegroundColor Red
    Write-Host "[!] 你直接运行了patch.exe？" -ForegroundColor Red
    "[!] 你直接运行了patch.exe？" | Out-File "patch_status.log" -Encoding UTF8
    exit 1
}

$TargetFile = $args[0]
$R2Path = ".\radare2.exe"

if (-not (Test-Path $TargetFile)) {
    Write-Host "[!] 找不到 kernel 文件: $TargetFile" -ForegroundColor Red
    "[!] 找不到 kernel 文件" | Out-File "patch_status.log" -Encoding UTF8
    exit 1
}

Write-Host ""
Write-Host "[*] 正在检测内核版本..." -ForegroundColor Yellow

$bytes = [System.IO.File]::ReadAllBytes($TargetFile)
$ascii = [System.Text.Encoding]::ASCII.GetString($bytes)

$kernelVersion = $null
if ($ascii -match 'Linux version\s+([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z\-\+\._]*)') {
    $kernelVersion = $matches[1]
}

if ($kernelVersion) {
    Write-Host "[*] 检测到内核版本: $kernelVersion" -ForegroundColor Green
    if ($kernelVersion -match '^([0-9]+)\.') {
        $mainVer = [int]$matches[1]
        Write-Host "[*] 内核主版本号: $mainVer" -ForegroundColor Cyan
        if ($mainVer -ne 4) {
            Write-Host "[!] 警告：当前内核不是 4.x，可能不兼容！" -ForegroundColor Red
        }
    }
} else {
    Write-Host "[!] 未能检测到内核版本，请自行确认是否为 4.x 内核！" -ForegroundColor Red
}

Write-Host ""
Write-Host "[?] 是否修补 vivo do_mount_check ？" -ForegroundColor Yellow
Write-Host "[*] 部分机型不需要此修补。若此处选择不修补后 Magisk 无法启动，请选择修补后再试。" -ForegroundColor Yellow
Write-Host "[*] 修补方案by wuxianlin。" -ForegroundColor Green
Write-Host "[*] 1. 不修补"
Write-Host "[*] 2. 修补"
$choiceC = Read-Host "[*] 请输入数字 (默认为 1): "

switch ($choiceC) {
    "2" { $Env:PATCH_C = "1"; Write-Host "[*] 已选择：修补 vivo do_mount_check" -ForegroundColor Green }
    default { $Env:PATCH_C = "0"; Write-Host "[*] 已选择：不修补 vivo do_mount_check" -ForegroundColor Yellow }
}

Write-Host ""
Write-Host "[?] 是否尝试修补分区挂载？" -ForegroundColor Yellow
Write-Host "[!] 部分机型修补后可能无法开机，异常请关闭该选项。" -ForegroundColor Yellow
Write-Host "[*] 1. 不修补"
Write-Host "[*] 2. 修补"
$choiceB = Read-Host "[*] 请输入数字 (默认为 1): "

switch ($choiceB) {
    "2" { $Env:PATCH_B = "1"; Write-Host "[*] 已选择：修补分区补丁" -ForegroundColor Green }
    default { $Env:PATCH_B = "0"; Write-Host "[*] 已选择：不修补分区补丁" -ForegroundColor Yellow }
}

$tempSearchA = "temp_search_a.txt"
$tempSearchB = "temp_search_b.txt"
$tempSearchC = "temp_search_c.txt"

$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 正在查找地址"
Write-Host ""
Write-Host "[1/2] 正在查找地址..." -ForegroundColor Yellow

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
        Write-Host "[*] (su) 找到地址" -ForegroundColor Gray
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
        if ($Env:PATCH_B -eq "1" -and $targetAddr) {
            Write-Host "[*] (mount fix) 找到地址" -ForegroundColor Gray
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
        if ($Env:PATCH_C -eq "1" -and $addressC) {
            Write-Host "[*] (do_mount_check) 找到地址" -ForegroundColor Gray
        }
    }
}

$doPatchA = ($addressesA.Count -gt 0)   # su 修补是强制型，只要找到就算
$doPatchB = ($Env:PATCH_B -eq "1" -and $null -ne $targetAddr)
$doPatchC = ($Env:PATCH_C -eq "1" -and $null -ne $addressC)

if (-not ($doPatchA -or $doPatchB -or $doPatchC)) {
    Write-Host "[!] 没有找到对应地址，可能是内核不支持、内核损坏或者内核已经被修补过了！" -ForegroundColor Red 
    "[!] 没有找到对应地址" | Out-File "patch_status.log" -Encoding UTF8 
    Remove-Item $tempSearchA, $tempSearchB, $tempSearchC, `
        "temp_search_a.rc", "temp_search_b.rc", "temp_search_c.rc" `
        -Force -ErrorAction SilentlyContinue
    exit 1
}

$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 正在修补内核"
Write-Host "[2/2] 正在修补..." -ForegroundColor Yellow

$patchScript = @"
e asm.arch=arm
e asm.bits=64
e io.cache=false
e search.in=io.maps
oo+

"@

foreach ($addr in $addressesA) {
    $patchScript += "wx 3fdd0071 @ $addr`n"
    Write-Host "[*] (su) 修补地址..." -ForegroundColor Green
}

if ($Env:PATCH_C -eq "1" -and $addressC) {
    $patchScript += "wx 0092CFC2C9CEC0DB00 @ $addressC`n"
    Write-Host "[*] (do_mount_check) 修补地址..." -ForegroundColor Green
}

if ($Env:PATCH_B -eq "1" -and $targetAddr) {
    $patchScript += "wx 081f0035 @ $targetAddr`n"
    Write-Host "[*] (mount fix) 修补地址..." -ForegroundColor Green
}

$patchScript += "wc`nq`n"
$patchScript | Set-Content "temp_apply_patch.rc" -Encoding ASCII
& $R2Path -w -q -i temp_apply_patch.rc $TargetFile *> $null

Remove-Item temp_search_*.txt, temp_search_*.rc, temp_apply_patch.rc -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "[SUCCESS] 内核自动修补完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

"SUCCESS" | Out-File "patch_status.log" -Encoding UTF8