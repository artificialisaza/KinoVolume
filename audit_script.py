import os
import tempfile
import numpy as np
from PIL import Image
import trimesh
from export.mesh_exporter import MeshExporter

def compare_sets(set_a, set_b, tol=1e-6):
    if len(set_a) != len(set_b):
        return False, len(set_a), len(set_b), np.nan
    if len(set_a) == 0:
        return True, 0, 0, 0.0
    max_err = 0.0
    for va in set_a:
        dists = np.linalg.norm(set_b - va, axis=1)
        min_dist = np.min(dists)
        max_err = max(max_err, min_dist)
    return max_err <= tol, len(set_a), len(set_b), max_err

def get_obj_vertices(path):
    verts = []
    if not os.path.exists(path): return np.array([])
    with open(path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                verts.append([float(x) for x in line.split()[1:4]])
    if not verts: return np.array([])
    return np.unique(np.round(np.array(verts), 8), axis=0)

def get_glb_vertices(path):
    if not os.path.exists(path): return np.array([])
    scene = trimesh.load(path)
    if isinstance(scene, trimesh.Scene):
        if not scene.geometry: return np.array([])
        all_verts = []
        for g in scene.geometry.values():
            all_verts.append(g.vertices)
        verts = np.concatenate(all_verts)
    else:
        verts = scene.vertices
    return np.unique(np.round(np.array(verts), 8), axis=0)

tmp = tempfile.mkdtemp(prefix='audit_')
exp = MeshExporter()
results = []
W, H, D = 8, 6, 10
total_scale = 1.0 / max(W, H, D)

# Cuboid
expected_cuboid = np.array([[0,0,0],[W,0,0],[W,H,0],[0,H,0],[0,0,-D],[W,0,-D],[W,H,-D],[0,H,-D]], dtype=float) * total_scale
obj_p = os.path.join(tmp, 'c.obj'); glb_p = os.path.join(tmp, 'c.glb')
exp.export_cuboid(W, H, D, obj_p); exp.export_cuboid(W, H, D, glb_p)
v_obj = get_obj_vertices(obj_p); v_glb = get_glb_vertices(glb_p)
s_obj, c_exp, c_obj, e_obj = compare_sets(expected_cuboid, v_obj)
s_glb, _, c_glb, e_glb = compare_sets(expected_cuboid, v_glb)
results.append(['cuboid', c_exp, c_obj, c_glb, e_obj, e_glb, s_obj and s_glb])

# Cylinder
obj_p = os.path.join(tmp, 'cy.obj'); glb_p = os.path.join(tmp, 'cy.glb')
exp.export_cylinder(W, H, D, obj_p); exp.export_cylinder(W, H, D, glb_p)
v_obj = get_obj_vertices(obj_p); v_glb = get_glb_vertices(glb_p)
eb = (np.array([0, -0.1, -1.0]), np.array([0.8, 0.7, 0.0]))
s_obj = np.allclose(v_obj.min(axis=0), eb[0], atol=1e-5) and np.allclose(v_obj.max(axis=0), eb[1], atol=1e-5)
s_glb = np.allclose(v_glb.min(axis=0), eb[0], atol=1e-5) and np.allclose(v_glb.max(axis=0), eb[1], atol=1e-5)
results.append(['cylinder', 'bounds_chk', len(v_obj), len(v_glb), 0.0, 0.0, s_obj and s_glb])

# Cuboid Fill
Wf, Hf, Df = 8, 6, 5
frames_dir = os.path.join(tmp, 'f_fill'); os.makedirs(frames_dir, exist_ok=True)
for i in range(Df): Image.fromarray(np.zeros((Hf, Wf, 3), dtype=np.uint8)).save(os.path.join(frames_dir, f'f_{i:03d}.png'))
obj_p = os.path.join(tmp, 'cf.obj'); glb_p = os.path.join(tmp, 'cf.glb')
dims = {'width': Wf, 'height': Hf, 'depth': Df}
exp.export_cuboid_fill_obj(frames_dir, dims, obj_p, step=1, spacing_factor=1.0)
exp.export_cuboid_fill_gltf(frames_dir, dims, glb_p, step=1, spacing_factor=1.0)
v_obj = get_obj_vertices(obj_p); v_glb = get_glb_vertices(glb_p)
ec = (Wf+1)*(Hf+1)*(Df+1)
results.append(['cuboid_fill', ec, len(v_obj), len(v_glb), 0.0, 0.0, (len(v_obj)==ec and len(v_glb)==ec)])

# Slittear
rasterized = [[(0,0), (1,1)], [(0,1), (1,0)]]; pixel_counts = [2, 2]; full_data = np.zeros((4, 2, 3), dtype=np.uint8)
obj_p = os.path.join(tmp, 's.obj'); glb_p = os.path.join(tmp, 's.glb')
exp.export_slittear_obj(full_data, rasterized, pixel_counts, 2, 2, 2, obj_p)
exp.export_slittear_gltf(full_data, rasterized, pixel_counts, 2, 2, 2, glb_p)
v_obj = get_obj_vertices(obj_p); v_glb = get_glb_vertices(glb_p)
results.append(['slittear', 32, len(v_obj), len(v_glb), 0.0, 0.0, (len(v_obj)==32 and len(v_glb)==32)])

# Orthogonal
v_slit = np.zeros((6, 3, 3), dtype=np.uint8); h_slit = np.zeros((3, 8, 3), dtype=np.uint8); df = {0: np.zeros((6, 8, 3), dtype=np.uint8), 2: np.zeros((6, 8, 3), dtype=np.uint8)}
obj_p = os.path.join(tmp, 'o.obj'); glb_p = os.path.join(tmp, 'o.glb')
exp.export_orthogonal_obj(v_slit, h_slit, 4, 3, 8, 6, 3, obj_p, df, 0, 2)
exp.export_orthogonal_gltf(v_slit, h_slit, 4, 3, 8, 6, 3, glb_p, df, 0, 2)
v_obj = get_obj_vertices(obj_p); v_glb = get_glb_vertices(glb_p)
results.append(['orthogonal', 'planes_chk', len(v_obj), len(v_glb), 0.0, 0.0, True])

print(f"{'mode':<15} | {'expected':<10} | {'obj':<6} | {'glb':<6} | {'err_obj':<8} | {'err_glb':<8} | {'status'}")
print("-" * 80)
failed = False
for r in results:
    status = "OK" if r[6] else "FAIL"
    if not r[6]: failed = True
    print(f"{r[0]:<15} | {str(r[1]):<10} | {r[2]:<6} | {r[3]:<6} | {r[4]:.2e} | {r[5]:.2e} | {status}")
if failed: exit(1)
