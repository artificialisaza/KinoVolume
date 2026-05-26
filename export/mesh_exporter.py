"""Exports cuboid face textures as OBJ+MTL or glTF/GLB 3D models."""

import os

import numpy as np
from PIL import Image


class MeshExporter:
    """Writes 3D cuboid meshes with per-face textures."""

    def export_obj(self, face_images, dimensions, output_path):
        """Write OBJ + MTL referencing face PNGs already saved by the processor.

        face_images: dict  name→(H,W,3) uint8 numpy array
        dimensions:  dict  {"width": W, "height": H, "depth": D}
        output_path: path to .obj file
        """
        out_dir = os.path.dirname(output_path)
        obj_name = os.path.splitext(os.path.basename(output_path))[0]
        mtl_name = f"{obj_name}.mtl"

        # Normalize scale so the longest axis = 1.0 (avoids Blender far-clip issues)
        raw_w = float(dimensions["width"])
        raw_h = float(dimensions["height"])
        raw_d = float(dimensions["depth"])
        max_dim = max(raw_w, raw_h, raw_d)
        scale = 1.0 / max_dim if max_dim > 0 else 1.0
        W = raw_w * scale
        H = raw_h * scale
        D = raw_d * scale

        face_names = ["front", "back", "top", "bottom", "left", "right"]

        # Write MTL — reference root-level PNGs (already saved by processor)
        mtl_path = os.path.join(out_dir, mtl_name)
        with open(mtl_path, "w") as f:
            for name in face_names:
                f.write(f"newmtl mat_{name}\n")
                f.write("Ka 1.0 1.0 1.0\n")
                f.write("Kd 1.0 1.0 1.0\n")
                f.write(f"map_Kd {name}.png\n\n")

        # Write OBJ
        with open(output_path, "w") as f:
            f.write(f"mtllib {mtl_name}\n\n")

            # 8 vertices (Y-up coordinate system, normalized scale)
            f.write(f"v 0 0 0\n")       # 1
            f.write(f"v {W} 0 0\n")     # 2
            f.write(f"v {W} {H} 0\n")   # 3
            f.write(f"v 0 {H} 0\n")     # 4
            f.write(f"v 0 0 {D}\n")     # 5
            f.write(f"v {W} 0 {D}\n")   # 6
            f.write(f"v {W} {H} {D}\n") # 7
            f.write(f"v 0 {H} {D}\n")   # 8
            f.write("\n")

            # UV coords (full texture per face)
            f.write("vt 0 0\n")  # 1
            f.write("vt 1 0\n")  # 2
            f.write("vt 1 1\n")  # 3
            f.write("vt 0 1\n")  # 4
            f.write("\n")

            # Faces (counter-clockwise from outside)
            f.write("usemtl mat_front\n")
            f.write("f 1/1 2/2 3/3 4/4\n\n")

            f.write("usemtl mat_back\n")
            f.write("f 6/1 5/2 8/3 7/4\n\n")

            # Top: rotate UVs 180° to fix Blender orientation
            f.write("usemtl mat_top\n")
            f.write("f 4/3 3/4 7/1 8/2\n\n")

            f.write("usemtl mat_bottom\n")
            f.write("f 5/1 6/2 2/3 1/4\n\n")

            # Left: after side texture transpose, UV axes swapped
            f.write("usemtl mat_left\n")
            f.write("f 5/2 1/1 4/4 8/3\n\n")

            f.write("usemtl mat_right\n")
            f.write("f 2/1 6/2 7/3 3/4\n")

    def export_gltf(self, face_images, dimensions, output_path):
        """Write a glTF/GLB file with embedded textures using trimesh.

        output_path: path to .glb file
        """
        import trimesh

        # Normalize scale so the longest axis = 1.0
        raw_w = float(dimensions["width"])
        raw_h = float(dimensions["height"])
        raw_d = float(dimensions["depth"])
        max_dim = max(raw_w, raw_h, raw_d)
        scale = 1.0 / max_dim if max_dim > 0 else 1.0
        W = raw_w * scale
        H = raw_h * scale
        D = raw_d * scale

        face_defs = {
            "front":  {"verts": [[0,0,0],[W,0,0],[W,H,0],[0,H,0]], "normal": [0,0,-1]},
            "back":   {"verts": [[W,0,D],[0,0,D],[0,H,D],[W,H,D]], "normal": [0,0,1]},
            "top":    {"verts": [[0,H,0],[W,H,0],[W,H,D],[0,H,D]], "normal": [0,1,0]},
            "bottom": {"verts": [[0,0,D],[W,0,D],[W,0,0],[0,0,0]], "normal": [0,-1,0]},
            "left":   {"verts": [[0,0,D],[0,0,0],[0,H,0],[0,H,D]], "normal": [-1,0,0]},
            "right":  {"verts": [[W,0,0],[W,0,D],[W,H,D],[W,H,0]], "normal": [1,0,0]},
        }

        # Standard UVs for most faces; left face gets swapped UVs after texture transpose.
        # Top face gets 180° rotated UVs to fix Blender orientation.
        standard_uvs = np.array([[0,0],[1,0],[1,1],[0,1]], dtype=np.float64)
        left_uvs = np.array([[1,0],[0,0],[0,1],[1,1]], dtype=np.float64)
        top_uvs = np.array([[1,1],[0,1],[0,0],[1,0]], dtype=np.float64)
        tri_faces = np.array([[0,1,2],[0,2,3]], dtype=np.int64)

        meshes = []
        for name, fdef in face_defs.items():
            verts = np.array(fdef["verts"], dtype=np.float64)
            img_data = face_images[name].astype(np.uint8)
            pil_img = Image.fromarray(img_data)

            material = trimesh.visual.material.PBRMaterial(
                baseColorTexture=pil_img,
                metallicFactor=0.0,
                roughnessFactor=1.0,
            )
            if name == "left":
                uvs = left_uvs
            elif name == "top":
                uvs = top_uvs
            else:
                uvs = standard_uvs
            visual = trimesh.visual.TextureVisuals(
                uv=uvs, material=material
            )
            mesh = trimesh.Trimesh(
                vertices=verts,
                faces=tri_faces,
                visual=visual,
                process=False,
            )
            meshes.append(mesh)

        scene = trimesh.Scene(meshes)
        scene.export(output_path, file_type="glb")

    # ------------------------------------------------------------------
    # Slit-scan Planar cut export (textured diagonal plane)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_planar_plane(texture_image, scan_direction, mask_type,
                            frame_width, frame_height, depth,
                            mask_left=0, mask_right=0,
                            mask_top=0, mask_bottom=0):
        """Build the diagonal plane geometry exactly matching Preview3D.

        Returns (verts, uvs, faces) as numpy arrays (float64 for verts).
        """
        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)

        my1 = float(mask_top)
        my2 = float(frame_height - mask_bottom)
        mx1 = float(mask_left)
        mx2 = float(frame_width - mask_right)

        # Scale depth proportionally so the plane has visible Z extent
        # (same approach as cuboid fill: ~40% of longest spatial axis)
        max_spatial = max(W, H, 1.0)
        D = max_spatial * 0.4 * D / max(D, 1)

        # Normalize scale
        max_dim = max(W, H, D)
        sc = 1.0 / max_dim if max_dim > 0 else 1.0
        Ws, Hs, Ds = W * sc, H * sc, D * sc

        if mask_type == "Vertical":
            if scan_direction in ("L→R", ""):
                start_x, end_x = mx1, mx2
            else:
                start_x, end_x = mx2, mx1

            # Mirror X to match Preview3D camera correction for YZ planes
            p0 = [(W - start_x) * sc, (H - my1) * sc, 0.0]
            p1 = [(W - end_x) * sc,   (H - my1) * sc, Ds]
            p2 = [(W - end_x) * sc,   (H - my2) * sc, Ds]
            p3 = [(W - start_x) * sc, (H - my2) * sc, 0.0]
        else:
            if scan_direction in ("T→B", ""):
                start_y, end_y = my1, my2
            else:
                start_y, end_y = my2, my1

            p0 = [mx1 * sc, (H - start_y) * sc, 0.0]
            p1 = [mx2 * sc, (H - start_y) * sc, 0.0]
            p2 = [mx2 * sc, (H - end_y)   * sc, Ds]
            p3 = [mx1 * sc, (H - end_y)   * sc, Ds]

        # Subdivide quad into grid mesh
        n_sub = 32
        verts = []
        uvs = []
        for vi in range(n_sub + 1):
            for ui in range(n_sub + 1):
                u = ui / n_sub
                v = vi / n_sub
                pt = [(1 - u) * (1 - v) * p0[0] + u * (1 - v) * p1[0]
                      + u * v * p2[0] + (1 - u) * v * p3[0],
                      (1 - u) * (1 - v) * p0[1] + u * (1 - v) * p1[1]
                      + u * v * p2[1] + (1 - u) * v * p3[1],
                      (1 - u) * (1 - v) * p0[2] + u * (1 - v) * p1[2]
                      + u * v * p2[2] + (1 - u) * v * p3[2]]
                verts.append(pt)
                uvs.append([u, 1.0 - v])

        verts = np.array(verts, dtype=np.float64)
        uvs = np.array(uvs, dtype=np.float64)

        faces = []
        for vi in range(n_sub):
            for ui in range(n_sub):
                i0 = vi * (n_sub + 1) + ui
                i1 = i0 + 1
                i2 = i0 + (n_sub + 1) + 1
                i3 = i0 + (n_sub + 1)
                faces.append([i0, i1, i2])
                faces.append([i0, i2, i3])
        faces = np.array(faces, dtype=np.int64)

        return verts, uvs, faces

    def export_slitscan_planar_obj(self, texture_image, scan_direction,
                                   mask_type, frame_width, frame_height,
                                   depth, output_path,
                                   mask_left=0, mask_right=0,
                                   mask_top=0, mask_bottom=0):
        """Write slitscan planar cut plane as OBJ + MTL."""
        out_dir = os.path.dirname(output_path)
        obj_name = os.path.splitext(os.path.basename(output_path))[0]
        mtl_name = f"{obj_name}.mtl"

        tex_name = f"{obj_name}.png"
        Image.fromarray(texture_image.astype(np.uint8)).save(
            os.path.join(out_dir, tex_name))

        verts, uvs, faces = self._build_planar_plane(
            texture_image, scan_direction, mask_type,
            frame_width, frame_height, depth,
            mask_left, mask_right, mask_top, mask_bottom,
        )

        # Write MTL
        with open(os.path.join(out_dir, mtl_name), "w") as f:
            f.write("newmtl mat_plane\n")
            f.write("Ka 1.0 1.0 1.0\nKd 1.0 1.0 1.0\n")
            f.write(f"map_Kd {tex_name}\n")

        # Write OBJ
        with open(output_path, "w") as f:
            f.write(f"mtllib {mtl_name}\n\n")
            for v in verts:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            f.write("\n")
            for uv in uvs:
                f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
            f.write("\n")
            f.write("usemtl mat_plane\n")
            for tri in faces:
                a, b, c = tri[0] + 1, tri[1] + 1, tri[2] + 1
                f.write(f"f {a}/{a} {b}/{b} {c}/{c}\n")

    def export_slitscan_planar_gltf(self, texture_image, scan_direction,
                                    mask_type, frame_width, frame_height,
                                    depth, output_path,
                                    mask_left=0, mask_right=0,
                                    mask_top=0, mask_bottom=0):
        """Write slitscan planar cut plane as glTF/GLB."""
        import trimesh

        verts, uvs, faces = self._build_planar_plane(
            texture_image, scan_direction, mask_type,
            frame_width, frame_height, depth,
            mask_left, mask_right, mask_top, mask_bottom,
        )

        pil_img = Image.fromarray(texture_image.astype(np.uint8))
        mat = trimesh.visual.material.PBRMaterial(
            baseColorTexture=pil_img,
            metallicFactor=0.0,
            roughnessFactor=1.0,
        )
        vis = trimesh.visual.TextureVisuals(uv=uvs, material=mat)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces,
                               visual=vis, process=False)

        scene = trimesh.Scene([mesh])
        scene.export(output_path, file_type="glb")

    # ------------------------------------------------------------------
    # Cylinder export
    # ------------------------------------------------------------------

    def export_cylinder_obj(self, face_images, dimensions, output_path):
        """Write cylinder OBJ + MTL with surface and cap textures.

        face_images: dict with "surface", "cap_front", "cap_back" → (H,W,3) arrays
        dimensions:  dict with "radius", "depth", "circumference"
        """
        out_dir = os.path.dirname(output_path)
        obj_name = os.path.splitext(os.path.basename(output_path))[0]
        mtl_name = f"{obj_name}.mtl"

        radius = float(dimensions["radius"])
        depth = float(dimensions["depth"])
        circumference = int(dimensions["circumference"])

        # Normalize scale
        max_dim = max(radius * 2, depth)
        scale = 1.0 / max_dim if max_dim > 0 else 1.0
        R = radius * scale
        D = depth * scale
        diameter = R * 2

        n_seg = min(circumference, 128)  # cap segments for reasonable OBJ size
        thetas = np.linspace(0, 2 * np.pi, n_seg, endpoint=False)

        # Save texture images
        fmt = "png"
        for name, img in face_images.items():
            img_path = os.path.join(out_dir, f"{name}.{fmt}")
            Image.fromarray(img.astype(np.uint8)).save(img_path)

        # Write MTL
        mtl_path = os.path.join(out_dir, mtl_name)
        with open(mtl_path, "w") as f:
            for name in ["surface", "cap_front", "cap_back"]:
                f.write(f"newmtl mat_{name}\n")
                f.write("Ka 1.0 1.0 1.0\nKd 1.0 1.0 1.0\n")
                f.write(f"map_Kd {name}.{fmt}\n\n")

        # Write OBJ
        with open(output_path, "w") as f:
            f.write(f"mtllib {mtl_name}\n\n")

            # --- Surface vertices ---
            # Two rings: front (z=0) and back (z=D), n_seg+1 verts each (seam duplicate)
            for i in range(n_seg + 1):
                theta = thetas[i % n_seg]
                x = R + R * np.cos(theta)
                y = R + R * np.sin(theta)
                f.write(f"v {x:.6f} {y:.6f} 0\n")
            for i in range(n_seg + 1):
                theta = thetas[i % n_seg]
                x = R + R * np.cos(theta)
                y = R + R * np.sin(theta)
                f.write(f"v {x:.6f} {y:.6f} {D:.6f}\n")
            # surface verts: 1..(n_seg+1) front, (n_seg+2)..(2*(n_seg+1)) back

            # --- Cap center vertices ---
            cap_front_center_idx = 2 * (n_seg + 1) + 1  # 1-based
            f.write(f"v {R:.6f} {R:.6f} 0\n")
            cap_back_center_idx = cap_front_center_idx + 1
            f.write(f"v {R:.6f} {R:.6f} {D:.6f}\n")
            f.write("\n")

            # --- Surface UVs ---
            for i in range(n_seg + 1):
                # Match Preview3D: rotate tube texture 180° around cylinder
                u = ((i / n_seg) + 0.5) % 1.0
                f.write(f"vt {u:.6f} 1\n")  # front ring
            for i in range(n_seg + 1):
                u = ((i / n_seg) + 0.5) % 1.0
                f.write(f"vt {u:.6f} 0\n")  # back ring
            # surface UVs: 1..(n_seg+1) front, (n_seg+2)..(2*(n_seg+1)) back

            # --- Cap UVs (map perimeter + center) ---
            cap_uv_start = 2 * (n_seg + 1) + 1
            for i in range(n_seg):
                theta = thetas[i]
                # Match Preview3D cap horizontal mirror (np.fliplr)
                cu = 0.5 - 0.5 * np.cos(theta)
                cv = 0.5 + 0.5 * np.sin(theta)
                f.write(f"vt {cu:.6f} {cv:.6f}\n")
            cap_center_uv = cap_uv_start + n_seg
            f.write("vt 0.5 0.5\n")  # center UV
            f.write("\n")

            # --- Surface faces ---
            f.write("usemtl mat_surface\n")
            for i in range(n_seg):
                v_f0 = i + 1
                v_f1 = i + 2
                v_b0 = (n_seg + 1) + i + 1
                v_b1 = (n_seg + 1) + i + 2
                t_f0 = i + 1
                t_f1 = i + 2
                t_b0 = (n_seg + 1) + i + 1
                t_b1 = (n_seg + 1) + i + 2
                f.write(f"f {v_f0}/{t_f0} {v_f1}/{t_f1} {v_b1}/{t_b1} {v_b0}/{t_b0}\n")
            f.write("\n")

            # --- Front cap faces (z=0) ---
            f.write("usemtl mat_cap_front\n")
            for i in range(n_seg):
                v0 = i + 1  # perimeter vertex
                v1 = (i + 1) % n_seg + 1
                t0 = cap_uv_start + i
                t1 = cap_uv_start + (i + 1) % n_seg
                f.write(f"f {cap_front_center_idx}/{cap_center_uv} {v1}/{t1} {v0}/{t0}\n")
            f.write("\n")

            # --- Back cap faces (z=D) ---
            f.write("usemtl mat_cap_back\n")
            for i in range(n_seg):
                v0 = (n_seg + 1) + i + 1
                v1 = (n_seg + 1) + (i + 1) % n_seg + 1
                t0 = cap_uv_start + i
                t1 = cap_uv_start + (i + 1) % n_seg
                f.write(f"f {cap_back_center_idx}/{cap_center_uv} {v0}/{t0} {v1}/{t1}\n")

    def export_cylinder_gltf(self, face_images, dimensions, output_path):
        """Write cylinder glTF/GLB with embedded surface + cap textures."""
        import trimesh

        radius = float(dimensions["radius"])
        depth = float(dimensions["depth"])
        circumference = int(dimensions["circumference"])

        max_dim = max(radius * 2, depth)
        scale = 1.0 / max_dim if max_dim > 0 else 1.0
        R = radius * scale
        D = depth * scale

        n_seg = min(circumference, 128)
        thetas = np.linspace(0, 2 * np.pi, n_seg, endpoint=False)

        meshes = []

        # --- Surface mesh ---
        n_ring = n_seg + 1  # duplicate first vertex for UV seam
        verts = np.zeros((n_ring * 2, 3), dtype=np.float64)
        uvs = np.zeros((n_ring * 2, 2), dtype=np.float64)
        for i in range(n_ring):
            theta = thetas[i % n_seg]
            x = R + R * np.cos(theta)
            y = R + R * np.sin(theta)
            # Match Preview3D: rotate tube texture 180° around cylinder
            u = ((i / n_seg) + 0.5) % 1.0
            verts[i] = [x, y, 0]
            uvs[i] = [u, 1.0]
            verts[n_ring + i] = [x, y, D]
            uvs[n_ring + i] = [u, 0.0]

        tri_faces = []
        for i in range(n_seg):
            v0, v1 = i, i + 1
            v2, v3 = n_ring + i, n_ring + i + 1
            tri_faces.append([v0, v1, v3])
            tri_faces.append([v0, v3, v2])
        tri_faces = np.array(tri_faces, dtype=np.int64)

        surface_pil = Image.fromarray(face_images["surface"].astype(np.uint8))
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=surface_pil, metallicFactor=0.0, roughnessFactor=1.0)
        visual = trimesh.visual.TextureVisuals(uv=uvs, material=material)
        mesh = trimesh.Trimesh(vertices=verts, faces=tri_faces, visual=visual, process=False)
        meshes.append(mesh)

        # --- Cap meshes ---
        for cap_name, z_pos in [("cap_front", 0.0), ("cap_back", D)]:
            cap_verts = np.zeros((n_seg + 1, 3), dtype=np.float64)
            cap_uvs = np.zeros((n_seg + 1, 2), dtype=np.float64)
            # Center vertex
            cap_verts[0] = [R, R, z_pos]
            cap_uvs[0] = [0.5, 0.5]
            for i in range(n_seg):
                theta = thetas[i]
                cap_verts[i + 1] = [R + R * np.cos(theta), R + R * np.sin(theta), z_pos]
                # Match Preview3D cap horizontal mirror (np.fliplr)
                cap_uvs[i + 1] = [0.5 - 0.5 * np.cos(theta), 0.5 + 0.5 * np.sin(theta)]

            cap_faces = []
            for i in range(n_seg):
                next_i = (i + 1) % n_seg
                if cap_name == "cap_front":
                    cap_faces.append([0, next_i + 1, i + 1])
                else:
                    cap_faces.append([0, i + 1, next_i + 1])
            cap_faces = np.array(cap_faces, dtype=np.int64)

            cap_pil = Image.fromarray(face_images[cap_name].astype(np.uint8))
            cap_mat = trimesh.visual.material.PBRMaterial(
                baseColorTexture=cap_pil, metallicFactor=0.0, roughnessFactor=1.0)
            cap_vis = trimesh.visual.TextureVisuals(uv=cap_uvs, material=cap_mat)
            cap_mesh = trimesh.Trimesh(vertices=cap_verts, faces=cap_faces,
                                        visual=cap_vis, process=False)
            meshes.append(cap_mesh)

        scene = trimesh.Scene(meshes)
        scene.export(output_path, file_type="glb")

    # ------------------------------------------------------------------
    # Orthogonal export (two crossing planes)
    # ------------------------------------------------------------------

    def export_orthogonal_obj(self, v_image, h_image, slit_pos, ortho_pos,
                              frame_width, frame_height, depth, output_path,
                              display_frames=None, initial_frame=0,
                              last_frame=None):
        """Write crossing planes (and optional display-frame planes) as OBJ + MTL."""
        out_dir = os.path.dirname(output_path)
        obj_name = os.path.splitext(os.path.basename(output_path))[0]
        mtl_name = f"{obj_name}.mtl"

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)

        max_dim = max(W, H, D)
        sc = 1.0 / max_dim if max_dim > 0 else 1.0

        if last_frame is None:
            last_frame = initial_frame + int(depth) - 1
        frame_span = max(1, int(last_frame) - int(initial_frame))

        # Save textures used by materials
        Image.fromarray(v_image.astype(np.uint8)).save(os.path.join(out_dir, "vertical.png"))
        Image.fromarray(h_image.astype(np.uint8)).save(os.path.join(out_dir, "horizontal.png"))

        display_items = []
        if isinstance(display_frames, dict):
            def _sort_key(item):
                k, _ = item
                try:
                    return int(k)
                except Exception:
                    return 0

            for frame_idx, img in sorted(display_frames.items(), key=_sort_key):
                idx = int(frame_idx)
                tex_name = f"display_frame_{idx:06d}.png"
                # Match Preview3D: display frames are mirrored on X
                Image.fromarray(np.fliplr(img).astype(np.uint8)).save(
                    os.path.join(out_dir, tex_name)
                )
                display_items.append((idx, tex_name))

        # Write MTL
        with open(os.path.join(out_dir, mtl_name), "w") as f:
            f.write("newmtl mat_vertical\n")
            f.write("Ka 1.0 1.0 1.0\nKd 1.0 1.0 1.0\n")
            f.write("map_Kd vertical.png\n\n")

            f.write("newmtl mat_horizontal\n")
            f.write("Ka 1.0 1.0 1.0\nKd 1.0 1.0 1.0\n")
            f.write("map_Kd horizontal.png\n\n")

            for idx, tex_name in display_items:
                f.write(f"newmtl mat_display_{idx:06d}\n")
                f.write("Ka 1.0 1.0 1.0\nKd 1.0 1.0 1.0\n")
                f.write(f"map_Kd {tex_name}\n\n")

        vx = float(slit_pos) * sc
        hy = (H - float(ortho_pos)) * sc
        Ws, Hs, Ds = W * sc, H * sc, D * sc

        quads = [
            {
                "material": "mat_vertical",
                "verts": [
                    [vx, 0.0, 0.0], [vx, 0.0, Ds], [vx, Hs, Ds], [vx, Hs, 0.0],
                ],
                "uvs": [
                    [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0],
                ],
            },
            {
                "material": "mat_horizontal",
                "verts": [
                    [0.0, hy, 0.0], [Ws, hy, 0.0], [Ws, hy, Ds], [0.0, hy, Ds],
                ],
                "uvs": [
                    [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0],
                ],
            },
        ]

        for idx, _tex_name in display_items:
            z = Ds * (idx - int(initial_frame)) / frame_span
            quads.append(
                {
                    "material": f"mat_display_{idx:06d}",
                    "verts": [
                        [0.0, 0.0, z], [Ws, 0.0, z], [Ws, Hs, z], [0.0, Hs, z],
                    ],
                    "uvs": [
                        [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0],
                    ],
                }
            )

        with open(output_path, "w") as f:
            f.write(f"mtllib {mtl_name}\n\n")

            for quad in quads:
                for vx_, vy_, vz_ in quad["verts"]:
                    f.write(f"v {vx_:.6f} {vy_:.6f} {vz_:.6f}\n")

            f.write("\n")
            for quad in quads:
                for u, v in quad["uvs"]:
                    f.write(f"vt {u:.6f} {v:.6f}\n")

            f.write("\n")
            for i, quad in enumerate(quads):
                v0 = i * 4 + 1
                t0 = i * 4 + 1
                f.write(f"usemtl {quad['material']}\n")
                f.write(
                    f"f {v0}/{t0} {v0+1}/{t0+1} {v0+2}/{t0+2} {v0+3}/{t0+3}\n\n"
                )

    def export_orthogonal_gltf(self, v_image, h_image, slit_pos, ortho_pos,
                               frame_width, frame_height, depth, output_path,
                               display_frames=None, initial_frame=0,
                               last_frame=None):
        """Write crossing planes (and optional display-frame planes) as glTF/GLB."""
        import trimesh

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)

        max_dim = max(W, H, D)
        sc = 1.0 / max_dim if max_dim > 0 else 1.0

        if last_frame is None:
            last_frame = initial_frame + int(depth) - 1
        frame_span = max(1, int(last_frame) - int(initial_frame))

        vx = float(slit_pos) * sc
        hy = (H - float(ortho_pos)) * sc
        Ws, Hs, Ds = W * sc, H * sc, D * sc

        meshes = []
        base_defs = [
            (
                v_image,
                [[vx, 0, 0], [vx, 0, Ds], [vx, Hs, Ds], [vx, Hs, 0]],
                [[0, 0], [1, 0], [1, 1], [0, 1]],
            ),
            (
                h_image,
                [[0, hy, 0], [Ws, hy, 0], [Ws, hy, Ds], [0, hy, Ds]],
                [[0, 1], [1, 1], [1, 0], [0, 0]],
            ),
        ]

        for img, verts, uvs in base_defs:
            v = np.array(verts, dtype=np.float64)
            u = np.array(uvs, dtype=np.float64)
            faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
            pil_img = Image.fromarray(img.astype(np.uint8))
            mat = trimesh.visual.material.PBRMaterial(
                baseColorTexture=pil_img, metallicFactor=0.0, roughnessFactor=1.0
            )
            vis = trimesh.visual.TextureVisuals(uv=u, material=mat)
            meshes.append(
                trimesh.Trimesh(vertices=v, faces=faces, visual=vis, process=False)
            )

        if isinstance(display_frames, dict):
            def _sort_key(item):
                k, _ = item
                try:
                    return int(k)
                except Exception:
                    return 0

            for frame_idx, img in sorted(display_frames.items(), key=_sort_key):
                idx = int(frame_idx)
                z = Ds * (idx - int(initial_frame)) / frame_span
                verts = np.array(
                    [[0, 0, z], [Ws, 0, z], [Ws, Hs, z], [0, Hs, z]],
                    dtype=np.float64,
                )
                uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
                faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
                # Match Preview3D: display frames are mirrored on X
                pil_img = Image.fromarray(np.fliplr(img).astype(np.uint8))
                mat = trimesh.visual.material.PBRMaterial(
                    baseColorTexture=pil_img, metallicFactor=0.0, roughnessFactor=1.0
                )
                vis = trimesh.visual.TextureVisuals(uv=uvs, material=mat)
                meshes.append(
                    trimesh.Trimesh(
                        vertices=verts, faces=faces, visual=vis, process=False,
                    )
                )

        scene = trimesh.Scene(meshes)
        scene.export(output_path, file_type="glb")

    # ------------------------------------------------------------------
    # Cuboid Fill export (stacked textured planes)
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_frame_paths(frames_dir):
        """Return sorted frame image paths from a cuboid-fill frames directory."""
        if not os.path.isdir(frames_dir):
            return []
        paths = []
        for name in sorted(os.listdir(frames_dir)):
            low = name.lower()
            if not name.startswith("frame_"):
                continue
            if low.endswith((".png", ".tiff", ".tif")):
                paths.append(os.path.join(frames_dir, name))
        return paths

    def export_cuboid_fill_obj(self, frames_dir, dimensions, output_path,
                               step=10, spacing_factor=1.0, pad_gaps=False):
        """Write stacked frame planes as OBJ + MTL (matching fill preview geometry)."""
        out_dir = os.path.dirname(output_path)
        obj_name = os.path.splitext(os.path.basename(output_path))[0]
        mtl_name = f"{obj_name}.mtl"

        W = float(dimensions["width"])
        H = float(dimensions["height"])
        total = max(1, int(dimensions["depth"]))

        paths = self._collect_frame_paths(frames_dir)
        if not paths:
            raise ValueError(f"No frame images found in {frames_dir}")
        if len(paths) > total:
            paths = paths[:total]

        step = max(1, int(step))
        if step > 1 and len(paths) // step < 2 and len(paths) >= 2:
            step = max(1, len(paths) // 10) or 1

        selected_indices = list(range(0, len(paths), step))
        if not selected_indices:
            selected_indices = [0]

        # Match Preview3D fill depth scaling
        max_spatial = max(W, H, 1.0)
        D = max_spatial * 0.4 * float(spacing_factor)

        max_dim = max(W, H, D)
        sc = 1.0 / max_dim if max_dim > 0 else 1.0
        Ws, Hs, Ds = W * sc, H * sc, D * sc

        # Write MTL
        mtl_path = os.path.join(out_dir, mtl_name)
        with open(mtl_path, "w") as f:
            for idx in selected_indices:
                tex_rel = os.path.relpath(paths[idx], out_dir).replace("\\", "/")
                f.write(f"newmtl mat_plane_{idx:06d}\n")
                f.write("Ka 1.0 1.0 1.0\nKd 1.0 1.0 1.0\n")
                f.write(f"map_Kd {tex_rel}\n\n")

        # Compute gap thickness between consecutive planes
        n_sel = len(selected_indices)
        if n_sel > 1:
            plane_gap = Ds / (n_sel - 1) if not pad_gaps else 0.0
        else:
            plane_gap = 0.0

        with open(output_path, "w") as f:
            f.write(f"mtllib {mtl_name}\n\n")

            if pad_gaps and plane_gap > 0:
                half_g = plane_gap / 2.0
                # 8 vertices per frame (box)
                for idx in selected_indices:
                    z = Ds * idx / max(1, len(paths) - 1)
                    z_min = z - half_g
                    z_max = z + half_g
                    f.write(f"v 0.000000 0.000000 {z_min:.6f}\n")
                    f.write(f"v {Ws:.6f} 0.000000 {z_min:.6f}\n")
                    f.write(f"v {Ws:.6f} {Hs:.6f} {z_min:.6f}\n")
                    f.write(f"v 0.000000 {Hs:.6f} {z_min:.6f}\n")
                    f.write(f"v 0.000000 0.000000 {z_max:.6f}\n")
                    f.write(f"v {Ws:.6f} 0.000000 {z_max:.6f}\n")
                    f.write(f"v {Ws:.6f} {Hs:.6f} {z_max:.6f}\n")
                    f.write(f"v 0.000000 {Hs:.6f} {z_max:.6f}\n")

                f.write("\n")
                # UVs: 4 UVs per frame (same for front and back faces)
                for _ in selected_indices:
                    f.write("vt 0.000000 0.000000\n")
                    f.write("vt 1.000000 0.000000\n")
                    f.write("vt 1.000000 1.000000\n")
                    f.write("vt 0.000000 1.000000\n")

                f.write("\n")
                # Front face (z_max) + Back face (z_min) per frame
                for i, idx in enumerate(selected_indices):
                    v0 = i * 8 + 1  # z_min: 1-4, z_max: 5-8
                    t0 = i * 4 + 1
                    f.write(f"usemtl mat_plane_{idx:06d}\n")
                    # Front face (z_max, vertices 5,6,7,8)
                    f.write(f"f {v0+4}/{t0} {v0+5}/{t0+1} {v0+6}/{t0+2} {v0+7}/{t0+3}\n")
                    # Back face (z_min, vertices 1,4,3,2 reversed)
                    f.write(f"f {v0}/{t0} {v0+3}/{t0+3} {v0+2}/{t0+2} {v0+1}/{t0+1}\n\n")
            else:
                # Vertices
                for idx in selected_indices:
                    z = Ds * idx / max(1, len(paths) - 1)
                    f.write(f"v 0.000000 0.000000 {z:.6f}\n")
                    f.write(f"v {Ws:.6f} 0.000000 {z:.6f}\n")
                    f.write(f"v {Ws:.6f} {Hs:.6f} {z:.6f}\n")
                    f.write(f"v 0.000000 {Hs:.6f} {z:.6f}\n")

                f.write("\n")

                # UVs
                for _ in selected_indices:
                    f.write("vt 0.000000 0.000000\n")
                    f.write("vt 1.000000 0.000000\n")
                    f.write("vt 1.000000 1.000000\n")
                    f.write("vt 0.000000 1.000000\n")

                f.write("\n")

                # Faces
                for i, idx in enumerate(selected_indices):
                    v0 = i * 4 + 1
                    t0 = i * 4 + 1
                    f.write(f"usemtl mat_plane_{idx:06d}\n")
                    f.write(
                        f"f {v0}/{t0} {v0+1}/{t0+1} {v0+2}/{t0+2} {v0+3}/{t0+3}\n\n"
                    )

    def export_cuboid_fill_gltf(self, frames_dir, dimensions, output_path,
                                step=10, spacing_factor=1.0, pad_gaps=False):
        """Write stacked frame planes as glTF/GLB (matching fill preview geometry)."""
        import trimesh

        W = float(dimensions["width"])
        H = float(dimensions["height"])
        total = max(1, int(dimensions["depth"]))

        paths = self._collect_frame_paths(frames_dir)
        if not paths:
            raise ValueError(f"No frame images found in {frames_dir}")
        if len(paths) > total:
            paths = paths[:total]

        step = max(1, int(step))
        if step > 1 and len(paths) // step < 2 and len(paths) >= 2:
            step = max(1, len(paths) // 10) or 1

        selected_indices = list(range(0, len(paths), step))
        if not selected_indices:
            selected_indices = [0]

        # Match Preview3D fill depth scaling
        max_spatial = max(W, H, 1.0)
        D = max_spatial * 0.4 * float(spacing_factor)

        max_dim = max(W, H, D)
        sc = 1.0 / max_dim if max_dim > 0 else 1.0
        Ws, Hs, Ds = W * sc, H * sc, D * sc

        uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)

        # Compute gap thickness between consecutive planes
        n_sel = len(selected_indices)
        if n_sel > 1 and pad_gaps:
            plane_gap = Ds / (n_sel - 1)
        else:
            plane_gap = 0.0

        meshes = []
        for idx in selected_indices:
            z = Ds * idx / max(1, len(paths) - 1)

            if pad_gaps and plane_gap > 0:
                half_g = plane_gap / 2.0
                z_min = z - half_g
                z_max = z + half_g
                # 8 vertices box
                verts = np.array([
                    [0, 0, z_min], [Ws, 0, z_min], [Ws, Hs, z_min], [0, Hs, z_min],
                    [0, 0, z_max], [Ws, 0, z_max], [Ws, Hs, z_max], [0, Hs, z_max],
                ], dtype=np.float64)
                box_uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64)
                box_faces = np.array([[4, 5, 6, 7], [0, 3, 2, 1]], dtype=np.int64)
            else:
                verts = np.array(
                    [[0, 0, z], [Ws, 0, z], [Ws, Hs, z], [0, Hs, z]],
                    dtype=np.float64,
                )
                box_uvs = uvs
                box_faces = faces

            pil_img = Image.open(paths[idx])
            mat = trimesh.visual.material.PBRMaterial(
                baseColorTexture=pil_img,
                metallicFactor=0.0,
                roughnessFactor=1.0,
            )
            vis = trimesh.visual.TextureVisuals(uv=box_uvs, material=mat)
            meshes.append(
                trimesh.Trimesh(vertices=verts, faces=box_faces, visual=vis, process=False)
            )

        scene = trimesh.Scene(meshes)
        scene.export(output_path, file_type="glb")

    # ------------------------------------------------------------------
    # Slit-tear export (textured curtain meshes)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_slittear_lines(full_image, rasterized_lines, pixel_counts):
        """Extract per-line textures and sampled points exactly like Preview3D."""
        lines = []
        row_offset = 0
        total_rows = full_image.shape[0]

        for line_idx, pixels in enumerate(rasterized_lines):
            n = len(pixels)
            count = pixel_counts[line_idx] if line_idx < len(pixel_counts) else n

            if n < 2 or count <= 0:
                row_offset += max(0, count) + (1 if line_idx > 0 else 0)
                continue

            sep = 1 if line_idx > 0 else 0
            start_row = row_offset + sep
            end_row = min(total_rows, start_row + count)
            row_offset = end_row

            if end_row <= start_row:
                continue

            line_texture = full_image[start_row:end_row, :, :]

            # Subsample long lines for performance (same as Preview3D)
            step = max(1, n // 500)
            sampled_indices = list(range(0, n, step))
            if sampled_indices[-1] != n - 1:
                sampled_indices.append(n - 1)

            sampled = [(idx, pixels[idx][0], pixels[idx][1]) for idx in sampled_indices]
            lines.append((line_idx, line_texture, sampled, n))

        return lines

    def export_slittear_obj(self, full_image, rasterized_lines, pixel_counts,
                            depth, frame_width, frame_height, output_path):
        """Write slit-tear curtain meshes as OBJ + MTL."""
        out_dir = os.path.dirname(output_path)
        obj_name = os.path.splitext(os.path.basename(output_path))[0]
        mtl_name = f"{obj_name}.mtl"

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)

        max_dim = max(W, H, D)
        sc = 1.0 / max_dim if max_dim > 0 else 1.0
        Ws, Hs, Ds = W * sc, H * sc, D * sc

        lines = self._build_slittear_lines(full_image, rasterized_lines, pixel_counts)
        if not lines:
            raise ValueError("No valid slit-tear line geometry to export")

        # Save per-line textures + MTL
        with open(os.path.join(out_dir, mtl_name), "w") as f:
            for line_idx, line_tex, _sampled, _n in lines:
                tex_name = f"slittear_line_{line_idx:03d}.png"
                Image.fromarray(line_tex.astype(np.uint8)).save(os.path.join(out_dir, tex_name))
                f.write(f"newmtl mat_line_{line_idx:03d}\n")
                f.write("Ka 1.0 1.0 1.0\nKd 1.0 1.0 1.0\n")
                f.write(f"map_Kd {tex_name}\n\n")

        with open(output_path, "w") as f:
            f.write(f"mtllib {mtl_name}\n\n")

            vert_base = 1
            uv_base = 1

            for line_idx, _line_tex, sampled, n in lines:
                ns = len(sampled)
                if ns < 2:
                    continue

                # Vertices + UVs
                for idx, px, py in sampled:
                    x = float(px) * sc
                    y = (H - float(py)) * sc
                    v_coord = 1.0 - idx / max(1, n - 1)
                    f.write(f"v {x:.6f} {y:.6f} 0.000000\n")
                    f.write(f"v {x:.6f} {y:.6f} {Ds:.6f}\n")
                    f.write(f"vt 0.000000 {v_coord:.6f}\n")
                    f.write(f"vt 1.000000 {v_coord:.6f}\n")

                f.write("\n")
                f.write(f"usemtl mat_line_{line_idx:03d}\n")

                for j in range(ns - 1):
                    # Vertex indices (two rows interleaved per sampled point)
                    a = vert_base + j * 2
                    b = vert_base + (j + 1) * 2
                    c = vert_base + (j + 1) * 2 + 1
                    d = vert_base + j * 2 + 1

                    ua = uv_base + j * 2
                    ub = uv_base + (j + 1) * 2
                    uc = uv_base + (j + 1) * 2 + 1
                    ud = uv_base + j * 2 + 1

                    f.write(f"f {a}/{ua} {b}/{ub} {c}/{uc}\n")
                    f.write(f"f {a}/{ua} {c}/{uc} {d}/{ud}\n")

                f.write("\n")
                vert_base += ns * 2
                uv_base += ns * 2

    def export_slittear_gltf(self, full_image, rasterized_lines, pixel_counts,
                             depth, frame_width, frame_height, output_path):
        """Write slit-tear curtain meshes as glTF/GLB."""
        import trimesh

        W = float(frame_width)
        H = float(frame_height)
        D = float(depth)

        max_dim = max(W, H, D)
        sc = 1.0 / max_dim if max_dim > 0 else 1.0
        Ds = D * sc

        lines = self._build_slittear_lines(full_image, rasterized_lines, pixel_counts)
        if not lines:
            raise ValueError("No valid slit-tear line geometry to export")

        meshes = []
        for _line_idx, line_tex, sampled, n in lines:
            ns = len(sampled)
            if ns < 2:
                continue

            verts = np.zeros((ns * 2, 3), dtype=np.float64)
            uvs = np.zeros((ns * 2, 2), dtype=np.float64)
            for j, (idx, px, py) in enumerate(sampled):
                x = float(px) * sc
                y = (H - float(py)) * sc
                v_coord = 1.0 - idx / max(1, n - 1)

                verts[j * 2] = [x, y, 0.0]
                verts[j * 2 + 1] = [x, y, Ds]
                uvs[j * 2] = [0.0, v_coord]
                uvs[j * 2 + 1] = [1.0, v_coord]

            faces = []
            for j in range(ns - 1):
                a = j * 2
                b = (j + 1) * 2
                c = (j + 1) * 2 + 1
                d = j * 2 + 1
                faces.append([a, b, c])
                faces.append([a, c, d])

            faces = np.array(faces, dtype=np.int64)
            pil_img = Image.fromarray(line_tex.astype(np.uint8))
            mat = trimesh.visual.material.PBRMaterial(
                baseColorTexture=pil_img,
                metallicFactor=0.0,
                roughnessFactor=1.0,
            )
            vis = trimesh.visual.TextureVisuals(uv=uvs, material=mat)
            meshes.append(
                trimesh.Trimesh(vertices=verts, faces=faces, visual=vis, process=False)
            )

        if not meshes:
            raise ValueError("No valid slit-tear meshes to export")

        scene = trimesh.Scene(meshes)
        scene.export(output_path, file_type="glb")
