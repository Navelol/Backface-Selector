# Select Orientation with Z-Depth
### A Blender Addon by Evan Pierce
**Minimum Blender version: 2.91** — developed on 4.3.2, compatible all the way back to 2.91.

Selects front-facing or back-facing geometry relative to your current viewport, with occlusion culling, X-Ray mode, and loose part island selection.

---

## Features

- **Front / Back Facing** — select only the faces (or verts/edges) whose normals point toward or away from your viewport camera
- **Loose Parts** — use facing detection as a seed and expand to the entire connected island, just like hitting `L`
- **Occlusion culling** — faces hidden behind other geometry are excluded by default
- **X-Ray toggle** — disable occlusion to select through meshes
- **Select mode aware** — respects Blender's active select mode (Vertex / Edge / Face)
- **Orthographic support** — works correctly in ortho views, not just perspective

---

## Installation

1. Download the latest `SelectBackfacing.py` from [Releases](../../releases)
2. In Blender, go to **Edit → Preferences → Add-ons → Install**
3. Select the downloaded `.py` file and click **Install Add-on**
4. Enable the checkbox next to **"Select Orientation with Z-Depth"**

---

## Usage

Open the **N-Panel** (`N` key in the 3D Viewport) and go to the **Select** tab.

### By Vertices
| Button | What it does |
|---|---|
| **Front Facing** | Selects geometry whose normals face toward the viewport |
| **Back Facing** | Selects geometry whose normals face away from the viewport |

### By Loose Part
| Button | What it does |
|---|---|
| **Front Parts** | Selects entire mesh islands that contain at least one front-facing face |
| **Back Parts** | Selects entire mesh islands that contain at least one back-facing face |

### X-Ray (Ignore Occlusion)
Toggle this on to select matching faces even if they are hidden behind other geometry. When off, only faces visible from the current viewpoint are selected.

![ezgif-2670251efbe70e60](https://github.com/user-attachments/assets/cc028ae0-32f6-475c-98ce-8c2b1a0a6682)

---

## Notes

- The addon must be used in **Edit Mode**
- All four buttons respect the **X-Ray** toggle at the time they are clicked
- The info bar at the bottom of Blender will show a breakdown of how many faces passed each stage (orientation → occlusion → island expand)

---

## License

MIT License — free to use, modify, and distribute.
