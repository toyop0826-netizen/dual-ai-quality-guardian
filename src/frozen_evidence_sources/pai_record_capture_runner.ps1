param([switch]$Execute)

$ErrorActionPreference = 'Stop'
$containerName = 'physicalai_crane'
$partition = 'pai_record_scene_wood_v1_20261101'
$remoteDir = '/home/ubuntu/pai_demo/pai_record_capture_v1'
$localDir = $PSScriptRoot
$downloads = Join-Path $env:USERPROFILE 'Downloads'
$expectedV6 = '0176B44EF8CB10D515D9824523730082EADD9FEC4DAE1E0B2C5E27FD2CD97A54'
$expectedRecordWorld = 'CEFFCCBD044509FC97BFB4D5A076886EC1057BAF5A1FE103D28E2380A7690A64'
$scene = '/home/ubuntu/pai_demo/pai_record_scene_wood_v1/pai_record_scene_preserve_wood_camera.sdf'
$v6World = '/home/ubuntu/pai_demo/pai_native_j1_pusher_20261101_v6/world_native_j1_v6.sdf'
$auth = 'AUTHORIZE_RECORD_SCENE_GAZEBO_ONLY_R4_0215_ONCE'
$files = @(
    @{Name='pai_record_capture_r4.py';Sha='A479B3E677CC062AC3DD45B67BD2F0080714854379C18223AFEC3670CA074E4A'},
    @{Name='pai_v6_r4_cube_push_0215.py';Sha='B1CFE6075B94A79E677DB8FA9D66F591DA87C1C9F347AB7A589D96601AE14CA5'},
    @{Name='pai_v6_precontact_mesh_audit.py';Sha='74AB17BF56B8F691BD73156DADC908CA72DBFCDC9FB28E7459C4AC77A0E52D9D'}
)

function Require-Local([string]$name, [string]$expected) {
    $p = Join-Path $localDir $name
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) {throw "LOCAL_FILE_NOT_FOUND:$name"}
    $h = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
    if ($h -ne $expected) { throw "LOCAL_HASH_MISMATCH:$name" }
    return $p
}

