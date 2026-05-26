import os
import tempfile
import numpy as np
import trimesh
from PIL import Image
from export.mesh_exporter import MeshExporter

def parse_obj(path):
    verts = []
    if not os.path.exists(path): return np.zeros((0,3))
    with open(path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                verts.append([float(x) for x in line.split()[1:4]])
    return np.array(verts)

def parse_glb(path):
    if not os.path.exists(path): return np.zeros((0,3))
    scene = trimesh.load(path)
    if isinstance(scene, trimesh.Scene):
        if not scene.geometry: return np.zeros((0,3))
        all_v = [m.vertices for m in scene.geometry.values()]
        return np.concatenate(all_v)
    return scene.vertices

def compare(name, obj_verts, glb_verts, expected_count=None):
    if len(obj_verts) == 0:
        return {"name": name, "obj_count": 0, "glb_count": 0, "passed": False}
    
    # Use unique vertices for comparison to handle differing indexing strategies
    obj_u = np.unique(np.round(obj_verts, 5), axis=0)
    glb_u = np.unique(np.round(glb_verts, 5), axis=0)
    
    obj_s = obj_u[np.lexsort(obj_u.T)]
    glb_s = glb_u[np.lexsort(glb_u.T)]
    
    consistent = len(obj_s) == len(glb_s) and np.allclose(obj_s, glb_s, atol=1e-5)
    return {
        "name": name,
        "obj_count": len(obj_verts),
        "glb_count": len(glb_verts),
        "passed": bool(consistent)
    }

try:
    tmp = tempfile.mkdtemp()
    exp = MeshExporter()
    results = []

    # 1. Cuboid
    obj_p = os.path.join(tmp, 'c.obj'); glb_p = os.path.join(tmp, 'c.glb')
    faces = {k: np.zeros((10,10,3),dtype=np.uint8) for k in ['top','bottom','left','right','front','back']}
    dims = {'width': 100, 'height': 50, 'depth': 20}
    exp.export_obj(faces, dims, obj_p); exp.export_gltf(faces, dims, glb_p)
    results.append(compare("Cuboid", parse_obj(obj_p), parse_glb(glb_p)))

    # 2. Cylinder
    obj_p = os.path.join(tmp, 'cy.obj'); glb_p = os.path.join(tmp, 'cy.glb')
    c_faces = {k: np.zeros((10,10,3),dtype=np.uint8) for k in ["surface", "cap_front", "cap_back"]}
    c_dims = {"radius": 50, "depth": 100, "circumference": 314}
    exp.export_cylinder_obj(c_faces, c_dims, obj_p); exp.export_cylinder_gltf(c_faces, c_dims, glb_p)
    results.append(compare("Cylinder", parse_obj(obj_p), parse_glb(glb_p)))

    # 3. Cuboid Fill
    frames_dir = os.path.join(tmp, 'frames'); os.makedirs(frames_dir, exist_ok=True)
    for i in range(2): Image.fromarray(np.zeros((4,4,3),dtype=np.uint8)).save(os.path.join(frames_dir, f'frame_{i:06d}.png'))
    obj_p = os.path.join(tmp, 'cf.obj'); glb_p = os.path.join(tmp, 'cf.glb')
    dims_cf = {'width': 4, 'height': 4, 'depth': 2}
    exp.export_cuboid_fill_obj(frames_dir, dims_cf, obj_p); exp.export_cuboid_fill_gltf(frames_dir, dims_cf, glb_p)
    results.append(compare("Cuboid Fill", parse_obj(obj_p), parse_glb(glb_p)))

    # 4. Slittear
    full = np.zeros((2, 8, 3), dtype=np.uint8)
    rast = [[(x, 0) for x in range(8)], [(x, 1) for x in range(8)]]
    obj_p = os.path.join(tmp, 's.obj'); glb_p = os.path.join(tmp, 's.glb')
    exp.export_slittear_obj(full, rast, [8, 8], 2, 8, 4, obj_p)
    exp.export_slittear_gltf(full, rast, [8, 8], 2, 8, 4, glb_p)
    results.append(compare("Slittear", parse_obj(obj_p), parse_glb(glb_p)))

    # 5. Orthogonal
    v = np.zeros((4, 2, 3), dtype=np.uint8); h = np.zeros((2, 8, 3), dtype=np.uint8)
    df = {0: np.zeros((4, 8, 3), dtype=np.uint8)}
    obj_p = os.path.join(tmp, 'o.obj'); glb_p = os.path.join(tmp, 'o.glb')
    exp.export_orthogonal_obj(v, h, 1, 1, 8, 4, 3, obj_p, display_frames=df)
    exp.export_orthogonal_gltf(v, h, 1, 1, 8, 4, 3, glb_p, display_frames=df)
    results.append(compare("Orthogonal", parse_obj(obj_p), parse_glb(glb_p)))

    print(f"{'Mode':<15} | {'OBJ_V':<5} | {'GLB_V':<5} | {'Status'}")
    print("-" * 40)
    failed = False
    for r in results:
        status = "PASS" if r['passed'] else "FAIL"
        if not r['passed']: failed = True
        print(f"{r['name']:<15} | {r['obj_count']:<5} | {r['glb_count']:<5} | {status}")
    if failed: exit(1)
except Exception:
    import traceback; traceback.print_exc(); exit(1)
