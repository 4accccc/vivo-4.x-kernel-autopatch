$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 请输入boot.img路径"

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "                 vivo 4系内核 全自动修补工具" -ForegroundColor Cyan
Write-Host "                工具作者:MyAngelAnchorage" -ForegroundColor Cyan
Write-Host "        仓库:https://github.com/4accccc/vivo-4.x-kernel-autopatch" -ForegroundColor Cyan
Write-Host "                       方案作者:romanovj" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan

$MagiskBoot = ".\magiskboot.exe"
$PatchEXE = ".\patch.exe"

if (-not (Test-Path $MagiskBoot)) {
    Write-Host "[!] 未找到 magiskboot.exe，终止。" -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键继续..."
    exit 1
}
if (-not (Test-Path $PatchEXE)) {
    Write-Host "[!] 未找到 patch.exe，终止。" -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键继续..."
    exit 1
}

$BootImg = Read-Host "[*] 请输入 boot.img 文件的完整路径（例如 D:\boot.img），路径最好不加引号！"
$BootImg = $BootImg.Trim('"')

if ([string]::IsNullOrWhiteSpace($BootImg)) {
    Write-Host "[!] 未输入 boot.img，脚本终止。" -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键继续..."
    exit 1
}
if (-not (Test-Path $BootImg)) {
    Write-Host "[!] boot.img 文件不存在，脚本终止。" -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键继续..."
    exit 1
}
if ((Get-Item $BootImg).PSIsContainer) {
    Write-Host "[!] 输入的是文件夹而非文件，脚本终止。" -ForegroundColor Red
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键继续..."
    exit 1
}
Write-Host "[*] 已确认 boot.img: $BootImg" -ForegroundColor Green

$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 请输入修补后boot.img保存路径"

$UserSave = Read-Host "[*] 请输入保存修补后boot文件的完整路径（留空则保存到boot.img同目录），路径最好不加引号！"
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
            Write-Host "[!] 指定目录不存在，默认保存到 boot.img 所在目录。" -ForegroundColor Yellow
            $UseFallback = $true
        } else {
            $testFile = Join-Path $targetDir ".__write_test__.tmp"
            "test" | Out-File $testFile -ErrorAction Stop
            Remove-Item $testFile -Force

            $FinalOutputPath = $UserSave
        }
    } catch {
        Write-Host "[!] 指定路径不可写，默认保存到 boot.img 所在目录。" -ForegroundColor Yellow
        $UseFallback = $true
        $FinalOutputPath = $FallbackPath
    }
} else {
    Write-Host "[*] 未指定保存路径，默认保存到 boot.img 所在目录。" -ForegroundColor Yellow
    $UseFallback = $true
    $FinalOutputPath = $FallbackPath
}

$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 正在解包boot.img"

Write-Host ""
Write-Host "[*] 开始解包 boot.img ..." -ForegroundColor Yellow
& $MagiskBoot unpack $BootImg 2>&1 | Out-File "unpack_log.txt"

$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 正在查找 kernel 文件"

$kernelCandidates = @(".\kernel", ".\kernel.gz", ".\kernel.lz4", ".\kernel.lzma", ".\Image", ".\zImage", ".\Image.gz")
$KernelFile = $null
foreach ($c in $kernelCandidates) {
    if (Test-Path $c) {
        $KernelFile = $c
        break
    }
}

if (-not $KernelFile) {
    Write-Host "[!] 未找到 kernel（请检查 unpack_log.txt）。" -ForegroundColor Red
    Read-Host "请按回车键继续..."
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    exit 1
}

if ($KernelFile -match "\.gz$|\.lz4$|\.lzma$") {
    Write-Host "[*] 发现压缩内核 $KernelFile，正在解压..." -ForegroundColor Yellow
    $decTarget = ".\kernel_decompressed"
    & $MagiskBoot decompress $KernelFile $decTarget 2>&1 | Out-Null

    if (-not (Test-Path $decTarget)) {
        Write-Host "[!] 解压失败。" -ForegroundColor Red
        Read-Host "请按回车键继续..."
        $keep = @("main.exe")
        Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
        Get-ChildItem -Directory | Remove-Item -Recurse -Force
        exit 1
    }
    $KernelFile = $decTarget
}

Write-Host "[+] 内核文件路径: $KernelFile" -ForegroundColor Green

Write-Host "[*] 开始修补内核..." -ForegroundColor Yellow

Start-Process -FilePath $PatchEXE -ArgumentList @($KernelFile, "-calledByMain") -NoNewWindow -Wait
$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 内核修补完成"

$status = "Fail"
if (Test-Path "patch_status.log") {
    $status = Get-Content "patch_status.log" -Raw
}

if ($status -match "没有找到对应地址") {
    $host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 修补失败"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] 内核修补失败，未找到对应地址，终止操作！" -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Remove-Item "patch_status.log" -Force
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键退出..."
    exit 1
}
if ($status -match "找不到 kernel 文件") {
    $host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 修补失败"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] 软件找不到 kernel 文件，终止操作！" -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Remove-Item "patch_status.log" -Force
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键退出..."
    exit 1
}
if ($status -match "你直接运行了patch") {
    $host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 修补失败"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] 参数传输异常，终止操作！" -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Remove-Item "patch_status.log" -Force
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    Read-Host "请按回车键退出..."
    exit 1
}

if ($status -notmatch "SUCCESS") {
    $host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 修补失败"
    Write-Host "===============================================" -ForegroundColor Red
    Write-Host "[Failed] 由于未知原因内核修补未成功，终止操作！" -ForegroundColor Red
    Write-Host "===============================================" -ForegroundColor Red
    Read-Host "请按回车键退出..."
    $keep = @("main.exe")
    Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
    Get-ChildItem -Directory | Remove-Item -Recurse -Force
    exit 1
}

Write-Host ""
$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 正在重打包boot.img"
Write-Host "[*] 修补成功，继续重新打包 boot.img ..." -ForegroundColor Yellow
& $MagiskBoot repack $BootImg 2>&1 | Out-File "repack_log.txt"

if (-not (Test-Path ".\new-boot.img")) {
    Write-Host "[!] 重新打包 boot.img 失败！" -ForegroundColor Red
    Read-Host "请按回车键继续..."
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

    Write-Host "[+] 修补后的 boot.img 已保存到: $FinalOutputPath" -ForegroundColor Green
} catch {
    Write-Host "[!] 无法保存到目标位置，使用默认路径(boot.img所在位置)。" -ForegroundColor Red
    $FinalOutputPath = $FallbackPath
}

$host.UI.RawUI.WindowTitle = "vivo 4系内核 全自动修补工具 自动修补完成"
Write-Host "=================================================================="
Write-Host "                    [SUCCESS] " -ForegroundColor Green
Write-Host "破解反su限制的boot.img已打包完成" -ForegroundColor Green
Write-Host "请自己将生成的boot.img放到面具里修补！" -ForegroundColor Green
Write-Host "输出路径: $FinalOutputPath" -ForegroundColor Green
Write-Host "请注意：我们发现部分机型除了内核有限制以外，selinux也做了一定的限制，本工具不涉及修改selinux的范围。" -ForegroundColor Yellow
$keep = @("main.exe")
Get-ChildItem -File | Where-Object { $keep -notcontains $_.Name } | Remove-Item -Force
Get-ChildItem -Directory | Remove-Item -Recurse -Force
Write-Host "=================================================================="
Read-Host "请按回车键退出..."
