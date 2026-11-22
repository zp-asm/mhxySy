# Fetch artifacts from the latest GitHub release, push to MuMu, load module, verify.
# ASCII only (Windows PowerShell 5.1 misparses UTF-8 without BOM).
#   run:  pwsh -File tools\deploy_drv.ps1

$ErrorActionPreference = 'Continue'
$repo   = 'zp-asm/mhxySy'
$out    = 'E:\out\drv'
$serial = '127.0.0.1:16384'
$pkg    = 'com.netease.my'

New-Item -ItemType Directory -Force -Path $out | Out-Null
$base = "https://github.com/$repo/releases/download/latest"

Write-Host "=== 1) download artifacts ==="
foreach ($f in 'mhxy_drv.ko', 'kread') {
    $dst = Join-Path $out $f
    try {
        Invoke-WebRequest "$base/$f" -OutFile $dst -UseBasicParsing -TimeoutSec 120
        Write-Host ("  OK   {0,-14} {1:N0} bytes" -f $f, (Get-Item $dst).Length)
    } catch {
        Write-Host ("  FAIL {0}: {1}" -f $f, $_.Exception.Message)
        return
    }
}

Write-Host "=== 2) push to device ==="
adb connect $serial | Out-Null
adb -s $serial push "$out\mhxy_drv.ko" /data/local/tmp/ | Out-Null
adb -s $serial push "$out\kread" /data/local/tmp/ | Out-Null
adb -s $serial shell 'chmod 755 /data/local/tmp/kread'
Write-Host "  pushed"

Write-Host "=== 3) insmod -f ==="
adb -s $serial shell 'rmmod mhxy_drv 2>/dev/null; insmod -f /data/local/tmp/mhxy_drv.ko; echo "exit=$?"'
adb -s $serial shell 'dmesg | tail -15'

Write-Host "=== 4) node + stat ==="
adb -s $serial shell 'ls -l /dev/mhxy_drv 2>&1'
adb -s $serial shell '/data/local/tmp/kread stat 2>&1'

Write-Host "=== 5) pgd probe ==="
adb -s $serial shell "/data/local/tmp/kread pgd $pkg 2>&1"

Write-Host "=== 6) DECISIVE: read houdini arena (EIO from userspace) ==="
adb -s $serial shell "/data/local/tmp/kread arena $pkg 2>&1"
