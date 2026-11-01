param(
    [ValidateSet('Preflight','Execute')]
    [string]$Action = 'Preflight'
)
$ErrorActionPreference = 'Stop'
$containerName = 'physicalai_crane'
$downloads = Join-Path $env:USERPROFILE 'Downloads'
$remoteDir = '/home/ubuntu/pai_demo/pai_dual_ai_v4_defect_20261102'
$remoteScript = "$remoteDir/pai_dual_ai_v4.py"
$remoteReport = "$remoteDir/dual_ai_v4_defect_result.json"
$scriptPath = Join-Path $PSScriptRoot 'pai_dual_ai_v4.py'
$scriptSha = 'FE582A00E487ECAB6AA8150F9A4DA9973F8CB2968807D2989B0312B5EE19A998'
$expectedImage = '655B5472E83CBB58AC42791310F61D0679C17CF279D0A325C687D97A2AD7963E'
$expectedWitness = '8B759DA10E573077951C88EF85E37148ACBA8E720DD5CE160B45C6912C14884B'
$expectedWorld = '81F859680CEC05D1F2B599A923FC015A29A0BBFF818B264666745378B1D047AB'
$remoteImage = '/home/ubuntu/pai_demo/pai_ng_camera_clearface_v4_capture_once/defect_camera_v4_640x480.png'
$remoteWitness = '/home/ubuntu/pai_demo/pai_ng_camera_clearface_v4_capture_once/defect_camera_v4_witness.json'
$remoteWorld = '/home/ubuntu/pai_demo/pai_ng_camera_clearface_v4/scene_DEFECT_scratch_wood_camera.sdf'
$initialOpenAI = [Environment]::GetEnvironmentVariable('OPENAI_API_KEY', 'Process')
$initialGemini = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'Process')

