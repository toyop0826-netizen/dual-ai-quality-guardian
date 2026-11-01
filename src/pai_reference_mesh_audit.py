#!/usr/bin/env python3
"""V6 read-only, conservative moving-mesh vs static scene precontact audit.

This program NEVER contacts Gazebo Transport, ROS, controllers, or hardware.
All collision geometry is read from the SHA-256-pinned V6 SDF and referenced STL files.
All arm links are ASSUMED to rotate rigidly about world Z with only joint 1 changing.
Result is NOT a dynamic contact/trajectory/torque safety certificate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import time
import xml.etree.ElementTree as ET

WORLD = Path('/home/ubuntu/pai_demo/pai_native_j1_pusher_20261101_v6/world_native_j1_v6.sdf')
WORLD_SHA256 = '0176b44ef8cb10d515d9824523730082eadd9fec4dae1e0b2c5e27fd2cd97a54'
MESH_PARENT = Path('/home/ubuntu/airobot_ws/src/crane_plus/crane_plus_description/meshes/collision')
DEFAULT_OUTPUT = Path('/home/ubuntu/pai_demo')
MAX_MESH_BYTES = 64 * 1024 * 1024
MAX_TRIANGLES = 700000
STEP_RAD = 0.005
# Strictly BEFORE the idealized first box overlap: OK=+0.1894, NG=-0.1486.
ENDS = {'OK': +0.170, 'NG': -0.130}
PUSHER_LINK = {'OK': 'crane_plus_link_hand', 'NG': 'crane_plus_link4'}
J1_PREFIX = 'pai_v6_precontact_mesh_audit_'


class Hold(RuntimeError):
    pass


def require(value, why):
    if not value:
        raise Hold(why)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def v3(node, key, n=6, default=None):
    text = node.findtext(key, default)
    require(text is not None, 'SDF_MISSING_' + key)
    seq = tuple(float(s) for s in text.split())
    require(len(seq) == n and all(math.isfinite(x) for x in seq), 'SDF_BAD_VECTOR_' + key)
    return seq


def pose(node):
    return v3(node, 'pose', 6, '0 0 0 0 0 0')


def dot(a, b):
    return sum(x*y for x,y in zip(a,b))


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def norm(a):
    return math.sqrt(dot(a,a))


def mv(m,v):
    return tuple(dot(row,v) for row in m)


def mm(a,b):
    return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def add(a,b):
    return tuple(x+y for x,y in zip(a,b))


def rot(r,p,y):
    cr,sr=math.cos(r),math.sin(r)
    cp,sp=math.cos(p),math.sin(p)
    cy,sy=math.cos(y),math.sin(y)
    return ((cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr),
            (sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr),
            (-sp,cp*sr,cp*cr))


def tf(*poses):
    r=((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
    t=(0.,0.,0.)
    for pp in poses:
        t=add(t,mv(r,pp[:3]))
        r=mm(r,rot(*pp[3:]))
    return t,r


def obb(*poses, size, local_center=(0.,0.,0.)):
    t,r=tf(*poses)
    t=add(t,mv(r,local_center))
    return (t, tuple(tuple(r[i][j] for i in range(3)) for j in range(3)),
            tuple(abs(x)*0.5 for x in size))


def sat_gap(a,b):
    """Positive gap proves separation. Nonpositive means OBBs intersect/touch.

    Note: positive is a SAT separating-axis gap, not Euclidean min distance.
    """
    ca,aa,ha=a
    cb,ab,hb=b
    delta=tuple(cb[i]-ca[i] for i in range(3))
    axes=list(aa)+list(ab)+[cross(x,y) for x in aa for y in ab]
    best=-math.inf
    for axis in axes:
        length=norm(axis)
        if length < 1e-10:
            continue
        u=tuple(x/length for x in axis)
        radius=sum(h*abs(dot(u,v)) for h,v in zip(ha,aa))+sum(h*abs(dot(u,v)) for h,v in zip(hb,ab))
        gap=abs(dot(delta,u))-radius
        best=max(best,gap)
    require(math.isfinite(best), 'NONFINITE_SAT_GAP')
    return best


def stl_bounds(raw):
    """Read STL triangle vertices with standard library, fail closed on bad meshes."""
    require(len(raw)>80 and len(raw)<=MAX_MESH_BYTES, 'STL_BYTES_INVALID')
    mn=[float('inf')]*3
    mx=[float('-inf')]*3
    def ingest(coords):
        require(len(coords)==3 and all(math.isfinite(x) for x in coords), 'STL_BAD_VERTEX')
        for i,x in enumerate(coords):
            mn[i]=min(mn[i],x)
            mx[i]=max(mx[i],x)
    count=None
    if len(raw)>=84:
        count=struct.unpack_from('<I', raw, 80)[0]
    if count is not None and count>0 and count<=MAX_TRIANGLES and 84+50*count==len(raw):
        for i in range(count):
            o=84+50*i+12
            for j in range(3):
                ingest(struct.unpack_from('<fff',raw,o+12*j))
        fmt='binary_stl'
        tri=count
    else:
        require(raw[:5].lower()==b'solid', 'STL_INVALID_BINARY_OR_ASCII_HEADER')
        try:
            lines=raw.decode('ascii').splitlines()
        except UnicodeDecodeError as exc:
            raise Hold('STL_ASCII_INVALID_ENCODING') from exc
        vertex_count=0
        for line in lines:
            words=line.strip().split()
            if not words or words[0].lower()!='vertex':
                continue
            require(len(words)==4, 'STL_ASCII_VERTEX_FORMAT')
            try:
                ingest(tuple(float(x) for x in words[1:]))
            except ValueError as exc:
                raise Hold('STL_ASCII_VERTEX_NONNUMERIC') from exc
            vertex_count+=1
            require(vertex_count<=3*MAX_TRIANGLES, 'STL_ASCII_TOO_MANY_VERTICES')
        require(vertex_count>0 and vertex_count%3==0, 'STL_ASCII_TRIANGLE_COUNT_BAD')
        fmt='ascii_stl'
        tri=vertex_count//3
    require(all(x<=y for x,y in zip(mn,mx)), 'STL_INVALID_BOUNDS')
    require(max(abs(x) for x in mn+mx)<2.0, 'STL_COORDINATES_GT_2M_UNEXPECTED_UNITS')
    return dict(triangles=tri,format=fmt,minimum=tuple(mn),maximum=tuple(mx))


def mesh_obb(model_pose, delta, link, coll, bounds):
    node=coll.find('geometry/mesh')
    require(node is not None, 'NOT_MESH_COLLISION')
    scales=v3(node, 'scale', 3, '1 1 1')
    require(all(x>0 and x<100 for x in scales), 'INVALID_MESH_SCALE')
    mins=bounds['minimum']
    maxs=bounds['maximum']
    center=tuple((x+y)*s/2 for x,y,s in zip(mins,maxs,scales))
    size=tuple((y-x)*s for x,y,s in zip(mins,maxs,scales))
    return obb(model_pose,(0,0,0,0,0,delta),pose(link),pose(coll),size=size,local_center=center)


def box_obb(model_node, link_node, collision):
    size=v3(collision, 'geometry/box/size', 3)
    require(all(x>0 for x in size), 'SDF_NONPOSITIVE_BOX')
    return obb(pose(model_node),pose(link_node),pose(collision),size=size)


def table_obb(model_node, link_node, collision):
    if collision.find('geometry/box') is not None:
        return box_obb(model_node, link_node, collision)
    if collision.find('geometry/cylinder') is not None:
        radius=float(collision.findtext('geometry/cylinder/radius','nan'))
        length=float(collision.findtext('geometry/cylinder/length','nan'))
        require(math.isfinite(radius) and math.isfinite(length)
                and radius>0 and length>0,'BAD_TABLE_CYLINDER')
        # A box circumscribes each cylindrical leg; false positives are HOLD.
        return obb(pose(model_node),pose(link_node),pose(collision),size=(2*radius,2*radius,length))
    raise Hold('UNKNOWN_TABLE_COLLISION_SHAPE')


def push_obb(model_pose, delta, link, collision):
    size=v3(collision,'geometry/box/size',3)
    return obb(model_pose,(0,0,0,0,0,delta),pose(link),pose(collision),size=size)


def mesh_uri(mesh_node):
    uri=(mesh_node.findtext('uri') or '').strip()
    require(uri.startswith('file:///'), 'NONLOCAL_MESH_URI')
    p=Path(uri[7:])
    real=p.resolve(strict=True)
    require(real.is_relative_to(MESH_PARENT.resolve(strict=True)), 'MESH_PATH_OUTSIDE_ALLOWLIST')
    require(real.suffix.lower()=='.stl' and real.is_file(), 'STL_NOT_REGULAR_FILE')
    return real


def joint1_valid(crane):
    joint=crane.find("joint[@name='crane_plus_joint1']")
    require(joint is not None, 'J1_JOINT_MISSING')
    require(joint.findtext('axis/xyz','').strip()=='0 0 1','J1_AXIS_NOT_WORLD_Z_ASSUMED')
    require(joint.findtext('parent')=='base_link' and joint.findtext('child')=='crane_plus_link1', 'J1_RELATIONS_CHANGED')
    require(crane.findtext('self_collide','false')=='false','SELF_COLLIDE_SETTING_CHANGED')
    root_pose=pose(crane)
    require(max(abs(root_pose[i]) for i in (0,1,3,4,5))<1e-8,'J1_BASE_FRAME_CHANGED')
    for plugin in crane.findall('plugin'):
        if plugin.findtext('joint_name','').startswith('crane_plus_joint'):
            require(abs(float(plugin.findtext('initial_position','nan')))<1e-10,'NONZERO_INITIAL_JOINT_TARGET')


def scene_load(world_file):
    require(world_file.is_file() and not world_file.is_symlink(),'V6_WORLD_MISSING_OR_SYMLINK')
    raw=world_file.read_bytes()
    require(digest(raw)==WORLD_SHA256, 'V6_WORLD_SHA_MISMATCH')
    root=ET.fromstring(raw)
    w=root.find('world')
    require(w is not None, 'WORLD_ELEMENT_MISSING')
    crane=w.find("model[@name='crane_plus']")
    cube=w.find("model[@name='wood_cube_5cm']")
    table=w.find("model[@name='Table']")
    require(crane is not None and cube is not None and table is not None,'SCENE_MODEL_MISSING')
    joint1_valid(crane)
    cube_col=cube.find('link/collision')
    require(cube_col is not None,'CUBE_COLLISION_MISSING')
    cube_box=box_obb(cube,cube.find('link'),cube_col)
    table_boxes=[]
    for link in table.findall('link'):
        for col in link.findall('collision'):
            table_boxes.append((col.attrib.get('name','unnamed'),table_obb(table,link,col)))
    require(len(table_boxes)==5,'TABLE_COLLISION_COUNT_UNEXPECTED')
    links={l.get('name'):l for l in crane.findall('link')}
    require(set(('base_link','crane_plus_link1','crane_plus_link2','crane_plus_link3','crane_plus_link4','crane_plus_link_hand')).issubset(links),'ROBOT_LINKS_MISSING')
    meshes=[]
    mesh_info=[]
    for name in ('base_link','crane_plus_link1','crane_plus_link2','crane_plus_link3','crane_plus_link4','crane_plus_link_hand'):
        link=links[name]
        colls=[c for c in link.findall('collision') if c.find('geometry/mesh') is not None]
        require(len(colls)==1,'MESH_COLLISION_COUNT_UNEXPECTED:'+name)
        col=colls[0]
        p=mesh_uri(col.find('geometry/mesh'))
        b=p.read_bytes()
        bounds=stl_bounds(b)
        meshes.append((name,link,col,bounds))
        mesh_info.append({'link':name,'stl':p.name,'sha256':digest(b),'bytes':len(b),'facets':bounds['triangles'],'format':bounds['format'],'local_aabb_m':{'min':bounds['minimum'],'max':bounds['maximum']}})
    pushers={}
    for label,link_name in PUSHER_LINK.items():
        link=links[link_name]
        col=link.find("collision[@name='pai_%s_pusher_ext_collision']"%label.lower())
        require(col is not None and col.find('geometry/box') is not None,'PUSHER_COLLISION_MISSING:'+label)
        pushers[label]=(link,col)
    return (crane,cube_box,table_boxes,meshes,pushers,mesh_info)


def sweeping_angles(end):
    n=round(abs(end)/STEP_RAD)
    require(abs(n*STEP_RAD-abs(end))<1e-9, 'BAD_END_NOT_IN_STEP_GRID')
    sign=1 if end>0 else -1
    return [sign*i*STEP_RAD for i in range(n+1)]


def angular_motion_margin(box, step=STEP_RAD):
    center,axis,half=box
    # Every vertex has horizontal radial distance <= |center_xy|+half diagonal.
    max_radius=math.hypot(center[0],center[1])+norm(half)
    return 2*max_radius*math.sin(step/4)+0.0001


def scan(scene):
    crane,cube_box,table_boxes,meshes,pushers,mesh_info=scene
    model_pose=pose(crane)
    result={}
    unexpected=[]
    for label,end in ENDS.items():
        angs=sweeping_angles(end)
        other='NG' if label=='OK' else 'OK'
        # Record per obstacle bounding interval. Each sample is inflated by a
        # conservative bound on maximum possible position change at half-step.
        min_records={}
        def record(key,gap,margin,angle):
            item=min_records.get(key)
            value=gap-margin
            if item is None or value<item['worst_conservative_clearance_m']:
                min_records[key]={'worst_conservative_clearance_m':value,
                    'raw_sat_axis_gap_m':gap,'angular_margin_m':margin,'at_j1_rad':round(angle,6)}
        for theta in angs:
            for name,link,col,bounds in meshes:
                # The fixed base_link is intentionally mounted on the table;
                # report separately, but NEVER let its static support contact
                # be misreported as a moving-arm obstruction.
                if name=='base_link':
                    continue
                arm_box=mesh_obb(model_pose,theta,link,col,bounds)
                margin=angular_motion_margin(arm_box)
                record('MESH:%s vs CUBE'%name,sat_gap(arm_box,cube_box),margin,theta)
                for tname,tbox in table_boxes:
                    record('MESH:%s vs TABLE:%s'%(name,tname),sat_gap(arm_box,tbox),margin,theta)
            for pname,(link,col) in pushers.items():
                pbox=push_obb(model_pose,theta,link,col)
                margin=angular_motion_margin(pbox)
                record('PUSHER:%s vs CUBE'%pname,sat_gap(pbox,cube_box),margin,theta)
                for tname,tbox in table_boxes:
                    record('PUSHER:%s vs TABLE:%s'%(pname,tname),sat_gap(pbox,tbox),margin,theta)
        # Expected contact with intended pusher is intentionally not a blocker
        # while collision is still >0 clearance; it must remain precontact.
        intended_key='PUSHER:%s vs CUBE'%label
        for key,entry in min_records.items():
            if entry['worst_conservative_clearance_m']<=0:
                unexpected.append({'direction':label,'pair':key,'at_rad':entry['at_j1_rad'],
                                   'swept_proxy_margin_mm':round(1000*entry['worst_conservative_clearance_m'],4),
                                   'is_intended_pusher':key==intended_key})
        result[label]={
            'end_command_target_rad':end,
            'sample_spacing_rad':STEP_RAD,
            'sample_count':len(angs),
            'swept_proxy_clearance_min_mm':{k:round(1000*v['worst_conservative_clearance_m'],4) for k,v in sorted(min_records.items())},
            'intended_pusher_cube_min_clearance_mm':round(1000*min_records[intended_key]['worst_conservative_clearance_m'],4),
            'other_pusher_cube_min_clearance_mm':round(1000*min_records['PUSHER:%s vs CUBE'%other]['worst_conservative_clearance_m'],4),
            'mesh_cube_min_clearance_mm':round(1000*min(v['worst_conservative_clearance_m'] for k,v in min_records.items() if k.startswith('MESH:') and ' vs CUBE' in k),4),
            'mesh_table_min_clearance_mm':round(1000*min(v['worst_conservative_clearance_m'] for k,v in min_records.items() if k.startswith('MESH:') and ' vs TABLE:' in k),4),
            'pusher_table_min_clearance_mm':round(1000*min(v['worst_conservative_clearance_m'] for k,v in min_records.items() if k.startswith('PUSHER:') and ' vs TABLE:' in k),4),
        }
    return result,unexpected


def internal_selftest():
    A=obb((0,0,0,0,0,0),size=(2,2,2))
    B=obb((3,0,0,0,0,0),size=(2,2,2))
    C=obb((1.5,0,0,0,0,0),size=(2,2,2))
    require(abs(sat_gap(A,B)-1)<1e-8,'SELFTEST_BOX_SEPARATION')
    require(sat_gap(A,C)<0,'SELFTEST_BOX_INTERSECTION')
    # Rotated box must be recognized by SAT, not only global AABBs.
    D=obb((3.0,0,0,0,0,math.pi/4),size=(2,2,2))
    require(sat_gap(A,D)>0,'SELFTEST_ROTATED_BOX_SEPARATION')
    stl=b'X'*80+struct.pack('<I',1)+struct.pack('<12fH',0,0,1,0,0,0,1,0,0,0,1,0,0)
    b=stl_bounds(stl)
    require(b['triangles']==1 and b['minimum']==(0.,0.,0.) and b['maximum']==(1.,1.,0.),'SELFTEST_BINARY_STL')
    text=b'solid s\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid s\n'
    b=stl_bounds(text)
    require(b['triangles']==1 and b['maximum']==(1.,1.,0.),'SELFTEST_ASCII_STL')
    require(len(sweeping_angles(.17))==35,'SELFTEST_ANGLE_COUNT')
    require(len(sweeping_angles(-.13))==27,'SELFTEST_NEGATIVE_ANGLE_COUNT')
    require(angular_motion_margin(A)>0,'SELFTEST_ARC_MARGIN')
    try:
        stl_bounds(b'garbage stl')
        raise RuntimeError('SELFTEST_CORRUPT_MESH_NOT_REJECTED')
    except Hold:
        pass
    print('V6_MESH_AUDIT_SELFTEST=PASS',flush=True)
    print('GAZEBO_COMMANDS=0',flush=True)
    print('MOTION_REQUESTED=False',flush=True)


def write_report(outdir,report):
    require(outdir.is_dir() and not outdir.is_symlink(),'OUTPUT_FOLDER_MISSING_OR_SYMLINK')
    filename=J1_PREFIX+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_%d.json'%time.time_ns()
    p=outdir/filename
    data=(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n').encode('utf-8')
    with p.open('xb') as fh:
        fh.write(data)
    require(digest(p.read_bytes())==digest(data),'EVIDENCE_WRITE_READBACK_FAILED')
    return p


def main():
    parser=argparse.ArgumentParser()
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--selftest',action='store_true')
    modes.add_argument('--audit',action='store_true')
    parser.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT)
    a=parser.parse_args()
    try:
        if a.selftest:
            internal_selftest()
            return 0
        report={'audit_type':'READONLY_V6_SDF_STL_SWEPT_PROXY_PREFLIGHT',
                'world_sha256_expected':WORLD_SHA256,'gazebo_queries':0,
                'joint_commands_sent':0,'robot_hardware_used':False,
                'cube_pose_writes':0,'robot_motion_authorized':False,
                'mesh_count_expected':6,
                'table_surface_and_legs_expected':5,
                'notes':['This is a conservative bounding-OBB sweep, not exact triangle-mesh collision, signed distance, or physics simulation.',
                         'All moving links are assumed to follow J1 rigid world-Z rotation; other joints are held at initial SDF pose.',
                         'SDF self_collide=false. Robot internal collisions are NOT audited. Fixed robot base/table mounting contact is excluded.',
                         'Four table cylinders are conservatively enclosed in OBBs; the Table model has a nonzero world pose.',
                         'A positive swept proxy gap rules out cube/table overlap under stated rigid-rotation assumptions.',
                         'A negative swept proxy gap indicates possible collision or an overconservative mesh bounding-box false positive.',
                         'The cube remains at initial location for the entire audit; contact and dynamic pushing are NOT authorized.']}
        scene=scene_load(WORLD)
        report['mesh_manifest']=scene[-1]
        scans,issues=scan(scene)
        report['sweeps']=scans
        report['possible_unintended_collision_pairs']=issues
        report['gate']='HOLD_OBSTACLE_OR_PROXY_UNCERTAINTY' if issues else 'PASS_CONSERVATIVE_PRECONTACT_PROXY_ONLY'
        out=write_report(a.output_dir,report)
        print('V6_MESHES_LOADED=%d'%len(report['mesh_manifest']),flush=True)
        for label in ('OK','NG'):
            s=scans[label]
            print('%s_END_J1_RAD=%.6f'%(label,s['end_command_target_rad']),flush=True)
            for field in ('intended_pusher_cube_min_clearance_mm','other_pusher_cube_min_clearance_mm',
                          'mesh_cube_min_clearance_mm','mesh_table_min_clearance_mm','pusher_table_min_clearance_mm'):
                print('%s_%s=%.4f'%(label,field.upper(),s[field]),flush=True)
        print('CONSERVATIVE_POTENTIAL_CONFLICTS=%d'%len(issues),flush=True)
        for row in issues[:15]:
            print('POTENTIAL_CONFLICT=%s @ %.5frad [%s]'%(row['pair'],row['at_rad'],row['direction']),flush=True)
        if len(issues)>15:
            print('POTENTIAL_CONFLICTS_TRUNCATED_IN_STDOUT_TRUE_REPORT_HAS_ALL=True',flush=True)
        print('V6_MESH_AUDIT_JSON='+str(out),flush=True)
        print('SIMULATION_COMMANDS_SENT=0',flush=True)
        print('ROBOT_MOTION_AUTHORIZED=False',flush=True)
        print('V6_MESH_AUDIT_GATE='+report['gate'],flush=True)
        return 0 if not issues else 3
    except Exception as exc:
        print('V6_MESH_AUDIT_GATE=HOLD',flush=True)
        print('V6_MESH_AUDIT_ERROR='+type(exc).__name__+':'+str(exc)[:600],flush=True)
        print('SIMULATION_COMMANDS_SENT=0',flush=True)
        return 3

if __name__=='__main__':
    sys.exit(main())
