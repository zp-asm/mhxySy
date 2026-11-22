# Create target dirs and move all caches/TEMP off C:
# Constraint: nothing on C:, nothing on F: (F is MuMu only)
# Run: powershell -ExecutionPolicy Bypass -File E:\gamework\mhxyMobile\tools\setup_dirs.ps1

$ErrorActionPreference = 'Continue'

$dirs = @(
    'D:\develop\tools\7zip',
    'D:\develop\tools\qemu',
    'D:\develop\tools\ghidra',
    'D:\develop\tools\android\ndk',
    'E:\iso',
    'E:\kernel-src',
    'E:\vms\ubuntu-kbuild',
    'E:\cache\pip',
    'E:\cache\tmp',
    'E:\cache\huggingface',
    'E:\out'
)

foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        Write-Host "created  $d"
    } else {
        Write-Host "exists   $d"
    }
}

$envs = @{
    'TEMP'           = 'E:\cache\tmp'
    'TMP'            = 'E:\cache\tmp'
    'PIP_CACHE_DIR'  = 'E:\cache\pip'
    'XDG_CACHE_HOME' = 'E:\cache'
    'HF_HOME'        = 'E:\cache\huggingface'
    'TORCH_HOME'     = 'E:\cache\torch'
    'QEMU_DIR'       = 'D:\develop\tools\qemu'
    'KERNEL_SRC'     = 'E:\kernel-src\linux-6.1.90'
    'OUT_DIR'        = 'E:\out'
}

foreach ($k in $envs.Keys) {
    $scope = 'Machine'
    try {
        [Environment]::SetEnvironmentVariable($k, $envs[$k], 'Machine')
    } catch {
        $scope = 'User'
        [Environment]::SetEnvironmentVariable($k, $envs[$k], 'User')
    }
    Set-Item -Path "Env:$k" -Value $envs[$k]
    Write-Host ("env      {0,-16} = {1}   [{2}]" -f $k, $envs[$k], $scope)
}

Write-Host ""
Write-Host "=== check ==="
foreach ($p in @('C','D','E','F')) {
    $d = Get-PSDrive -Name $p -ErrorAction SilentlyContinue
    if ($d) { "{0}:  free {1,7:N1} GB" -f $p, ($d.Free / 1GB) }
}
"TEMP now  = $env:TEMP"
"pip cache = $env:PIP_CACHE_DIR"
Write-Host "done. open a new terminal for machine-level vars."