function Check-Remote([string]$path, [string]$expected) {
    $lines = @(docker exec --user ubuntu $containerName sha256sum $path 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {throw "REMOTE_SHA_COMMAND_FAILED:$path"}
    $m = [regex]::Match([string]$lines[0], '^[0-9a-fA-F]{64}')
    if (-not $m.Success -or $m.Value.ToUpperInvariant() -ne $expected) {
        throw "REMOTE_HASH_MISMATCH:$path"
    }
}

function Ensure-Remote([string]$local, [string]$remote, [string]$expected) {
    docker exec --user ubuntu $containerName test -e $remote
    $code = $LASTEXITCODE
    if ($code -eq 1) {
        docker cp $local "${containerName}:$remote"
        if ($LASTEXITCODE -ne 0) {throw "REMOTE_COPY_FAILED:$remote"}
    }
    elseif ($code -ne 0) {throw "REMOTE_EXISTENCE_CHECK_FAILED:$remote"}
    Check-Remote $remote $expected
}

function Copy-VerifiedOutput([string[]]$lines,[string]$label,[string]$regexPath) {
    $mark = $label + '='
    $hits = @($lines | Where-Object { "$_".StartsWith($mark) })
    if ($hits.Count -ne 1) {throw "FILE_MARKER_NOT_UNIQUE:$label"}
    $remote = ([string]$hits[0]).Substring($mark.Length)
    if ($remote -cnotmatch $regexPath) {throw "REMOTE_EVIDENCE_PATH_NOT_ALLOWED:$label"}
    $name = [IO.Path]::GetFileName($remote)
    $local = Join-Path $downloads $name
    if (Test-Path -LiteralPath $local) {throw "EVIDENCE_EXISTS_NO_OVERWRITE:$name"}
    $line = @(docker exec --user ubuntu $containerName sha256sum $remote 2>&1)
    if ($LASTEXITCODE -ne 0 -or $line.Count -ne 1) {throw "EVIDENCE_REMOTE_SHA_FAILED:$label"}
    $m = [regex]::Match([string]$line[0], '^[0-9a-fA-F]{64}')
    if (-not $m.Success) {throw "EVIDENCE_REMOTE_SHA_INVALID:$label"}
    docker cp "${containerName}:$remote" $local
    if ($LASTEXITCODE -ne 0) {throw "EVIDENCE_COPY_FAILED:$label"}
    if ((Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash -ne $m.Value.ToUpperInvariant()) {
        throw "EVIDENCE_LOCAL_REMOTE_HASH_MISMATCH:$label"
    }
    Write-Host "${label}_LOCAL=$local"
    return $local
}

try {
    $running = @(docker inspect --format '{{.State.Running}}' $containerName 2>&1)
    if ($LASTEXITCODE -ne 0 -or $running.Count -ne 1 -or "$($running[0])".Trim() -ne 'true') {
        throw 'DOCKER_CONTAINER_NOT_RUNNING'
    }
    Check-Remote $scene $expectedRecordWorld
    Check-Remote $v6World $expectedV6
    Write-Host 'RECORD_ORIGINAL_AND_SCENE_HASH_PASS=True'

    foreach ($entry in $files) {
        $local = Require-Local $entry.Name $entry.Sha
    }
    docker exec --user ubuntu $containerName test -d $remoteDir
    $hasDir = $LASTEXITCODE
    if ($hasDir -eq 1) {
        docker exec --user ubuntu $containerName mkdir -m 700 $remoteDir
        if ($LASTEXITCODE -ne 0) {throw 'CAPTURE_DIRECTORY_CREATE_FAILED'}
    }
    elseif ($hasDir -ne 0) {throw 'CAPTURE_DIRECTORY_CHECK_FAILED'}
    foreach ($entry in $files) {
        $local = Join-Path $localDir $entry.Name
        Ensure-Remote $local "$remoteDir/$($entry.Name)" $entry.Sha
    }
    Write-Host 'RECORD_SOURCE_FILES_VERIFIED=PASS'

    $remotePy = "$remoteDir/pai_record_capture_r4.py"
    $common = @('--user', 'ubuntu', '-e', 'HOME=/home/ubuntu', '-e', 'DISPLAY=:0',
                '-e', "IGN_PARTITION=$partition", '-e', 'PYTHONDONTWRITEBYTECODE=1',
                $containerName, 'python3', '-B', $remotePy)
    $self = @(docker exec @common --action selftest)
    $selfRc = $LASTEXITCODE
    foreach ($line in $self) {Write-Host "$line"}
    if ($selfRc -ne 0 -or -not ($self -contains 'RECORD_CAPTURE_SELFTEST=PASS_NO_MOTION')) {
        throw "CAPTURE_SELFTEST_HOLD_EXIT_$selfRc"
    }

    if (-not $Execute) {
        Write-Host 'RECORD_PREFLIGHT_START'
        $lines = @(docker exec @common --action preflight)
        $rc = $LASTEXITCODE
        foreach ($line in $lines) {Write-Host "$line"}
        if ($rc -ne 0 -or -not ($lines -contains 'RECORD_PREFLIGHT_GATE=PASS_NO_MOTION_SCREENSHOT_SAVED')) {
            throw "RECORD_PREFLIGHT_HOLD_EXIT_$rc"
        }
        $regex = '^/home/ubuntu/pai_demo/pai_record_capture_v1/record_gui_check_[0-9]{8}T[0-9]{6}Z_[0-9]+\.png$'
        $png = Copy-VerifiedOutput $lines 'RECORD_SCREENSHOT_REMOTE' $regex
        Write-Host 'RECORD_CAPTURE_RUNNER=PASS_PREFLIGHT_NO_MOTION'
        Write-Host 'NEXT_ACTION=OPTIONAL_RECORD_ONLY_AFTER_GUI_VISUAL_REVIEW'
        exit 0
    }

    # This branch is the ONLY route that can issue the R4 +0.215/0.0 joint commands.
    Write-Host 'RECORD_SIMULATION_R4_ONCE_START'
    $lines = @(docker exec @common --action record --authorization $auth)
    $rc = $LASTEXITCODE
    foreach ($line in $lines) {Write-Host "$line"}
    if (@($lines | Where-Object { "$($_)".StartsWith('RECORD_VIDEO_REMOTE=') }).Count -eq 1) {
        $videoRegex = '^/home/ubuntu/pai_demo/pai_record_capture_v1/record_gazebo_r4_[0-9]{8}T[0-9]{6}Z_[0-9]+\.mp4$'
        $video = Copy-VerifiedOutput $lines 'RECORD_VIDEO_REMOTE' $videoRegex
    }
    if (@($lines | Where-Object { "$($_)".StartsWith('RECORD_MOTION_REPORT_REMOTE=') }).Count -eq 1) {
        $motionRegex = '^/home/ubuntu/pai_demo/pai_v6_r4_cube_push_[0-9]{8}T[0-9]{6}_[0-9]+\.json$'
        $motion = Copy-VerifiedOutput $lines 'RECORD_MOTION_REPORT_REMOTE' $motionRegex
    }
    if (@($lines | Where-Object { "$($_)".StartsWith('RECORD_WITNESS_REMOTE=') }).Count -eq 1) {
        $witnessRegex = '^/home/ubuntu/pai_demo/pai_record_capture_v1/record_gazebo_r4_[0-9]{8}T[0-9]{6}Z_[0-9]+\.witness\.json$'
        $witness = Copy-VerifiedOutput $lines 'RECORD_WITNESS_REMOTE' $witnessRegex
    }
    if ($rc -ne 0 -or -not ($lines -contains 'RECORD_RUNNER_GATE=PASS_VIDEO_AND_MEASURED_SIM_ONLY')) {
        throw "RECORD_R4_HOLD_NO_RETRY_EXIT_$rc"
    }
    if (-not $video -or -not $witness -or -not $motion) {
        throw 'RECORD_RESULT_FILES_INCOMPLETE'
    }
    $report = Get-Content -LiteralPath $witness -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($report.mode -ne 'INDEPENDENT_RECORD_WORLD_R4_GAZEBO_GUI_CAPTURE' -or
        $report.status -ne 'PASS_RECORDING_AND_MEASURED_PUSH' -or
        $report.record_partition -ne $partition -or
        $report.record_world_sha256.ToUpperInvariant() -ne $expectedRecordWorld -or
        $report.robot_hardware_used -ne $false -or
        [double]$report.cube_dx_mm -lt 0.7 -or
        (Get-FileHash -LiteralPath $video -Algorithm SHA256).Hash -ne $report.video_sha256.ToUpperInvariant() -or
        (Get-FileHash -LiteralPath $motion -Algorithm SHA256).Hash -ne $report.motion_report_sha256.ToUpperInvariant()) {
        throw 'VIDEO_WITNESS_OR_MEASURED_PUSH_INVALID'
    }
    Check-Remote $v6World $expectedV6
    Write-Host 'RECORD_VIDEO_AND_R4_WITNESS_VERIFIED=PASS'
    Write-Host "RECORD_SUBMISSION_VIDEO=$video"
    exit 0
}
catch {
    Write-Host 'RECORD_CAPTURE_RUNNER=HOLD'
    Write-Host "RECORD_CAPTURE_REASON=$($_.Exception.Message)"
    exit 3
}
