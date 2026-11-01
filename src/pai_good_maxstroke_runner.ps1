<#
===============================================================================
Dual-AI Quality Guardian - GOOD long-stroke guarded PowerShell runner
Author  : Y.TOYODA
Platform: Windows PowerShell 5.1 + Docker container physicalai_crane
Purpose : Stage the verified Python/C++ files and retrieve real MP4/JSON proof.
Safety  : No real robot. Preflight is read-only. Record is manual one-shot.
          Failures always HOLD, never print PASS when a subcommand failed.
===============================================================================
#>
param(
    [ValidateSet('Preflight','Record')]
    [string]$Action='Preflight'
)
$ErrorActionPreference='Stop'
$container='physicalai_crane'
$stage='/home/ubuntu/pai_demo/pai_good_maxstroke_r1'
$partition='pai_record_scene_wood_v1_20261101'
$targetFolder=Join-Path $env:USERPROFILE 'Downloads'
$auth='AUTHORIZE_SIMULATED_GOOD_POSITIVE_J1_R1_ONCE'

# Filled with exact hashes during package sealing. Never skip a hash check.
$sources=@(
    @{Name='pai_good_maxstroke.py';Sha='56A80B6A4EC5774AF8CAC6C89B882C56D64C1AA2CC4B0480BFEBE6F67B36A356'},
    @{Name='pai_good_pose_stream.cc';Sha='31FDE1CCF9AFA05060E7A9B6AEEFD0572B5A8948CDBB604D3BA975313866E0E8'},
    @{Name='pai_good_guarded_driver.cc';Sha='2640D591A63AB8E8523FB872804E2CFA1D16260F56AD2BEC192C73260AA5D8F6'}
)
function Assert-Rc([int]$rc,[string]$tag) {
    if($rc -ne 0){throw "${tag}_EXIT_$rc"}
}
function Local-Sha([string]$path) {
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)) {throw "MISSING_LOCAL:$path"}
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToUpperInvariant()
}
function Remote-Sha([string]$path) {
    $lines=@(& docker exec --user ubuntu $container sha256sum $path 2>&1)
    Assert-Rc $LASTEXITCODE 'REMOTE_SHA_COMMAND'
    if($lines.Count -ne 1){throw 'REMOTE_SHA_MULTIPLE_LINES'}
    $m=[regex]::Match(([string]$lines[0]),'^[0-9A-Fa-f]{64}(?=\s)')
    if(-not $m.Success){throw 'REMOTE_SHA_FORMAT'}
    return $m.Value.ToUpperInvariant()
}
function Collect-File([string[]]$lines,[string]$marker,[string]$suffix) {
    $prefix=$marker+'='
    $found=@($lines | Where-Object {([string]$_).StartsWith($prefix)})
    if($found.Count -eq 0){return $null}
    if($found.Count -ne 1){throw "DUPLICATE_MARKER:$marker"}
    $remote=([string]$found[0]).Substring($prefix.Length)
    $re='^/home/ubuntu/pai_demo/pai_good_maxstroke_r1/good_maxstroke_r1_[0-9]{8}T[0-9]{6}Z_[0-9]+\.'+$suffix+'$'
    if($remote -cnotmatch $re){throw "UNEXPECTED_REMOTE_PATH:$marker"}
    $expected=Remote-Sha $remote
    $name=[IO.Path]::GetFileName($remote)
    $local=Join-Path $targetFolder $name
    if(-not (Test-Path -LiteralPath $local)) {
        & docker cp "${container}:$remote" $local | Out-Host
        Assert-Rc $LASTEXITCODE "COPY_$marker"
    }
    $actual=Local-Sha $local
    Write-Host "${marker}_REMOTE_SHA256=$expected"
    Write-Host "${marker}_LOCAL_SHA256=$actual"
    if($expected -cne $actual){throw "COPY_SHA256_MISMATCH:$marker"}
    Write-Host "${marker}_LOCAL=$local"
    return $local
}
try {
    if(-not(Test-Path -LiteralPath $targetFolder -PathType Container)) {
        throw 'DOWNLOADS_DIRECTORY_MISSING'
    }
    $alive=@(& docker inspect --format '{{.State.Running}}' $container 2>&1)
    if($LASTEXITCODE -ne 0 -or $alive.Count -ne 1 -or
       ([string]$alive[0]).Trim() -cne 'true') {
        throw 'CONTAINER_NOT_RUNNING'
    }
    & docker exec --user ubuntu $container test -d $stage
    $rc=$LASTEXITCODE
    if($rc -eq 1) {
        & docker exec --user ubuntu $container mkdir -m 700 $stage
        Assert-Rc $LASTEXITCODE 'CREATE_STAGE'
    }
    elseif($rc -ne 0){throw 'STAGE_INSPECT_FAILED'}
    foreach($src in $sources) {
        $local=Join-Path $PSScriptRoot $src.Name
        $expected=([string]$src.Sha).ToUpperInvariant()
        if((Local-Sha $local) -cne $expected){throw "SOURCE_HASH_MISMATCH:$($src.Name)"}
        $remote="$stage/$($src.Name)"
        & docker exec --user ubuntu $container test -f $remote
        $rc=$LASTEXITCODE
        if($rc -eq 1) {
            & docker cp $local "${container}:$remote" | Out-Host
            Assert-Rc $LASTEXITCODE 'STAGE_COPY'
        }
        elseif($rc -ne 0){throw 'REMOTE_STAGE_FILE_CHECK_FAIL'}
        if((Remote-Sha $remote) -cne $expected){throw "REMOTE_SOURCE_CHANGED:$($src.Name)"}
    }
    Write-Host 'GOOD_R1_SOURCE_HASHES=PASS'
    $command=@('exec','--user','ubuntu',
        '-e','HOME=/home/ubuntu',
        '-e','DISPLAY=:0',
        '-e',"IGN_PARTITION=$partition",
        '-e','PYTHONDONTWRITEBYTECODE=1',
        $container,'python3','-B',"$stage/pai_good_maxstroke.py")
    $test=@(& docker @command --action selftest 2>&1)
    $rc=$LASTEXITCODE
    foreach($line in $test){Write-Host ([string]$line)}
    if($rc -ne 0 -or $test -notcontains 'GOOD_R1_SELFTEST=PASS_OFFLINE_NO_NETWORK_NO_MOTION') {
        throw "GOOD_SELFTEST_HOLD_$rc"
    }
    $pre=@(& docker @command --action preflight 2>&1)
    $rc=$LASTEXITCODE
    foreach($line in $pre){Write-Host ([string]$line)}
    if($rc -ne 0 -or $pre -notcontains 'GOOD_R1_PREFLIGHT=PASS_READONLY_GOOD_HOME_AND_STATIC_AUDIT') {
        throw "GOOD_PREFLIGHT_HOLD_$rc"
    }
    if($Action -ceq 'Preflight') {
        Write-Host 'GOOD_R1_RUNNER_GATE=PASS_PREFLIGHT_READONLY'
        exit 0
    }
    # The only branch which can trigger a new physical simulation J1 command.
    Write-Host 'GOOD_R1_SIMULATION_ONLY_RECORD_START=True'
    $lines=@(& docker @command --action record --authorization $auth 2>&1)
    $motionRc=$LASTEXITCODE
    foreach($line in $lines){Write-Host ([string]$line)}
    # Recover evidence even if the simulator has gone into a guarded HOLD.
    $video=Collect-File $lines 'GOOD_VIDEO_REMOTE' 'mp4'
    $motion=Collect-File $lines 'GOOD_MOTION_REMOTE' 'motion\.json'
    $witness=Collect-File $lines 'GOOD_WITNESS_REMOTE' 'witness\.json'
    if($motionRc -ne 0){throw "GOOD_MOTION_HOLD_NO_AUTO_RETRY_$motionRc"}
    if(-not $video -or -not $motion -or -not $witness){throw 'GOOD_SUCCESS_EVIDENCE_INCOMPLETE'}
    $w=Get-Content -LiteralPath $witness -Encoding UTF8 -Raw | ConvertFrom-Json
    if($w.mode -cne 'REAL_GAZEBO_SIMULATION_GOOD_R1' -or
       @('PASS_100MM_MEASURED','PASS_BOUNDED_MAX_MEASURED_BELOW_100MM') -cnotcontains ([string]$w.status) -or
       $w.joint_return_verified -ne $true -or
       $w.automatic_ai_actuation -ne $false -or
       ([double]$w.peak_cube_dx_mm) -lt 5.0 -or
       ([double]$w.final_cube_dx_mm) -lt 5.0 -or
       (Local-Sha $video) -cne ([string]$w.video_sha256).ToUpperInvariant() -or
       (Local-Sha $motion) -cne ([string]$w.motion_sha256).ToUpperInvariant()) {
        throw 'GOOD_WITNESS_CONTENT_OR_HASH_INVALID'
    }
    if($w.status -ceq 'PASS_100MM_MEASURED' -and
       ([double]$w.final_cube_dx_mm) -lt 100.0) {
        throw 'GOOD_FALSE_100MM_PASS'
    }
    Write-Host "GOOD_R1_MEASURED_PEAK_MM=$($w.peak_cube_dx_mm)"
    Write-Host "GOOD_R1_MEASURED_FINAL_MM=$($w.final_cube_dx_mm)"
    Write-Host "GOOD_R1_RUNNER_GATE=$($w.status)"
    Write-Host "GOOD_R1_FINAL_VIDEO=$video"
    exit 0
}
catch {
    Write-Host "GOOD_R1_RUNNER_GATE=HOLD; REASON=$($_.Exception.Message)"
    Write-Host 'NO_AUTOMATIC_MOTION_RETRY=True'
    exit 3
}
