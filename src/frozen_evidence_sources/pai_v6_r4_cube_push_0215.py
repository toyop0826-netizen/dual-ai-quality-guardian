#!/usr/bin/env python3
"""Gazebo-only V6 R4: first bounded OK-side physical cube push (+0.215 rad).

The default modes never publish joint commands. The execute mode requires an
explicit simulation-only token, a frozen-world hash, validated mesh-audit
provenance, live no-motion preflight, and a single identified Gazebo process.
This is an intentional dynamic contact probe, NOT validated bin sorting or hardware control.
R4: extra static STL/OBB contact-envelope audit before a bounded simulation-only contact probe.
During motion, any malformed frame immediately requests abort/return and HOLD.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time

BASE = Path('/home/ubuntu/pai_demo/pai_native_j1_pusher_20261101_v6')
PART = 'pai_native_j1_push_20261101_v6'
TOPIC = '/model/crane_plus/joint/crane_plus_joint1/0/cmd_pos'
AUDIT = Path('/home/ubuntu/pai_demo/pai_v6_precontact_mesh_audit_20261101T115815Z_1793534295875582156.json')
MESH_DIR = Path('/home/ubuntu/airobot_ws/src/crane_plus/crane_plus_description/meshes/collision')
CODE_HASH = 'e92e0300f06cdef1fa432252e5582c58f39121dd45bda39ea44e560e5d743c47'
WORLD_HASH = '0176b44ef8cb10d515d9824523730082eadd9fec4dae1e0b2c5e27fd2cd97a54'
AUTH = 'AUTHORIZE_GAZEBO_ONLY_V6_R4_CUBE_PUSH_0215'
TARGET = 0.215
EXPECTED_PEAK_MIN = 0.195
EXPECTED_PEAK_MAX = 0.220
MAX_ABS_NEGATIVE_RAD = 0.015
MAX_CUBE_SHIFT_MM = 12.0
MAX_BASE_SHIFT_MM = 2.0
MIN_FINAL_POSITIVE_X_MM = 0.7
MAX_RETURN_ERROR_RAD = 0.010

DRIVER_CPP = r'''#include <ignition/transport.hh>
#include <ignition/msgs.hh>
#include <chrono>
#include <iostream>
#include <thread>
#include <poll.h>
#include <unistd.h>

static bool abort_requested() {
    struct pollfd p = {STDIN_FILENO, (short)(POLLIN | POLLHUP), 0};
    int r = poll(&p, 1, 0);
    if (r < 0) return true;
    if (r == 0) return false;
    if ((p.revents & (POLLIN | POLLHUP | POLLERR | POLLNVAL)) == 0) return false;
    char c = 0;
    ssize_t n = read(STDIN_FILENO, &c, 1);
    return n <= 0 || c == '!';
}

int main() {
    const std::string topic = "/model/crane_plus/joint/crane_plus_joint1/0/cmd_pos";
    ignition::transport::Node node;
    auto pub = node.Advertise<ignition::msgs::Double>(topic);
    if (!pub.Valid()) {
        std::cout << "R4_CONTACT_DRIVER=HOLD_ADVERTISE_FAILED\n" << std::flush;
        return 3;
    }
    bool connected = false;
    for (int i = 0; i < 60; ++i) {
        if (pub.HasConnections()) { connected = true; break; }
        if (abort_requested()) {
            std::cout << "R4_CONTACT_DRIVER=HOLD_ABORT_BEFORE_MOTION\n" << std::flush;
            return 3;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (!connected) {
        std::cout << "R4_CONTACT_DRIVER=HOLD_NO_SUBSCRIBER\n" << std::flush;
        return 3;
    }
    // A disconnected Python supervisor must never initiate new motion.
    if (abort_requested()) {
        std::cout << "R4_CONTACT_DRIVER=HOLD_ABORT_BEFORE_MOTION\n" << std::flush;
        return 3;
    }

    ignition::msgs::Double outward;
    outward.set_data(0.215);
    if (!pub.Publish(outward)) {
        std::cout << "R4_CONTACT_DRIVER=HOLD_OUT_PUBLISH_FAILED\n" << std::flush;
        return 3;
    }
    std::cout << "J1_R4_CUBE_PUSH_COMMAND_PUBLISHED=0.215\n" << std::flush;
    bool abort = false;
    for (int i = 0; i < 80; ++i) {
        if (abort_requested()) { abort = true; break; }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    ignition::msgs::Double zero;
    zero.set_data(0.0);
    bool any = false;
    for (int i = 0; i < 6; ++i) {
        bool sent = pub.Publish(zero);
        any = sent || any;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    std::cout << "J1_RETURN_ZERO_COMMAND_PUBLISHED=" << (any ? "True" : "False") << "\n" << std::flush;
    std::this_thread::sleep_for(std::chrono::milliseconds(2200));
    if (abort) {
        std::cout << "R4_CONTACT_DRIVER=HOLD_ABORT_REQUESTED_RETURN_ATTEMPTED\n" << std::flush;
        return 3;
    }
    if (!any) {
        std::cout << "R4_CONTACT_DRIVER=HOLD_RETURN_PUBLISH_FAILED\n" << std::flush;
        return 3;
    }
    std::cout << "R4_CONTACT_DRIVER=PASS_COMMANDS_ISSUED_ONLY\n" << std::flush;
    return 0;
}
'''


class Hold(RuntimeError):
    pass


def require(ok, msg):
    if not ok:
        raise Hold(msg)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify_file(path, expected, label):
    require(path.is_file() and not path.is_symlink(), label + '_MISSING_OR_SYMLINK')
    require(sha256(path.read_bytes()) == expected, label + '_HASH_MISMATCH')


def verify_audit():
    require(AUDIT.is_file() and not AUDIT.is_symlink(), 'AUDIT_EVIDENCE_MISSING')
    data = AUDIT.read_bytes()
    report = json.loads(data)
    require(report.get('audit_type') == 'READONLY_V6_SDF_STL_SWEPT_PROXY_PREFLIGHT', 'AUDIT_TYPE_INVALID')
    require(report.get('world_sha256_expected') == WORLD_HASH, 'AUDIT_WORLD_MISMATCH')
    require(report.get('gate') == 'PASS_CONSERVATIVE_PRECONTACT_PROXY_ONLY', 'AUDIT_NOT_PASS')
    require(report.get('gazebo_queries') == 0 and report.get('joint_commands_sent') == 0, 'AUDIT_NOT_READONLY')
    require(report.get('robot_motion_authorized') is False, 'AUDIT_MOTION_FLAG_UNEXPECTED')
    require(report.get('possible_unintended_collision_pairs') == [], 'AUDIT_CONFLICT_PAIRS')
    sweeps = report.get('sweeps', {})
    require(set(sweeps) == {'OK', 'NG'}, 'AUDIT_DIRECTIONS_INCOMPLETE')
    for label, end, minimum in [('OK', .170, 1.5), ('NG', -.130, 1.4)]:
        row = sweeps[label]
        require(abs(float(row['end_command_target_rad'])-end) < 1e-8,
                'AUDIT_END_MISMATCH_' + label)
        require(abs(float(row['sample_spacing_rad'])-.005) < 1e-8,
                'AUDIT_GRID_MISMATCH_' + label)
        require(float(row['intended_pusher_cube_min_clearance_mm']) > minimum,
                'AUDIT_CLEARANCE_INSUFFICIENT_' + label)
        require(float(row['mesh_cube_min_clearance_mm']) > 40.,
                'AUDIT_MESH_CUBE_RISK_' + label)
        require(float(row['mesh_table_min_clearance_mm']) > 30.,
                'AUDIT_MESH_TABLE_RISK_' + label)
        require(float(row['pusher_table_min_clearance_mm']) > 10.,
                'AUDIT_PUSHER_TABLE_RISK_' + label)
    meshes = report.get('mesh_manifest', [])
    require(len(meshes) == 6 and len({row['stl'] for row in meshes}) == 6,
            'AUDIT_MESH_MANIFEST_INVALID')
    parent = MESH_DIR.resolve(strict=True)
    for row in meshes:
        name = row['stl']
        require(isinstance(name, str) and name.endswith('.stl') and '/' not in name
                and '\\' not in name and name not in ('.', '..'),
                'AUDIT_MESH_FILENAME_INVALID')
        mesh = MESH_DIR/name
        require(mesh.is_file() and mesh.resolve(strict=True).parent == parent,
                'AUDIT_MESH_MISSING_OR_OUTSIDE_ALLOWLIST')
        require(sha256(mesh.read_bytes()) == row['sha256'], 'AUDIT_MESH_CHANGED:' + name)
    print('V6_FROZEN_PRECONTACT_AUDIT_PASS=True', flush=True)
    print('V6_AUDIT_SHA256=' + sha256(data), flush=True)
    return sha256(data)



MESH_AUDIT_SOURCE = Path(__file__).resolve().parent/'pai_v6_precontact_mesh_audit.py'
MESH_AUDIT_SHA256 = '74ab17bf56b8f691bd73156dadc908ca72dbfcdc9fb28e7459c4ac77a0e52d9d'
CONTACT_SWEEP_LIMIT_RAD = .220


def verify_contact_envelope():
    """Read-only SDF/STL OBB sweep for first contact; allow intended pair ONLY."""
    import importlib.util
    verify_file(MESH_AUDIT_SOURCE,MESH_AUDIT_SHA256,'FROZEN_MESH_AUDIT_SOURCE')
    spec=importlib.util.spec_from_file_location('pai_r4_mesh_audit',str(MESH_AUDIT_SOURCE))
    require(spec is not None and spec.loader is not None,'MESH_AUDIT_MODULE_LOAD_FAIL')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(module.WORLD_SHA256==WORLD_HASH and abs(module.STEP_RAD-.005)<1e-12,
            'MESH_AUDIT_PARAMETERS_CHANGED')
    scene=module.scene_load(module.WORLD)
    module.ENDS={'OK':CONTACT_SWEEP_LIMIT_RAD}
    scans, issues=module.scan(scene)
    intended='PUSHER:OK vs CUBE'
    anomalies=[row for row in issues if (row.get('pair')!=intended or
                                              row.get('direction')!='OK' or
                                              row.get('is_intended_pusher') is not True)]
    s=scans['OK']
    # Only the intended pusher/cube overlap is permitted in this proxy audit.
    ok=(not anomalies and len(issues)>=1 and len(scans)==1 and
        abs(s['end_command_target_rad']-.220)<1e-10 and
        s['sample_count']==45 and
        -6.0 < s['intended_pusher_cube_min_clearance_mm'] < -0.1 and
        s['other_pusher_cube_min_clearance_mm']>10.0 and
        s['mesh_cube_min_clearance_mm']>30.0 and
        s['mesh_table_min_clearance_mm']>30.0 and
        s['pusher_table_min_clearance_mm']>10.0 and
        len(scene[-1])==6)
    report=dict(mode='READONLY_V6_R4_OK_CONTACT_ENVELOPE_PROXY',
                status='PASS_PROXY_INTENDED_CONTACT_ONLY' if ok else 'HOLD',
                intended_contact_only=not anomalies and len(issues)>=1,
                static_cube_at_initial_position=True,
                world_sha256=WORLD_HASH,
                mesh_audit_source_sha256=MESH_AUDIT_SHA256,
                max_swept_joint_rad=CONTACT_SWEEP_LIMIT_RAD,
                sweep=scans['OK'],candidate_pairs=issues,
                mesh_manifest=scene[-1],gazebo_queries=0,joint_commands_sent=0,
                robot_hardware_used=False,
                limitations=['Rigid J1-only OBB sweep; not exact triangle contact.',
                             'Cube held at its INITIAL pose in this audit; actual cube will move.',
                             'Dynamics, impulses, internal robot collision pairs and camera video NOT validated.',
                             'No physical robot or hardware control.'])
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+str(time.time_ns())
    p=Path('/home/ubuntu/pai_demo')/('pai_v6_r4_contact_envelope_'+stamp+'.json')
    with p.open('x',encoding='utf-8') as fh:
        json.dump(report,fh,indent=2,allow_nan=False)
    saved=json.loads(p.read_text(encoding='utf-8'))
    require(saved['status']==report['status'] and saved['candidate_pairs']==report['candidate_pairs'],
            'CONTACT_ENVELOPE_EVIDENCE_READBACK_INVALID')
    print('V6_R4_CONTACT_ENVELOPE_JSON='+str(p),flush=True)
    print('R4_CONTACT_SWEEP_END_RAD=%.3f'%CONTACT_SWEEP_LIMIT_RAD,flush=True)
    print('R4_EXPECTED_INTENDED_CONTACT_PAIRS=%d'%len(issues),flush=True)
    print('R4_UNEXPECTED_PROXY_CONFLICTS=%d'%len(anomalies),flush=True)
    print('R4_INTENDED_OBB_CLEARANCE_MIN_MM=%.4f'%s['intended_pusher_cube_min_clearance_mm'],flush=True)
    print('R4_NONINTENDED_MESH_CUBE_MIN_MM=%.4f'%s['mesh_cube_min_clearance_mm'],flush=True)
    print('R4_MESH_TABLE_MIN_MM=%.4f'%s['mesh_table_min_clearance_mm'],flush=True)
    require(ok,'CONTACT_ENVELOPE_PROXY_HOLD')
    print('V6_R4_CONTACT_ENVELOPE_GATE=PASS_PROXY_INTENDED_CONTACT_ONLY',flush=True)
    return sha256(p.read_bytes())


def v6_module():
    require(Path('/.dockerenv').exists(), 'SIM_CONTAINER_REQUIRED')
    require(os.geteuid() == 1000, 'UBUNTU_UID_REQUIRED')
    require(os.environ.get('HOME') == '/home/ubuntu', 'HOME_MISMATCH')
    require(os.environ.get('IGN_PARTITION') == PART, 'V6_PARTITION_MISMATCH')
    verify_file(BASE/'pai_v6_preflight.py', CODE_HASH, 'FROZEN_V6_DRIVER')
    verify_file(BASE/'world_native_j1_v6.sdf', WORLD_HASH, 'FROZEN_V6_WORLD')
    sys.path.insert(0, str(BASE))
    import pai_v6_preflight as v
    m = v.static_guard()
    require(m.get('partition') == PART and m.get('trial_enabled') is False,
            'V6_MANIFEST_UNEXPECTED')
    pid = v.read_pid()
    require(pid is not None and v.alive(pid), 'V6_GAZEBO_PROCESS_ABSENT')
    v.owned(pid)
    require(v.advertised(), 'V6_WORLD_NOT_READY')
    return v


def verify_no_command_publisher(v):
    info = v.cli(['ign', 'topic', '-i', '-t', TOPIC], timeout=8)
    require(info.returncode == 0, 'J1_TOPIC_INFO_FAILED')
    response = (info.stdout + info.stderr).decode('utf-8', 'replace').strip()
    expected = 'No publishers on topic [' + TOPIC + ']'
    require(response == expected, 'COMPETING_J1_PUBLISHER_OR_TOPIC_INFO_CHANGED')
    print('OTHER_J1_COMMAND_PUBLISHERS=0', flush=True)


def install_pose_frame_guard(v):
    """Keep the frozen V6 pose parser intact; recover only transient CLI framing.

    Never merge messages or accept duplicate Pose_V headers. Outside motion,
    retry up to two *fresh CLI calls* for a clean single message. During motion,
    retain fail-closed behavior (zero retries) and shorten CLI read timeout.
    """
    original_snapshot = v.snapshot
    original_cli = v.cli
    state = {'motion': False, 'transient_frames': 0}

    def guarded_cli(args, timeout=8, env=None):
        if (state['motion'] and args == ['ign', 'topic', '-e', '-n', '1',
                                        '-t', v.POSE_TOPIC]):
            timeout = min(float(timeout), 1.5)
        return original_cli(args, timeout=timeout, env=env)

    def guarded_snapshot():
        allowed = 1 if state['motion'] else 3
        for attempt in range(allowed):
            try:
                result = original_snapshot()
                require(isinstance(result, tuple) and len(result) == 3,
                        'POSE_RESULT_UNEXPECTED_SHAPE')
                return result
            except Exception as exc:
                if (type(exc).__name__ != 'Hold' or
                        str(exc) != 'MULTIPLE_POSE_V_HEADERS'):
                    raise
                state['transient_frames'] += 1
                if state['motion']:
                    print('POSE_V_MULTIPLE_HEADERS_DURING_MOTION=HOLD', flush=True)
                    raise
                print('POSE_V_MULTIPLE_HEADERS_DISCARDED=' +
                      str(attempt + 1), flush=True)
                if attempt + 1 == allowed:
                    raise Hold('POSE_V_RETRY_EXHAUSTED_NO_VALID_SINGLE_FRAME') from exc
                time.sleep(0.06)
        raise Hold('POSE_V_RETRY_INTERNAL_ERROR')

    v.cli = guarded_cli
    v.snapshot = guarded_snapshot
    return state


def live_gate(v):
    v.preflight()  # Gazebo pose reads, subscriber probe; NO command publication.
    cube, base, yaw = v.snapshot()
    require(v.distance(cube, v.CUBE) < .004, 'CUBE_INITIAL_OUT_OF_BOUNDS')
    require(v.distance(base, (0., 0., 1.015)) < .005, 'BASE_INITIAL_OUT_OF_BOUNDS')
    require(abs(v.angle_diff(yaw, v.START_Q)) < .012, 'J1_INITIAL_OUT_OF_BOUNDS')
    verify_no_command_publisher(v)
    print('V6_LIVE_PRECONTACT_GATE=PASS_NO_MOTION', flush=True)
    return cube, base, yaw


def compile_driver(folder):
    src = folder/'contact_r4.cc'
    exe = folder/'contact_r4'
    src.write_text(DRIVER_CPP, encoding='utf-8', newline='\n')
    flags = subprocess.run(['pkg-config', '--cflags', '--libs',
                            'ignition-transport11', 'ignition-msgs8'],
                           capture_output=True, text=True, timeout=8, check=False)
    require(flags.returncode == 0, 'GAZEBO_DEV_LIBRARIES_MISSING')
    args = ['c++', '-std=c++17', '-O0', '-Wall', '-Wextra', str(src), '-o', str(exe)] + shlex.split(flags.stdout)
    result = subprocess.run(args, capture_output=True, text=True, timeout=45, check=False)
    if result.returncode != 0:
        print('CXX_COMPILE_ERROR=' + (result.stderr or result.stdout)[-1200:], flush=True)
    require(result.returncode == 0 and exe.is_file() and os.access(exe, os.X_OK),
            'R4_CONTACT_DRIVER_BUILD_FAILED')
    print('V6_R4_CUBE_PUSH_DRIVER_BUILD_PASS=True', flush=True)
    return exe


def calc_row(v, initial, snapshot, elapsed):
    cube, base, yaw = snapshot
    dx, dy, dz = ((a-b)*1000.0 for a,b in zip(cube,initial[0]))
    q = v.angle_diff(yaw, initial[2])
    cube_mm = v.distance(cube, initial[0])*1000.0
    base_mm = v.distance(base, initial[1])*1000.0
    require(all(math.isfinite(x) for x in (dx,dy,dz,q,cube_mm,base_mm)), 'NONFINITE_POSE_SAMPLE')
    return dict(t_s=round(elapsed,4), j1_link_yaw_delta_rad=round(q,8),
                cube_dx_mm=round(dx,5),cube_dy_mm=round(dy,5),cube_dz_mm=round(dz,5),
                cube_distance_mm=round(cube_mm,5),base_distance_mm=round(base_mm,5))


def unsafe_sample(row):
    if row['j1_link_yaw_delta_rad'] > EXPECTED_PEAK_MAX:
        return 'J1_EXCESSIVE_ROTATION'
    if row['j1_link_yaw_delta_rad'] < -MAX_ABS_NEGATIVE_RAD:
        return 'J1_MOVED_WRONG_DIRECTION'
    if row['cube_distance_mm'] > MAX_CUBE_SHIFT_MM:
        return 'CUBE_OUTSIDE_BOUNDED_ZONE'
    if row['cube_dx_mm'] < -0.7:
        return 'CUBE_MOVED_OPPOSITE_DIRECTION'
    if abs(row['cube_dy_mm']) > 8.0:
        return 'CUBE_EXCESSIVE_LATERAL_SHIFT'
    if abs(row['cube_dz_mm']) > 2.0:
        return 'CUBE_EXCESSIVE_HEIGHT_SHIFT'
    if row['base_distance_mm'] > MAX_BASE_SHIFT_MM:
        return 'UNEXPECTED_BASE_MOVEMENT'
    return ''


def send_abort(process):
    try:
        if process.poll() is None and process.stdin and not process.stdin.closed:
            process.stdin.write('!\n')
            process.stdin.flush()
            return True
    except (OSError,ValueError):
        pass
    return False


def evaluate(samples, final, driver_return, driver_text):
    require(driver_return == 0, 'MOTION_DRIVER_RETURNED_ERROR')
    require('J1_R4_CUBE_PUSH_COMMAND_PUBLISHED=0.215' in driver_text,
            'OUTWARD_COMMAND_MARKER_MISSING')
    require('J1_RETURN_ZERO_COMMAND_PUBLISHED=True' in driver_text,
            'RETURN_COMMAND_MARKER_MISSING')
    require('R4_CONTACT_DRIVER=PASS_COMMANDS_ISSUED_ONLY' in driver_text,
            'DRIVER_PASS_MARKER_MISSING')
    require(len(samples) >= 6, 'TOO_FEW_POSE_SAMPLES')
    require(all(not unsafe_sample(row) for row in samples), 'UNSAFE_SAMPLE_RECORDED')
    peak = max(row['j1_link_yaw_delta_rad'] for row in samples)
    require(EXPECTED_PEAK_MIN <= peak <= EXPECTED_PEAK_MAX, 'J1_TARGET_NOT_MEASURED')
    require(not unsafe_sample(final), 'UNSAFE_FINAL_POSE')
    require(abs(final['j1_link_yaw_delta_rad']) < MAX_RETURN_ERROR_RAD,
            'J1_RETURN_NOT_VERIFIED')
    require(final['cube_dx_mm'] >= MIN_FINAL_POSITIVE_X_MM,
            'CUBE_POSITIVE_X_DISPLACEMENT_NOT_VERIFIED')
    require(max(row['cube_dx_mm'] for row in samples) >= MIN_FINAL_POSITIVE_X_MM,
            'CUBE_DISPLACEMENT_NOT_SAMPLED_DURING_MOTION')
    require(final['base_distance_mm'] < MAX_BASE_SHIFT_MM,
            'BASE_NOT_AT_INITIAL_POSITION')
    return peak


def execute(v, exe, initial, audit_sha, contact_audit_sha, observation_state=None):
    report = dict(mode='V6_GAZEBO_ONLY_R4_OK_0215_CUBE_PUSH', status='HOLD',
                  target_j1_joint_rad=TARGET, prior_precontact_audit_sha256=audit_sha,
                  contact_envelope_audit_sha256=contact_audit_sha,robot_hardware_used=False,
                  gazebo_pose_writes=0, initial_cube_model_origin_m=list(initial[0]),
                  initial_j1_world_yaw_rad=initial[2], samples=[])
    proc=None
    outcome=3
    pending_error=None
    try:
        verify_no_command_publisher(v)
        if observation_state is not None:
            observation_state['motion']=True
        proc=subprocess.Popen([str(exe)],stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              text=True,start_new_session=True)
        started=time.monotonic()
        while proc.poll() is None and time.monotonic()-started < 16:
            try:
                row=calc_row(v,initial,v.snapshot(),time.monotonic()-started)
                report['samples'].append(row)
                issue=unsafe_sample(row)
                if issue:
                    pending_error=issue
                    print('R4_EMERGENCY_RETURN_REQUEST='+issue,flush=True)
                    print('R4_EMERGENCY_RETURN_SENT='+str(send_abort(proc)),flush=True)
                    break
            except Exception as exc:
                pending_error='POSE_OBSERVATION_FAILED:'+type(exc).__name__
                print('R4_EMERGENCY_RETURN_REQUEST='+pending_error,flush=True)
                print('R4_EMERGENCY_RETURN_SENT='+str(send_abort(proc)),flush=True)
                break
            time.sleep(0.1)
        if proc.poll() is None and time.monotonic()-started >= 16:
            pending_error='DRIVER_TIME_LIMIT_REACHED'
            print('R4_EMERGENCY_RETURN_SENT='+str(send_abort(proc)),flush=True)
        try:
            out,err=proc.communicate(timeout=12)
        except subprocess.TimeoutExpired as exc:
            send_abort(proc)
            raise Hold('DRIVER_UNRESPONSIVE_RETURN_NOT_VERIFIED') from exc
        if observation_state is not None:
            observation_state['motion']=False
        report['driver_output']=out[-3000:]
        report['driver_exit_code']=proc.returncode
        print(out,end='',flush=True)
        if err.strip():
            print('R4_DRIVER_STDERR='+err[-1000:],flush=True)
        require(pending_error is None,'EARLY_ABORT:'+str(pending_error))
        final=calc_row(v,initial,v.snapshot(),time.monotonic()-started)
        report['final_sample']=final
        peak=evaluate(report['samples'],final,proc.returncode,out)
        report.update(status='PASS_OBSERVED_CUBE_X_DISPLACEMENT_AND_J1_RETURN',
                      j1_peak_delta_rad=peak,
                      j1_final_delta_rad=final['j1_link_yaw_delta_rad'],
                      cube_final_dx_mm=final['cube_dx_mm'],
                      cube_final_dy_mm=final['cube_dy_mm'],
                      cube_final_dz_mm=final['cube_dz_mm'],
                      cube_max_recorded_shift_mm=max(row['cube_distance_mm'] for row in report['samples']))
        outcome=0
    except (Exception,KeyboardInterrupt) as exc:
        report['status']='HOLD'
        report['error']=type(exc).__name__+':'+str(exc)[:500]
        outcome=3
    finally:
        if proc is not None and proc.poll() is None:
            print('R4_DRIVER_STILL_RUNNING_RETURN_NOT_VERIFIED=True',flush=True)
            print('R4_EMERGENCY_RETURN_SENT='+str(send_abort(proc)),flush=True)
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                print('OPERATOR_ACTION=PAUSE_GAZEBO_AND_INSPECT_NO_RETRY',flush=True)
            report['status']='HOLD'
            report['error']='DRIVER_STILL_RUNNING_OR_RETURN_UNVERIFIED'
            outcome=3
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+str(time.time_ns())
        evidence=Path('/home/ubuntu/pai_demo')/('pai_v6_r4_cube_push_'+stamp+'.json')
        try:
            with evidence.open('x',encoding='utf-8') as fh:
                json.dump(report,fh,indent=2,allow_nan=False)
            check=json.loads(evidence.read_text(encoding='utf-8'))
            require(check['status']==report['status'] and check['mode']==report['mode'],
                    'EVIDENCE_READBACK_MISMATCH')
            print('V6_R4_CUBE_PUSH_EVIDENCE_JSON='+str(evidence),flush=True)
        except (OSError,ValueError,Hold,KeyError) as err:
            print('V6_R4_CUBE_PUSH_EVIDENCE_WRITE_HOLD='+type(err).__name__+':'+str(err)[:160],flush=True)
            outcome=3
            report['status']='HOLD'
            report['error']='EVIDENCE_NOT_SAVED_OR_VERIFIED'
    if outcome==0:
        print('R4_J1_PEAK_RAD=%.6f'%report['j1_peak_delta_rad'],flush=True)
        print('R4_J1_RETURN_ERROR_RAD=%.6f'%abs(report['j1_final_delta_rad']),flush=True)
        print('R4_CUBE_FINAL_X_MM=%.5f'%report['cube_final_dx_mm'],flush=True)
        print('R4_CUBE_MAX_SHIFT_MM=%.5f'%report['cube_max_recorded_shift_mm'],flush=True)
        print('V6_R4_CUBE_PUSH_GATE=PASS_OBSERVED_CUBE_X_DISPLACEMENT_AND_J1_RETURN',flush=True)
    else:
        print('V6_R4_CUBE_PUSH_GATE=HOLD',flush=True)
        print('V6_R4_CUBE_PUSH_REASON='+report.get('error','UNVERIFIED_OUTCOME'),flush=True)
    return outcome


def selftest():
    require(DRIVER_CPP.count('outward.set_data(0.215)')==1,'CPP_TARGET_CHANGED')
    require(DRIVER_CPP.count('zero.set_data(0.0)')==1,'CPP_RETURN_MISSING')
    require('pub.Publish(outward)' in DRIVER_CPP and 'pub.Publish(zero)' in DRIVER_CPP,
            'CPP_SEQUENCE_CHANGED')
    def mk(q, x=0.0, y=0.0, z=0.0, base=0.0):
        return dict(t_s=0.,j1_link_yaw_delta_rad=q,cube_dx_mm=x,cube_dy_mm=y,
                    cube_dz_mm=z,cube_distance_mm=math.sqrt(x*x+y*y+z*z),base_distance_mm=base)
    good=[mk(0),mk(.08),mk(.20,1.2),mk(.215,2.5),mk(.215,2.5),mk(.10,2.5),mk(0,2.5)]
    flags=('J1_R4_CUBE_PUSH_COMMAND_PUBLISHED=0.215\n'
           'J1_RETURN_ZERO_COMMAND_PUBLISHED=True\n'
           'R4_CONTACT_DRIVER=PASS_COMMANDS_ISSUED_ONLY\n')
    require(abs(evaluate(good,good[-1],0,flags)-.215)<1e-8,'SELFTEST_GOOD')
    bads=[('CUBE_BACK',mk(.1,-1)),('CUBE_FAR',mk(.1,15)),('CUBE_Y',mk(.1,1,10)),
          ('CUBE_Z',mk(.1,1,0,4)),('J1_OVERSHOOT',mk(.240)),
          ('J1_REVERSED',mk(-.030)),('BASE_MOVED',mk(.1,1,0,0,3))]
    for name,row in bads:
        require(bool(unsafe_sample(row)),'SELFTEST_MISSED_'+name)
    for name,rows in [('NO_CUBE_MOVE',[mk(x['j1_link_yaw_delta_rad']) for x in good]),
                      ('NO_RETURN',[mk(.215,2.5)]*7),
                      ('NO_J1_MOVE',[mk(0,2.5)]*7),
                      ('TOO_FEW',good[:2])]:
        try:
            evaluate(rows,rows[-1],0,flags)
            raise RuntimeError('FALSE_PASS_'+name)
        except Hold:
            pass
    for name,rc,msg in [('DRIVER_ERROR',3,flags),('MISSING_RETURN',0,flags.replace('J1_RETURN_ZERO_COMMAND_PUBLISHED=True','J1_RETURN_ZERO_COMMAND_PUBLISHED=False'))]:
        try:
            evaluate(good,good[-1],rc,msg)
            raise RuntimeError('FALSE_PASS_'+name)
        except Hold:pass
    # Regression: discard only transient malformed CLI frames before motion.
    class FakeV:
        POSE_TOPIC='/world/default/pose/info'
        def __init__(self,events): self.events=list(events);self.calls=[]
        def snapshot(self):
            result=self.events.pop(0)
            if isinstance(result,Exception):raise result
            return result
        def cli(self,args,timeout=8,env=None): self.calls.append(timeout)
    sample=((0.,-.1,1.015),(0.,0.,1.015),-1.571170863)
    v=FakeV([Hold('MULTIPLE_POSE_V_HEADERS'),sample]);g=install_pose_frame_guard(v)
    require(v.snapshot()==sample and g['transient_frames']==1,'FRAME_RETRY_FAIL')
    v=FakeV([Hold('MULTIPLE_POSE_V_HEADERS'),sample]);g=install_pose_frame_guard(v);g['motion']=True
    try:
        v.snapshot();raise RuntimeError('FRAME_FALSE_PASS_DURING_MOTION')
    except Hold:require(len(v.events)==1,'FRAME_UNSAFE_RETRY_DURING_MOTION')
    print('V6_R4_CUBE_PUSH_OFFLINE_SELFTEST=PASS',flush=True)
    print('COMMAND_MESSAGES_PUBLISHED=0',flush=True)
    return 0


def main():
    require(0.0<TARGET<=.215 and TARGET<EXPECTED_PEAK_MAX<=.220 and
            EXPECTED_PEAK_MAX <= CONTACT_SWEEP_LIMIT_RAD,
            'R4_TARGET_OUTSIDE_BOUNDED_ZONE')
    p=argparse.ArgumentParser(allow_abbrev=False)
    flags=p.add_mutually_exclusive_group(required=True)
    flags.add_argument('--selftest',action='store_true')
    flags.add_argument('--preflight',action='store_true')
    flags.add_argument('--execute',action='store_true')
    p.add_argument('--authorization',default='')
    a=p.parse_args()
    require((a.execute and a.authorization==AUTH) or
            (not a.execute and a.authorization==''),
            'EXPLICIT_GAZEBO_ONLY_R4_AUTHORIZATION_REQUIRED_OR_UNEXPECTED')
    if a.selftest:
        return selftest()
    old_sha=verify_audit()
    contact_sha=verify_contact_envelope()
    v=v6_module()
    observation_state=install_pose_frame_guard(v)
    initial=live_gate(v)
    with tempfile.TemporaryDirectory(prefix='pai_v6_r4_contact_',dir='/tmp') as temp:
        exe=compile_driver(Path(temp))
        if a.preflight:
            print('V6_R4_CUBE_PUSH_PREFLIGHT=PASS_NO_MOTION',flush=True)
            print('ROBOT_MOTION_AUTHORIZED=False',flush=True)
            return 0
        print('GAZEBO_ONLY_CONTACT_MOTION_AUTHORIZATION=ACCEPTED',flush=True)
        return execute(v,exe,initial,old_sha,contact_sha,observation_state)


if __name__=='__main__':
    try:
        sys.exit(main())
    except (Exception,KeyboardInterrupt) as exc:
        print('V6_R4_CUBE_PUSH_GATE=HOLD',flush=True)
        print('V6_R4_CUBE_PUSH_FATAL='+type(exc).__name__+':'+str(exc)[:500],flush=True)
        sys.exit(3)
