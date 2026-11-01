param(
    [ValidateSet('Preflight','Record')]
    [string]$Action='Preflight'
)
$ErrorActionPreference='Stop'
$containerName='physicalai_crane'
$stage='/home/ubuntu/pai_demo/pai_ng_maxstroke_r2'
$download=Join-Path $env:USERPROFILE 'Downloads'
$part='pai_ng_defect_camera_v2_20261101'
$auth='AUTHORIZE_SIM_ONLY_GUARDED_R2_MAX_STROKE_ONE_SHOT'
$sources=@(
    @{Name='pai_ng_maxstroke_r2.py'; Sha='7A2CEDB9179AEA59C25DAAFFD7A878F414D7C6B5BE4036D07813E820493C12BB'},
    @{Name='pai_ng_pose_stream_r2.cc';Sha='3C9C7B4AF180CDE794329EBDBC4AC328B269864CCA596F9602D334A5F2BDEC93'}
)
function Assert-Rc([int]$Rc,[string]$Where) {
    if($Rc -ne 0) {throw "${Where}_EXIT_$Rc"}
}
function Hash-Local([string]$File) {
    if(-not(Test-Path -LiteralPath $File -PathType Leaf)) {
        throw "MISSING_LOCAL_FILE:$File"
    }
    return (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash.ToUpperInvariant()
}
function Hash-Remote([string]$File) {
    $lines=@(& docker exec --user ubuntu $containerName sha256sum $File 2>&1)
    Assert-Rc $LASTEXITCODE 'DOCKER_SHA256'
    if($lines.Count -ne 1) {throw 'DOCKER_SHA256_LINES_INVALID'}
    $m=[regex]::Match([string]$lines[0],'^[0-9A-Fa-f]{64}(?=\s)')
    if(-not $m.Success) {throw 'DOCKER_SHA256_FORMAT_INVALID'}
    return $m.Value.ToUpperInvariant()
}
function Copy-Evidence([string[]]$Lines,[string]$Marker,[string]$Extension) {
    $prefix=$Marker+'='
    $hits=@($Lines | Where-Object {([string]$_).StartsWith($prefix)})
    if($hits.Count -eq 0) {return $null}
    if($hits.Count -ne 1) {throw "DUPLICATE_EVIDENCE_MARKER:$Marker"}
    $remote=([string]$hits[0]).Substring($prefix.Length)
    $regex='^/home/ubuntu/pai_demo/pai_ng_maxstroke_r2/ng_maxstroke_r2_[0-9]{8}T[0-9]{6}Z_[0-9]+\.'+$Extension+'$'
    if($remote -cnotmatch $regex) {throw "EVIDENCE_REMOTE_PATH_INVALID:$Marker"}
    $actualRemote=Hash-Remote $remote
    $dest=Join-Path $download ([System.IO.Path]::GetFileName($remote))
    if(-not(Test-Path -LiteralPath $dest)) {
        & docker cp "${containerName}:$remote" $dest | Out-Host
        Assert-Rc $LASTEXITCODE "COPY_$Marker"
    }
    $actualLocal=Hash-Local $dest
    Write-Host "${Marker}_REMOTE_SHA256=$actualRemote"
    Write-Host "${Marker}_LOCAL_SHA256=$actualLocal"
    if($actualLocal -cne $actualRemote) {throw "EVIDENCE_HASH_MISMATCH:$Marker"}
    Write-Host "${Marker}_LOCAL=$dest"
    return $dest
}
try {
    if(-not(Test-Path -LiteralPath $download -PathType Container)) {
        throw 'DOWNLOADS_FOLDER_MISSING'
    }
    $running=@(& docker inspect --format '{{.State.Running}}' $containerName 2>&1)
    $rc=$LASTEXITCODE
    if($rc -ne 0 -or $running.Count -ne 1 -or
        ([string]$running[0]).Trim() -cne 'true') {
        throw 'EXISTING_CONTAINER_NOT_RUNNING'
    }
    & docker exec --user ubuntu $containerName test -d $stage
    $rc=$LASTEXITCODE
    if($rc -eq 1) {
        & docker exec --user ubuntu $containerName mkdir -m 700 $stage
        Assert-Rc $LASTEXITCODE 'CREATE_R2_FOLDER'
    }
    elseif($rc -ne 0) {throw 'CHECK_R2_FOLDER_FAILED'}
    foreach($s in $sources) {
        $local=Join-Path $PSScriptRoot $s.Name
        if((Hash-Local $local) -cne ([string]$s.Sha).ToUpperInvariant()) {
            throw "R2_LOCAL_SOURCE_SHA_MISMATCH:$($s.Name)"
        }
        $remote="$stage/$($s.Name)"
        & docker exec --user ubuntu $containerName test -f $remote
        $rc=$LASTEXITCODE
        if($rc -eq 1) {
            & docker cp $local "${containerName}:$remote" | Out-Host
            Assert-Rc $LASTEXITCODE 'COPY_R2_SOURCE'
        }
        elseif($rc -ne 0) {throw 'CHECK_REMOTE_SOURCE_FAILED'}
        if((Hash-Remote $remote) -cne ([string]$s.Sha).ToUpperInvariant()) {
            throw "R2_REMOTE_SOURCE_SHA_MISMATCH:$($s.Name)"
        }
    }
    Write-Host 'R2_SOURCE_HASHES=PASS'
    $base=@('exec','--user','ubuntu',
            '-e','HOME=/home/ubuntu',
            '-e','DISPLAY=:0',
            '-e',"IGN_PARTITION=$part",
            '-e','PYTHONDONTWRITEBYTECODE=1',
            $containerName,'python3','-B',"$stage/pai_ng_maxstroke_r2.py")
    $test=@(& docker @base --action selftest 2>&1)
    $testRc=$LASTEXITCODE
    foreach($line in $test){Write-Host ([string]$line)}
    if($testRc -ne 0 -or $test -notcontains 'R2_OFFLINE_SELFTEST=PASS_NO_GAZEBO_NO_MOTION') {
        throw "R2_SELFTEST_HOLD_EXIT_$testRc"
    }
    $pre=@(& docker @base --action preflight 2>&1)
    $preRc=$LASTEXITCODE
    foreach($line in $pre){Write-Host ([string]$line)}
    if($preRc -ne 0 -or $pre -notcontains 'R2_PREFLIGHT_GATE=PASS_READONLY_HOME_AND_STREAM') {
        throw "R2_PREFLIGHT_HOLD_EXIT_$preRc"
    }
    if($Action -ceq 'Preflight') {
        Write-Host 'R2_RUNNER_GATE=PASS_PREFLIGHT_ONLY_NO_MOTION'
        exit 0
    }
    Write-Host 'R2_SIM_ONLY_OWNER_LONG_STROKE_REQUEST_CONFIRMED=True'
    $lines=@(& docker @base --action record --authorization $auth 2>&1)
    $motionRc=$LASTEXITCODE
    foreach($line in $lines){Write-Host ([string]$line)}
    # Always recover partial evidence; never suppress a HOLD from the motion.
    $movie=Copy-Evidence $lines 'R2_VIDEO_REMOTE' 'mp4'
    $motion=Copy-Evidence $lines 'R2_MOTION_REMOTE' 'motion\.json'
    $witness=Copy-Evidence $lines 'R2_WITNESS_REMOTE' 'witness\.json'
    if($motionRc -ne 0) {throw "R2_MOTION_HOLD_EXIT_$motionRc"}
    if([string]::IsNullOrWhiteSpace($movie) -or
       [string]::IsNullOrWhiteSpace($motion) -or
       [string]::IsNullOrWhiteSpace($witness)) {
       throw 'R2_MOTION_SUCCESS_EVIDENCE_MISSING'
    }
    $w=Get-Content -LiteralPath $witness -Encoding UTF8 -Raw | ConvertFrom-Json
    if($w.mode -cne 'SIM_ONLY_HUMAN_DEFECT_EXTENDED_MOVEMENT_R2_VIDEO' -or
       @('PASS_100MM_MEASURED','PASS_BOUNDED_MAX_MEASURED_BELOW_100MM') -cnotcontains ([string]$w.status) -or
       $w.joint_return_verified -ne $true -or
       $w.no_model_pose_writes -ne $true -or
       $w.v4_ai_fusion -cne 'REVIEW' -or
       $w.manual_override_demo -ne $true -or
       ([double]$w.measured_final_x_mm) -gt -5.0 -or
       (Hash-Local $movie) -cne ([string]$w.video_sha256).ToUpperInvariant() -or
       (Hash-Local $motion) -cne ([string]$w.motion_sha256).ToUpperInvariant()) {
        throw 'R2_WITNESS_CONTENT_INVALID'
    }
    if($w.status -ceq 'PASS_100MM_MEASURED' -and
       ([double]$w.measured_final_x_mm) -gt -100.0) {
        throw 'R2_FALSE_100MM_PASS'
    }
    Write-Host "R2_FINAL_CUBE_DX_MM=$($w.measured_final_x_mm)"
    Write-Host "R2_RUNNER_GATE=$($w.status)"
    Write-Host "R2_FINAL_VIDEO=$movie"
    exit 0
}
catch {
    Write-Host "R2_RUNNER_GATE=HOLD; REASON=$($_.Exception.Message)"
    Write-Host 'NO_AUTOMATIC_MOTION_RETRY=True'
    exit 3
}