function Assert-Digest([string]$path, [string]$expected) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw 'LOCAL_FILE_MISSING'
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -cne $expected) {
        throw "LOCAL_SHA256_MISMATCH_$([System.IO.Path]::GetFileName($path))"
    }
}
function Check-Exit([int]$rc, [string]$stage) {
    if ($rc -ne 0) {
        throw "$($stage)_EXIT_$rc"
    }
}
function Remote-Exists([string]$path) {
    & docker exec --user ubuntu $containerName test -f $path
    $rc = $LASTEXITCODE
    if ($rc -eq 0) { return $true }
    if ($rc -eq 1) { return $false }
    throw "REMOTE_EXISTENCE_QUERY_FAILED_$rc"
}
function Remote-Digest([string]$path, [string]$expected) {
    $lines = @(& docker exec --user ubuntu $containerName sha256sum $path)
    $rc = $LASTEXITCODE
    Check-Exit $rc 'REMOTE_HASH_READ'
    if ($lines.Count -ne 1) { throw 'REMOTE_HASH_LINE_COUNT_INVALID' }
    $m = [regex]::Match([string]$lines[0], '^[A-Fa-f0-9]{64}(?=\s)')
    if (-not $m.Success) { throw 'REMOTE_HASH_PARSE_FAILED' }
    $actual = $m.Value.ToUpperInvariant()
    if ($actual -cne $expected) { throw 'REMOTE_HASH_MISMATCH' }
    return $actual
}
function Run-Stage([string]$stage,[string]$sentinel) {
    $lines = @(& docker exec --user ubuntu -e HOME=/home/ubuntu -e PYTHONDONTWRITEBYTECODE=1 $containerName python3 -B $remoteScript --stage $stage)
    $rc = $LASTEXITCODE
    foreach ($line in $lines) { Write-Host ([string]$line) }
    if ($rc -ne 0 -or -not ($lines -contains $sentinel)) {
        throw "PYTHON_STAGE_$($stage)_HOLD_EXIT_$rc"
    }
}
function Ensure-Secret([string]$name) {
    $present = [Environment]::GetEnvironmentVariable($name, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($present)) { return }
    $secret = Read-Host -Prompt "Enter $name locally (hidden input)" -AsSecureString
    if ($null -eq $secret) { throw "SECRET_MISSING_$name" }
    $ptr = [IntPtr]::Zero
    $plain = $null
    try {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        if ([string]::IsNullOrWhiteSpace($plain)) { throw "SECRET_EMPTY_$name" }
        [Environment]::SetEnvironmentVariable($name, $plain, 'Process')
    }
    finally {
        $plain = $null
        if ($ptr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
        $secret.Dispose()
    }
}
function Collect-And-Verify-Report {
    if (-not (Remote-Exists $remoteReport)) {
        Write-Host 'V4_DUAL_AI_REPORT_REMOTE=NOT_CREATED'
        return $false
    }
    $hashLines = @(& docker exec --user ubuntu $containerName sha256sum $remoteReport)
    $rc = $LASTEXITCODE
    Check-Exit $rc 'REMOTE_REPORT_SHA'
    if ($hashLines.Count -ne 1) { throw 'REPORT_HASH_LINE_COUNT_INVALID' }
    $m = [regex]::Match([string]$hashLines[0], '^[A-Fa-f0-9]{64}(?=\s)')
    if (-not $m.Success) { throw 'REPORT_HASH_PARSE_INVALID' }
    $reportHash = $m.Value.ToUpperInvariant()
    $dest = Join-Path $downloads 'dual_ai_v4_defect_result.json'
    if (-not (Test-Path -LiteralPath $dest)) {
        & docker cp "${containerName}:$remoteReport" $dest | Out-Host
        $rc = $LASTEXITCODE
        Check-Exit $rc 'REPORT_COPY'
    }
    Assert-Digest $dest $reportHash
    $r = Get-Content -LiteralPath $dest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($r.mode -cne 'REAL_TWO_PROVIDER_V4_IMAGE_INFERENCE_NO_ROBOT_CONTROL' -or
        ([string]$r.source_image_sha256).ToUpperInvariant() -cne $expectedImage -or
        ([string]$r.source_capture_witness_sha256).ToUpperInvariant() -cne $expectedWitness -or
        ([string]$r.source_world_sha256).ToUpperInvariant() -cne $expectedWorld -or
        $r.human_ground_truth_sent_to_providers -ne $false -or
        $r.robot_commands_sent -ne 0 -or
        $r.gazebo_model_pose_writes -ne 0 -or
        $r.gazebo_server_starts -ne 0 -or
        $r.robot_motion_authorized -ne $false -or
        $r.ng_movement_observed -ne $false) {
        throw 'REPORT_PROVENANCE_OR_SAFETY_INVALID'
    }
    $o = $r.providers.openai
    $g = $r.providers.gemini
    if ($r.fusion.decision -ceq 'DEFECT') {
        if ($o.status -cne 'PASS' -or $g.status -cne 'PASS' -or
            $o.label -cne 'DEFECT' -or $g.label -cne 'DEFECT' -or
            $r.fusion.next_action -cne 'NG_CANDIDATE_ONLY_NO_MOTION') {
            throw 'UNSUPPORTED_DEFECT_FUSION'
        }
    } elseif ($r.fusion.decision -ceq 'REVIEW') {
        if ($o.status -ceq 'PASS' -and $g.status -ceq 'PASS' -and
            $o.label -ceq 'DEFECT' -and $g.label -ceq 'DEFECT') {
            throw 'INCORRECT_REVIEW_FUSION'
        }
    } else {
        throw 'UNKNOWN_FUSION_DECISION'
    }
    Write-Host "V4_DUAL_AI_REPORT_LOCAL=$dest"
    Write-Host "V4_DUAL_AI_REPORT_HASH_VERIFIED=$reportHash"
    Write-Host 'V4_DUAL_AI_REPORT_CONTENT_VERIFIED=PASS'
    return $true
}

try {
    if (-not (Test-Path -LiteralPath $downloads -PathType Container)) {
        throw 'DOWNLOADS_DIRECTORY_MISSING'
    }
    Assert-Digest $scriptPath $scriptSha
    Assert-Digest (Join-Path $downloads 'v4_clearface_defect_camera_v4_640x480.png') $expectedImage
    Assert-Digest (Join-Path $downloads 'v4_clearface_defect_camera_v4_witness.json') $expectedWitness
    Write-Host 'V4_DUAL_AI_LOCAL_HASHES=PASS'

    $state = @(& docker inspect --format '{{.State.Running}}' $containerName)
    $rc = $LASTEXITCODE
    if ($rc -ne 0 -or $state.Count -ne 1 -or ([string]$state[0]).Trim() -cne 'true') {
        throw 'DOCKER_CONTAINER_NOT_RUNNING'
    }
    & docker exec --user ubuntu $containerName test -d $remoteDir
    $rc = $LASTEXITCODE
    if ($rc -eq 1) {
        & docker exec --user ubuntu $containerName mkdir -m 700 $remoteDir
        Check-Exit $LASTEXITCODE 'STAGE_DIRECTORY_CREATE'
    } elseif ($rc -ne 0) {
        throw "STAGE_DIRECTORY_QUERY_FAILED_$rc"
    }
    if (-not (Remote-Exists $remoteScript)) {
        & docker cp $scriptPath "${containerName}:$remoteScript" | Out-Host
        Check-Exit $LASTEXITCODE 'SCRIPT_COPY'
    }
    $unused = Remote-Digest $remoteScript $scriptSha
    $unused = Remote-Digest $remoteImage $expectedImage
    $unused = Remote-Digest $remoteWitness $expectedWitness
    $unused = Remote-Digest $remoteWorld $expectedWorld
    Write-Host 'V4_DUAL_AI_REMOTE_HASHES=PASS'
    Run-Stage 'selftest' 'V4_DUAL_AI_SELFTEST=PASS_NO_NETWORK_NO_MOTION'
    Run-Stage 'verify' 'V4_DUAL_AI_PREFLIGHT=PASS_PINNED_IMAGE_NO_API_NO_MOTION'
    Write-Host 'V4_DUAL_AI_PREFLIGHT_COMPLETE=PASS_NO_API_NO_MOTION'
    if ($Action -ceq 'Preflight') { exit 0 }

    if ([string]::IsNullOrWhiteSpace($env:GEMINI_API_KEY) -and
        -not [string]::IsNullOrWhiteSpace($env:GOOGLE_API_KEY)) {
        [Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $env:GOOGLE_API_KEY, 'Process')
    }
    Ensure-Secret 'OPENAI_API_KEY'
    Ensure-Secret 'GEMINI_API_KEY'
    Write-Host 'V4_DUAL_AI_INFERENCE_REQUEST=ONE_SHOT_NO_ROBOT_CONTROL'

    $lines = @(& docker exec --user ubuntu -e HOME=/home/ubuntu -e PYTHONDONTWRITEBYTECODE=1 -e OPENAI_API_KEY -e GEMINI_API_KEY $containerName python3 -B $remoteScript --stage infer)
    $rc = $LASTEXITCODE
    foreach ($line in $lines) { Write-Host ([string]$line) }
    $evidenceOk = Collect-And-Verify-Report
    if ($rc -ne 0) { throw "INFERENCE_REPORTED_HOLD_EXIT_$rc" }
    if (-not $evidenceOk) { throw 'INFERENCE_SUCCEEDED_WITHOUT_EVIDENCE' }
    if (-not (($lines -contains 'V4_DUAL_AI_GATE=PASS_DUAL_DEFECT_CANDIDATE_NO_MOTION') -or
               ($lines -contains 'V4_DUAL_AI_GATE=PASS_INFERENCE_REVIEW_NO_MOTION'))) {
        throw 'INFERENCE_SUCCESS_SENTINEL_MISSING'
    }
    Write-Host 'V4_DUAL_AI_RUNNER_GATE=PASS_REAL_RESPONSES_VERIFIED_NO_MOTION'
    exit 0
}
catch {
    Write-Host "V4_DUAL_AI_RUNNER_GATE=HOLD; REASON=$($_.Exception.Message)"
    Write-Host 'NO_AUTOMATIC_RETRY=True'
    Write-Host 'ROBOT_COMMANDS_SENT=0'
    exit 3
}
finally {
    [Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $initialOpenAI, 'Process')
    [Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $initialGemini, 'Process')
}
