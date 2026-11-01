#!/usr/bin/env python3
"""Gazebo-only recording of the already-approved R4 controller in the independent wood/camera scene.

Two actions: --preflight (read-only sim observations + screenshot), --record (explicit
one-shot simulation-only R4 motion and genuine Gazebo GUI screen capture).
Never modifies the original V6 world or saved R4 source; no hardware use.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time

PART='pai_record_scene_wood_v1_20261101'
REC=Path('/home/ubuntu/pai_demo/pai_record_scene_wood_v1')
CAP=Path('/home/ubuntu/pai_demo/pai_record_capture_v1')
V6=Path('/home/ubuntu/pai_demo/pai_native_j1_pusher_20261101_v6')
REC_W=REC/'pai_record_scene_preserve_wood_camera.sdf'
REC_WORLD_SHA='ceffccbd044509fc97bfb4d5a076886ec1057baf5a1fe103d28e2380a7690a64'
V6_WORLD_SHA='0176b44ef8cb10d515d9824523730082eadd9fec4dae1e0b2c5e27fd2cd97a54'
V6_CODE_SHA='e92e0300f06cdef1fa432252e5582c58f39121dd45bda39ea44e560e5d743c47'
LAUNCH=REC/'pai_record_scene_launcher_identity_fixed.py'
LAUNCH_SHA='6ff637f95e59fb0c643a3b1f559358bfc88db9486036375c7a255421a064f9e4'
R4_SRC=CAP/'pai_v6_r4_cube_push_0215.py'
R4_SHA='b1cfe6075b94a79e677db8fa9d66f591da87c1c9f347ab7a589d96601ae14ca5'
MESH_SRC=CAP/'pai_v6_precontact_mesh_audit.py'
MESH_SHA='74ab17bf56b8f691bd73156dadc908ca72dbfcdc9fb28e7459c4ac77a0e52d9d'
TOKEN='AUTHORIZE_RECORD_SCENE_GAZEBO_ONLY_R4_0215_ONCE'
CUBE=(0.,-0.1,1.015)
YAW=-1.571170863


def require(ok, why):
    if not ok: raise RuntimeError(why)


def digest(path, expected, label):
    require(path.is_file() and not path.is_symlink(), label+'_MISSING')
    require(hashlib.sha256(path.read_bytes()).hexdigest()==expected,label+'_SHA256_MISMATCH')


def load_py(path, name):
    spec=importlib.util.spec_from_file_location(name,str(path))
    require(spec is not None and spec.loader is not None,'MODULE_LOAD_SPEC_MISSING')
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def guard():
    require(Path('/.dockerenv').is_file(), 'NOT_DOCKER')
    require(os.geteuid()==1000,'UBUNTU_UID_REQUIRED')
    require(os.environ.get('HOME')=='/home/ubuntu','HOME_MISMATCH')
    require(os.environ.get('IGN_PARTITION')==PART,'PARTITION_WRONG')
    require(os.environ.get('DISPLAY')==':0','DISPLAY_WRONG')
    require(CAP.is_dir() and not CAP.is_symlink(),'CAPTURE_DIRECTORY_WRONG')
    digest(REC_W,REC_WORLD_SHA,'RECORD_WORLD')
    digest(V6/'world_native_j1_v6.sdf',V6_WORLD_SHA,'FROZEN_V6_WORLD')
    digest(V6/'pai_v6_preflight.py',V6_CODE_SHA,'FROZEN_V6_HELPER')
    digest(LAUNCH,LAUNCH_SHA,'FIXED_RECORD_LAUNCHER')
    digest(R4_SRC,R4_SHA,'FROZEN_R4_CONTROL')
    digest(MESH_SRC,MESH_SHA,'FROZEN_R4_MESH_AUDIT')
    launch=load_py(LAUNCH,'record_launcher_attest')
    launch.guard_files()  # byte-exact: only camera + table albedo map differ from V6
    pserver=launch.get_recorded_pid('server')
    pgui=launch.get_recorded_pid('gui')
    require(pserver is not None and launch.verify_pid(pserver,'server'), 'RECORD_SERVER_IDENTITY_HOLD')
    require(pgui is not None and launch.verify_pid(pgui,'gui'), 'RECORD_GUI_IDENTITY_HOLD')
    require(launch.probe_world(),'RECORD_WORLD_SERVICE_MISSING')
    require(shutil.which('ffmpeg') is not None,'FFMPEG_MISSING')
    require(shutil.which('ffprobe') is not None,'FFPROBE_MISSING')
    require(shutil.which('xwininfo') is not None and shutil.which('xprop') is not None,'X11_INSPECTOR_MISSING')
    print('RECORD_SCENE_SERVER_IDENTITY=PASS',flush=True)
    print('RECORD_SCENE_GUI_IDENTITY=PASS',flush=True)
    print('RECORD_FROZEN_V6_UNCHANGED=PASS',flush=True)
    return pgui


def proc_run(args, timeout=8, **kw):
    return subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,timeout=timeout,check=False,stdin=subprocess.DEVNULL,**kw)


def list_windows(tree):
    return re.findall(r'^\s*(0x[0-9a-fA-F]+)\s+"Gazebo"\s*:', tree, re.M)


def read_window_owner(xprop_text):
    m=re.search(r'_NET_WM_PID(?:\([^)]*\))?\s*=\s*([0-9]+)',xprop_text)
    return int(m.group(1)) if m else None


def gui_group_owns_window(gui_pid,window_pid):
    if window_pid is None or window_pid < 2:return False
    p=Path('/proc')/str(window_pid)
    try:
        return (p.stat().st_uid==os.geteuid() and os.getpgid(window_pid)==gui_pid
                and ('IGN_PARTITION='+PART).encode() in (p/'environ').read_bytes().split(b'\x00'))
    except (OSError,ValueError): return False


def video_window(gui_pid):
    tr=proc_run(['xwininfo','-root','-tree'],timeout=7)
    require(tr.returncode==0, 'XWININFO_ROOT_FAILED:'+tr.stderr[-200:])
    candidates=list_windows(tr.stdout)
    require(candidates,'NO_NAMED_GAZEBO_WINDOWS')
    matched=[]
    for win in candidates[:30]:
        xp=proc_run(['xprop','-id',win,'_NET_WM_PID'],timeout=4)
        if xp.returncode!=0:continue
        owner=read_window_owner(xp.stdout)
        if not gui_group_owns_window(gui_pid,owner):continue
        wi=proc_run(['xwininfo','-id',win],timeout=5)
        if wi.returncode!=0 or 'Map State: IsViewable' not in wi.stdout:continue
        w=re.search(r'Width:\s*([0-9]+)',wi.stdout)
        h=re.search(r'Height:\s*([0-9]+)',wi.stdout)
        if not w or not h:continue
        dims=(int(w.group(1)),int(h.group(1)))
        if dims[0]>=650 and dims[1]>=500:
            matched.append((win,dims,owner))
    require(len(matched)==1,
            'RECORD_GUI_WINDOW_NOT_UNIQUE_OR_XPROP_PID_MISSING:matches='+str(matched))
    win,dims,owner=matched[0]
    print('RECORD_GUI_CAPTURE_WINDOW='+win,flush=True)
    print('RECORD_GUI_CAPTURE_DIMENSIONS=%dx%d'%dims,flush=True)
    print('RECORD_GUI_CAPTURE_XPID='+str(owner),flush=True)
    return win,dims


def record_preflight(v):
    cube1,base1,yaw1=v.snapshot()
    time.sleep(.65)
    cube2,base2,yaw2=v.snapshot()
    require(v.distance(cube1,CUBE)<.004 and v.distance(cube2,CUBE)<.004,
            'RECORD_CUBE_NOT_AT_INITIAL_POSITION')
    require(v.distance(cube1,cube2)<.0015,'RECORD_CUBE_NOT_STATIONARY')
    require(v.distance(base2,(0.,0.,1.015))<.004,'RECORD_ROBOT_BASE_NOT_INITIAL')
    require(abs(v.angle_diff(yaw2,YAW))<.012,'RECORD_J1_NOT_AT_ZERO_RELATIVE')
    require(abs(v.angle_diff(yaw1,yaw2))<.006,'RECORD_J1_NOT_STATIONARY')
    probe=V6/'j1_subscriber_probe'
    digest(probe,json.loads((V6/'manifest_v6.json').read_text())['j1_probe_sha256'], 'FROZEN_J1_PROBE')
    r=proc_run([str(probe)],timeout=12)
    require(r.returncode==0 and 'SUBSCRIBER_CONNECTION=PASS' in r.stdout
            and 'COMMAND_MESSAGES_PUBLISHED=0' in r.stdout, 'RECORD_J1_SUBSCRIBER_NOT_CONNECTED')
    print('RECORD_INITIAL_CUBE_M=' + ','.join('%.6f'%x for x in cube2),flush=True)
    print('RECORD_INITIAL_J1_WORLD_YAW_RAD=%.6f'%yaw2,flush=True)
    print('RECORD_J1_SUBSCRIBER_CONNECTED_NO_COMMAND_SENT=True',flush=True)
    return 0


def setup_r4():
    r4=load_py(R4_SRC,'record_r4_frozen')
    require(r4.PART!=PART and r4.WORLD_HASH==V6_WORLD_SHA,
            'R4_EXPECTED_ORIGINAL_PROVENANCE_CHANGED')
    require(abs(r4.TARGET-.215)<1e-12,'R4_TARGET_CHANGED')
    # The frozen R4 geometry audit is applicable: the record world differs
    # byte-exactly only in table visual albedo_map and a non-collision camera model.
    def recorded_module():
        sys.path.insert(0,str(V6))
        import pai_v6_preflight as v
        v.preflight=lambda:record_preflight(v)
        return v
    r4.v6_module=recorded_module
    return r4


def capture_still(win):
    now=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path=CAP/('record_gui_check_'+now+'_'+str(time.time_ns())+'.png')
    p=proc_run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error',
                '-f','x11grab','-framerate','1','-window_id',win,
                '-i',':0.0','-frames:v','1','-update','1','-n',str(path)],timeout=25)
    require(p.returncode==0, 'SCREENSHOT_FFMPEG_FAILED:'+p.stderr[-400:])
    require(path.is_file() and path.stat().st_size>3000,'SCREENSHOT_NOT_CREATED')
    hdr=path.open('rb').read(24)
    require(hdr[:8]==b'\x89PNG\r\n\x1a\n' and len(hdr)==24,'SCREENSHOT_CORRUPT')
    w,h=struct.unpack('>II',hdr[16:24]);require(600<=w<=8192 and 480<=h<=8192,'SCREENSHOT_DIMENSIONS_INVALID')
    print('RECORD_SCREENSHOT_REMOTE='+str(path),flush=True)
    print('RECORD_SCREENSHOT_SHA256='+hashlib.sha256(path.read_bytes()).hexdigest(),flush=True)
    return path


def ffprobe_video(path):
    p=proc_run(['ffprobe','-v','error','-select_streams','v:0',
                '-show_entries','stream=codec_name,width,height,nb_frames:format=duration',
                '-of','json',str(path)],timeout=15)
    require(p.returncode==0,'FFPROBE_FAILED:'+p.stderr[-200:])
    report=json.loads(p.stdout)
    streams=report.get('streams',[])
    require(len(streams)==1,'VIDEO_STREAM_NOT_ONE')
    s=streams[0]
    duration=float(report['format']['duration'])
    require(s['codec_name']=='h264' and int(s['width'])>=650 and int(s['height'])>=500,
            'VIDEO_CODEC_OR_RESOLUTION_NOT_OK')
    require(10.0<=duration<=23.0,'VIDEO_DURATION_OUTSIDE_EXPECTED_BOUNDS')
    require(path.stat().st_size>50000,'VIDEO_FILE_TOO_SMALL')
    return dict(duration_sec=duration,width=s['width'],height=s['height'],codec=s['codec_name'],size_bytes=path.stat().st_size)


def save_json_exclusive(path,payload):
    with path.open('x',encoding='utf8') as f:
        json.dump(payload,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.flush();os.fsync(f.fileno())
    loaded=json.loads(path.read_text(encoding='utf8'))
    require(loaded==payload,'VIDEO_WITNESS_JSON_READBACK_DIFF')


def capture_and_r4(r4, base_exec, win, v, exe, initial, audit_sha, contact_sha, obs_state):
    now=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest=CAP/('record_gazebo_r4_'+now+'_'+str(time.time_ns())+'.mp4')
    log=CAP/(dest.stem+'.ffmpeg.log')
    # The intent file is created BEFORE publishing anything. A failed attempt
    # cannot be repeated against an already-moved cube without new review.
    marker=CAP/'record_action_intent_once.json'
    intent={'mode':'RECORD_GAZEBO_SIM_ONLY_R4_ONCE','utc':now,
            'expected_world_sha256':REC_WORLD_SHA,'target_rad':.215,
            'v6_original_world_sha256':V6_WORLD_SHA,'video':str(dest),'no_hardware':True}
    save_json_exclusive(marker,intent)
    print('RECORD_ACTION_INTENT_FROZEN=True',flush=True)
    prior_reports={str(p) for p in Path('/home/ubuntu/pai_demo').glob('pai_v6_r4_cube_push_*.json')}
    command=['ffmpeg','-nostdin','-hide_banner','-loglevel','warning',
             '-f','x11grab','-framerate','15','-window_id',win,
             '-i',':0.0','-t','18',
             '-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2',
             '-c:v','libx264','-preset','ultrafast','-crf','22',
             '-pix_fmt','yuv420p','-movflags','+faststart','-n',str(dest)]
    start=time.monotonic()
    mov_rc=3
    with log.open('xb') as errlog:
        ff=subprocess.Popen(command,stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,stderr=errlog,close_fds=True,
                             start_new_session=True)
        try:
            time.sleep(2)
            require(ff.poll() is None,'FFMPEG_EXITED_BEFORE_SIMULATION_MOTION')
            print('RECORD_VIDEO_CAPTURE_RUNNING_BEFORE_MOTION=True',flush=True)
            mov_rc=base_exec(v,exe,initial,audit_sha,contact_sha,obs_state)
            print('RECORD_SIMULATION_R4_RETURN_CODE='+str(mov_rc),flush=True)
            remain=21-(time.monotonic()-start)
            if remain>0:
                try: ff.wait(timeout=min(remain,12))
                except subprocess.TimeoutExpired: pass
        finally:
            if ff.poll() is None:
                ff.terminate()
                try: ff.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    # Only the specific FFmpeg process created by this runner.
                    ff.kill();ff.wait(timeout=4)
        ff_rc=ff.returncode
    print('RECORD_FFMPEG_EXIT_CODE='+str(ff_rc),flush=True)
    if dest.exists():
        print('RECORD_VIDEO_REMOTE='+str(dest),flush=True)
    if mov_rc!=0:
        print('RECORD_CAPTURE_GATE=HOLD_SIMULATION_MOTION_NOT_VERIFIED',flush=True)
        return 3
    require(ff_rc==0,'FFMPEG_RECORDING_FAILED:code='+str(ff_rc))
    video_meta=ffprobe_video(dest)
    # The R4 controller creates one new result JSON. Capture it by snapshot
    # timestamp; additional concurrent invocations are forbidden by one-shot marker.
    results=[p for p in Path('/home/ubuntu/pai_demo').glob('pai_v6_r4_cube_push_*.json')
             if p.is_file() and str(p) not in prior_reports]
    verified=[]
    for p in results:
        d=json.loads(p.read_text(encoding='utf8'))
        if (d.get('mode')=='V6_GAZEBO_ONLY_R4_OK_0215_CUBE_PUSH' and
            d.get('status')=='PASS_OBSERVED_CUBE_X_DISPLACEMENT_AND_J1_RETURN'):
            verified.append((p,d))
    require(len(results)==1 and len(verified)==1,'RECORD_R4_CONTROLLER_EVIDENCE_NOT_UNIQUE')
    report_file,report=verified[0]
    require(report['cube_final_dx_mm']>=.7 and abs(report['j1_final_delta_rad'])<.01,
            'RECORD_R4_MEASURED_VALUES_NOT_PASS')
    witness={'mode':'INDEPENDENT_RECORD_WORLD_R4_GAZEBO_GUI_CAPTURE',
             'record_partition':PART,'record_world_sha256':REC_WORLD_SHA,
             'original_v6_world_sha256':V6_WORLD_SHA,
             'robot_hardware_used':False,'cube_visual_material_modified_by_runner':False,
             'scene_must_have_original_brown_gui_display_selected_by_operator':True,
             'control_source_sha256':R4_SHA,'motion_report_path':str(report_file),
             'motion_report_sha256':hashlib.sha256(report_file.read_bytes()).hexdigest(),
             'j1_peak_rad':report['j1_peak_delta_rad'],
             'j1_return_rad':report['j1_final_delta_rad'],
             'cube_dx_mm':report['cube_final_dx_mm'],
             'video_path':str(dest),'video_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
             'video_metadata':video_meta,'status':'PASS_RECORDING_AND_MEASURED_PUSH',
             'limitations':['Video proves GUI rendering during a separate R4-style simulation repeat, not actual bin sorting.',
                            'Original R4 controller evidence uses the V6 legacy mode label; this witness identifies the actual independent recording partition.',
                            'GUI color is manually adjusted by operator and not a portable SDF material override.']}
    witness_file=CAP/(dest.stem+'.witness.json')
    save_json_exclusive(witness_file,witness)
    print('RECORD_VIDEO_DURATION_S=%.3f'%video_meta['duration_sec'],flush=True)
    print('RECORD_CUBE_FINAL_DX_MM=%.5f'%witness['cube_dx_mm'],flush=True)
    print('RECORD_MOTION_REPORT_REMOTE='+str(report_file),flush=True)
    print('RECORD_WITNESS_REMOTE='+str(witness_file),flush=True)
    print('RECORD_CAPTURE_GATE=PASS_RECORDING_AND_MEASURED_PUSH',flush=True)
    return 0


def run(action,authorization):
    require(action in ('selftest','preflight','record'),'UNKNOWN_ACTION')
    require((action=='record' and authorization==TOKEN) or
            (action!='record' and not authorization),'SIMULATION_ONLY_EXPLICIT_AUTHORIZATION_REQUIRED_OR_UNEXPECTED')
    if action=='selftest':
        require(list_windows(' 0xaabbccef "Gazebo": class\n')==['0xaabbccef'],'WINDOW_REGEX_SELFTEST')
        require(read_window_owner('_NET_WM_PID(CARDINAL) = 432')==432,'XPID_PARSER_SELFTEST')
        require(read_window_owner('not found') is None,'XPID_MISSING_FALSE_PASS')
        require(not gui_group_owns_window(1,None),'OWNER_MISSING_FALSE_PASS')
        r4=setup_r4()
        require(r4.selftest()==0,'FROZEN_R4_SELFTEST_FAILED')
        print('RECORD_CAPTURE_SELFTEST=PASS_NO_MOTION',flush=True)
        return 0
    gui=guard()
    win,_=video_window(gui)
    r4=setup_r4()
    orig_execute=r4.execute
    if action=='record':
        require(not (CAP/'record_action_intent_once.json').exists(), 'ONE_SHOT_ALREADY_USED_NO_RETRY')
        r4.execute=lambda v,exe,initial,ah,ch,st: capture_and_r4(r4,orig_execute,win,v,exe,initial,ah,ch,st)
    old_args=sys.argv[:]
    try:
        sys.argv=['r4'] + (['--preflight'] if action=='preflight' else
                            ['--execute','--authorization',r4.AUTH])
        status=r4.main()
    finally:
        sys.argv=old_args
    if status!=0:return 3
    if action=='preflight':
        capture_still(win)
        print('RECORD_PREFLIGHT_GATE=PASS_NO_MOTION_SCREENSHOT_SAVED',flush=True)
    else:
        print('RECORD_RUNNER_GATE=PASS_VIDEO_AND_MEASURED_SIM_ONLY',flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--action',choices=['selftest','preflight','record'],required=True)
    parser.add_argument('--authorization',default='')
    args=parser.parse_args()
    try: return run(args.action,args.authorization)
    except (Exception,KeyboardInterrupt) as e:
        print('RECORD_RUNNER_GATE=HOLD',flush=True)
        print('RECORD_RUNNER_REASON='+type(e).__name__+':'+str(e)[:400],flush=True)
        return 3


if __name__=='__main__':
    sys.exit(main())
