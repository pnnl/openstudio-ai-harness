"""Build a self-contained OpenStudio geometry viewer."""

from __future__ import annotations

import json
import math
from typing import Any


def _name(item: Any, fallback: str) -> str:
    return (item.nameString() if hasattr(item, "nameString") else "") or fallback


def _optional_name(optional: Any, fallback: str = "Unassigned") -> str:
    return _name(optional.get(), fallback) if optional.is_initialized() else fallback


def _handle(item: Any) -> str:
    return str(item.handle())


def _vertices(item: Any, transformation: Any | None = None) -> list[list[float]]:
    vertices = item.vertices()
    if transformation is not None:
        vertices = [transformation * vertex for vertex in vertices]
    return [
        [float(point.x()), float(point.y()), float(point.z())] for point in vertices
    ]


def _finite_polygon(vertices: list[list[float]]) -> bool:
    if len(vertices) < 3 or not all(
        math.isfinite(value) for point in vertices for value in point
    ):
        return False
    origin = vertices[0]
    for candidate in vertices[1:]:
        edge = [candidate[index] - origin[index] for index in range(3)]
        if not any(edge):
            continue
        for point in vertices[1:]:
            other = [point[index] - origin[index] for index in range(3)]
            cross = [
                edge[1] * other[2] - edge[2] * other[1],
                edge[2] * other[0] - edge[0] * other[2],
                edge[0] * other[1] - edge[1] * other[0],
            ]
            if any(cross):
                return True
        return False
    return False


def _surface_record(
    surface: Any, space_id: str, kind: str, *, transformation: Any | None = None
) -> dict[str, Any] | None:
    vertices = _vertices(surface, transformation)
    if not _finite_polygon(vertices):
        return None
    if kind == "surface":
        surface_type, area, boundary = (
            surface.surfaceType(),
            surface.grossArea(),
            surface.outsideBoundaryCondition(),
        )
    elif kind == "subsurface":
        surface_type, area, boundary = surface.subSurfaceType(), surface.netArea(), ""
    else:
        surface_type, area, boundary = "Shading", surface.grossArea(), ""
    return {
        "id": _handle(surface),
        "space_id": space_id,
        "name": _name(surface, "Unnamed surface"),
        "kind": kind,
        "surface_type": surface_type,
        "boundary_condition": boundary,
        "area_m2": round(float(area), 3),
        "vertices": vertices,
    }


def build_geometry_scene(
    model: Any, *, source_model: str, include_subsurfaces: bool, include_shading: bool
) -> dict[str, Any]:
    """Return JSON-safe geometry and searchable OpenStudio space metadata."""
    warnings: list[str] = []
    spaces: list[dict[str, Any]] = []
    faces: list[dict[str, Any]] = []
    bounds: list[float] | None = None

    def add_face(face: dict[str, Any]) -> None:
        nonlocal bounds
        faces.append(face)
        values = [value for point in face["vertices"] for value in point]
        current = [
            min(values[0::3]),
            min(values[1::3]),
            min(values[2::3]),
            max(values[0::3]),
            max(values[1::3]),
            max(values[2::3]),
        ]
        bounds = (
            current
            if bounds is None
            else [
                min(bounds[0], current[0]),
                min(bounds[1], current[1]),
                min(bounds[2], current[2]),
                max(bounds[3], current[3]),
                max(bounds[4], current[4]),
                max(bounds[5], current[5]),
            ]
        )

    def add_record(record: dict[str, Any] | None, label: str, item: Any) -> None:
        if record is None:
            warnings.append(f"Skipped invalid {label}: {_name(item, _handle(item))}")
        else:
            add_face(record)

    for space in model.getSpaces():
        space_id, transform = _handle(space), space.siteTransformation()
        surfaces = list(space.surfaces())
        spaces.append(
            {
                "id": space_id,
                "name": _name(space, "Unnamed space"),
                "story": _optional_name(space.buildingStory()),
                "thermal_zone": _optional_name(space.thermalZone()),
                "space_type": _optional_name(space.spaceType()),
                "floor_area_m2": round(float(space.floorArea()), 3),
                "volume_m3": round(float(space.volume()), 3),
                "surface_count": len(surfaces),
            }
        )
        for surface in surfaces:
            add_record(
                _surface_record(surface, space_id, "surface", transformation=transform),
                "surface",
                surface,
            )
            if include_subsurfaces:
                for subsurface in surface.subSurfaces():
                    add_record(
                        _surface_record(
                            subsurface, space_id, "subsurface", transformation=transform
                        ),
                        "subsurface",
                        subsurface,
                    )
    if include_shading:
        for shading in model.getShadingSurfaces():
            group = shading.shadingSurfaceGroup()
            transform = (
                group.get().siteTransformation() if group.is_initialized() else None
            )
            add_record(
                _surface_record(
                    shading, "__shading__", "shading", transformation=transform
                ),
                "shading surface",
                shading,
            )
    return {
        "version": 1,
        "source_model": source_model,
        "units": "m",
        "bounds": bounds or [0, 0, 0, 1, 1, 1],
        "spaces": sorted(
            spaces, key=lambda item: (item["story"], item["name"].lower())
        ),
        "faces": faces,
        "counts": {
            "spaces": len(spaces),
            "faces": len(faces),
            "stories": len(
                {item["story"] for item in spaces if item["story"] != "Unassigned"}
            ),
        },
        "warnings": warnings,
    }


def render_geometry_viewer_html(scene: dict[str, Any]) -> str:
    """Create a fully offline canvas viewer with one direct renderer."""
    payload = json.dumps(scene, separators=(",", ":")).replace("<", "\\u003c")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OpenStudio Geometry Viewer</title><style>
*{{box-sizing:border-box}}body{{margin:0;font:14px system-ui,sans-serif;background:#f4f7fb;color:#172033}}header{{height:58px;padding:11px 18px;background:#102a43;color:white;display:flex;align-items:center;justify-content:space-between}}h1{{font-size:17px;margin:0}}#layout{{display:grid;grid-template-columns:320px 1fr;height:calc(100vh - 58px);min-height:0}}aside{{min-height:0;padding:14px;background:#fff;border-right:1px solid #d9e2ec;overflow:auto}}label{{display:block;font-size:12px;font-weight:650;margin-top:12px}}input,select,button{{width:100%;padding:8px;margin-top:4px;border:1px solid #bcccdc;border-radius:5px;background:white}}button{{cursor:pointer;background:#edf2f7}}#spaces,#surface-list{{list-style:none;padding:0;margin:12px 0}}.space{{padding:9px;border-bottom:1px solid #edf2f7;cursor:pointer}}.space:hover,.space.active{{background:#d9eaf7}}.meta{{font-size:12px;color:#486581;margin-top:3px}}main{{position:relative;min-width:0;min-height:0}}canvas{{display:block;width:100%;height:100%;background:linear-gradient(#eaf4ff,#f8fbff)}}#detail{{position:absolute;right:16px;top:16px;background:#fffdfaee;border:1px solid #bcccdc;border-radius:6px;padding:10px;max-width:290px;display:none}}#hint{{position:absolute;bottom:12px;right:16px;color:#486581;background:#ffffffcc;padding:6px 9px;border-radius:4px;font-size:12px}}.checks{{display:flex;gap:8px;align-items:center;margin-top:8px}}.checks label{{margin:0;font-weight:400}}.checks input{{width:auto;margin-right:4px}}@media(max-width:700px){{#layout{{grid-template-columns:1fr;height:auto;min-height:calc(100vh - 58px)}}aside{{max-height:42vh}}canvas{{height:58vh}}}}
</style></head><body><header><div><h1>OpenStudio Geometry Viewer</h1><div id="summary"></div></div><button id="reset" style="width:auto;color:#102a43">Reset view</button></header><div id="layout"><aside><label>Search spaces<input id="search" placeholder="Name, floor, zone, type"></label><label>Floor / story<select id="story"><option value="">All floors</option></select></label><label>Sort spaces<select id="sort"><option value="name">Name</option><option value="story">Floor / story</option><option value="area">Floor area</option><option value="volume">Volume</option></select></label><div class="checks"><label><input type="checkbox" id="sub" checked>Windows & doors</label></div><div class="checks"><label><input type="checkbox" id="shade" checked>Shading</label></div><button id="showall">Show all spaces</button><ul id="spaces" onclick="setTimeout(()=>this.querySelector('[aria-pressed=true]')?.focus())"></ul><details open><summary>Surfaces</summary><ul id="surface-list" aria-label="Surfaces"></ul></details></aside><main><canvas id="canvas"></canvas><div id="detail"></div><div id="hint">Drag or arrow keys to orbit · scroll or +/- to zoom · Home resets · click any surface for details</div></main></div><script>const scene={payload};
const $=s=>document.querySelector(s),canvas=$('#canvas'),ctx=canvas.getContext('2d'),list=$('#spaces'),surfaceList=$('#surface-list'),detail=$('#detail'),search=$('#search'),story=$('#story'),sort=$('#sort'),sub=$('#sub'),shade=$('#shade'),byId=new Map(scene.faces.map(f=>[f.id,f])),colors={{Wall:'#7aa7d9',Floor:'#91c788',RoofCeiling:'#d7a7d9',default:'#9eb7ca',FixedWindow:'#f7c873',OperableWindow:'#f7c873',GlassDoor:'#f7c873',Door:'#b9805b',shading:'#8b8f98'}},b=scene.bounds,cx=(b[0]+b[3])/2,cy=(b[1]+b[4])/2,cz=(b[2]+b[5])/2,span=Math.max(b[3]-b[0],b[4]-b[1],b[5]-b[2],1),resetYaw=-.7,resetPitch=.65;let selected=null,selectedFaceId=null,ids=new Set(scene.spaces.map(s=>s.id)),yaw=resetYaw,pitch=resetPitch,zoom=1,drag=null;
function esc(v){{return String(v).replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]))}}function camera(){{let c=Math.cos(pitch),s=Math.sin(pitch),co=Math.cos(yaw),si=Math.sin(yaw);return {{d:[si*c,-co*c,s],r:[co,si,0],u:[-si*s,co*s,c]}}}}function project(p){{let v=[p[0]-cx,p[1]-cy,p[2]-cz],q=camera(),dot=(a,d)=>a[0]*d[0]+a[1]*d[1]+a[2]*d[2],z=span*3-dot(v,q.d),scale=Math.min(canvas.clientWidth,canvas.clientHeight)/span*zoom;return [canvas.clientWidth/2+dot(v,q.r)/z*scale*span,canvas.clientHeight/2-dot(v,q.u)/z*scale*span,z]}}function normal(v){{let n=[0,0,0];for(let i=0;i<v.length;i++){{let a=v[i],b=v[(i+1)%v.length];n[0]+=(a[1]-b[1])*(a[2]+b[2]);n[1]+=(a[2]-b[2])*(a[0]+b[0]);n[2]+=(a[0]-b[0])*(a[1]+b[1])}}return n}}function visible(f){{let n=normal(f.vertices),d=camera().d;return(f.kind!=='subsurface'||sub.checked)&&(f.kind!=='shading'||shade.checked)&&(f.space_id==='__shading__'||ids.has(f.space_id))&&(f.id===selectedFaceId||f.kind==='shading'||n[0]*d[0]+n[1]*d[1]+n[2]*d[2]>1e-7)&&(!selected||f.space_id===selected||f.space_id==='__shading__')}}function faces(){{return scene.faces.filter(visible).map(f=>({{f,p:f.vertices.map(project)}})).sort((a,b)=>b.p.reduce((s,p)=>s+p[2],0)/b.p.length-a.p.reduce((s,p)=>s+p[2],0)/a.p.length)}}function paint(p,fill,alpha,stroke,width){{ctx.beginPath();ctx.moveTo(p[0][0],p[0][1]);for(let i=1;i<p.length;i++)ctx.lineTo(p[i][0],p[i][1]);ctx.closePath();ctx.fillStyle=fill;ctx.globalAlpha=alpha;ctx.fill();ctx.globalAlpha=1;ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke()}}function draw(){{ctx.clearRect(0,0,canvas.clientWidth,canvas.clientHeight);let all=faces();for(let x of all){{let f=x.f;paint(x.p,f.space_id===selected?'#ef5b5b':(colors[f.kind==='shading'?'shading':f.surface_type]||colors.default),f.kind==='subsurface'?.92:.62,f.space_id===selected?'#9b1c1c':'#ffffffaa',f.space_id===selected?2:1)}}let chosen=all.find(x=>x.f.id===selectedFaceId);if(chosen)paint(chosen.p,'#ef5b5b',.92,'#8a1010',3)}}
function filtered(){{let q=search.value.trim().toLowerCase();return scene.spaces.filter(s=>(!q||[s.name,s.story,s.thermal_zone,s.space_type].join(' ').toLowerCase().includes(q))&&(!story.value||s.story===story.value))}}function listSpaces(){{let items=filtered(),mode=sort.value;items.sort((a,b)=>mode==='name'?a.name.localeCompare(b.name):mode==='story'?a.story.localeCompare(b.story)||a.name.localeCompare(b.name):b[mode==='area'?'floor_area_m2':'volume_m3']-a[mode==='area'?'floor_area_m2':'volume_m3']);list.innerHTML=items.map(s=>'<li><button type="button" class="space '+(s.id===selected?'active':'')+'" data-id="'+s.id+'" aria-pressed="'+(s.id===selected)+'"><strong>'+esc(s.name)+'</strong><span class="meta">'+esc(s.story)+' · '+s.floor_area_m2+' m² · '+esc(s.thermal_zone)+'</span></button></li>').join('')||'<li class="meta">No matching spaces.</li>';list.querySelectorAll('[data-id]').forEach(e=>e.onclick=()=>selectSpace(e.dataset.id))}}function listSurfaces(){{let all=scene.faces.filter(f=>(f.kind!=='subsurface'||sub.checked)&&(f.kind!=='shading'||shade.checked)).sort((a,b)=>a.name.localeCompare(b.name));surfaceList.innerHTML=all.map(f=>'<li '+(f.space_id!=='__shading__'&&!ids.has(f.space_id)?'hidden':'')+'><button type="button" class="space" data-face-id="'+f.id+'">'+esc(f.name)+'<span class="meta">'+esc(f.surface_type)+' · '+f.area_m2+' m²</span></button></li>').join('')||'<li class="meta">No visible surfaces.</li>';surfaceList.querySelectorAll('[data-face-id]').forEach(e=>e.onclick=()=>showSurface(byId.get(e.dataset.faceId)))}}function selectSpace(id){{selected=id;selectedFaceId=null;let s=scene.spaces.find(x=>x.id===id);detail.style.display='block';detail.innerHTML='<strong>'+esc(s.name)+'</strong><div class="meta">'+esc(s.story)+'<br>'+esc(s.space_type)+'<br>Zone: '+esc(s.thermal_zone)+'<br>'+s.floor_area_m2+' m² · '+s.volume_m3+' m³<br>'+s.surface_count+' surfaces</div>';listSpaces();draw()}}function showSurface(f){{selected=null;selectedFaceId=f.id;let s=scene.spaces.find(x=>x.id===f.space_id);detail.style.display='block';detail.innerHTML='<strong>'+esc(f.name)+'</strong><div class="meta">Surface type: '+esc(f.surface_type)+'<br>Belongs to: '+esc(s?s.name:'Shading geometry')+'<br>Floor: '+esc(s?s.story:'Unassigned')+'<br>Area: '+f.area_m2+' m²<br>Boundary: '+esc(f.boundary_condition||'N/A')+'</div>';listSpaces();draw()}}function applyFilter(){{ids=new Set(filtered().map(s=>s.id));if(selected&&!ids.has(selected)){{selected=null;selectedFaceId=null;detail.style.display='none'}}let f=selectedFaceId&&byId.get(selectedFaceId);if(f&&!visible(f)){{selectedFaceId=null;detail.style.display='none'}}listSpaces();listSurfaces();draw()}}function inside(x,y,p){{let hit=false;for(let i=0,j=p.length-1;i<p.length;j=i++){{let a=p[i],b=p[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit}}return hit}}function resize(){{canvas.width=canvas.clientWidth*devicePixelRatio;canvas.height=canvas.clientHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);draw()}}
canvas.tabIndex=0;canvas.setAttribute('aria-label','Building geometry. Arrow keys orbit, plus and minus zoom, Home resets, and the surface list inspects individual surfaces.');canvas.onpointerdown=e=>{{drag={{x:e.clientX,y:e.clientY,moved:false}};canvas.setPointerCapture(e.pointerId)}};canvas.onpointermove=e=>{{if(!drag)return;let dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>3)drag.moved=true;yaw+=dx*.01;pitch=Math.max(-1.4,Math.min(1.4,pitch+dy*.01));drag.x=e.clientX;drag.y=e.clientY;draw()}};canvas.onpointerup=e=>{{if(drag&&!drag.moved){{let r=canvas.getBoundingClientRect(),hit=[...faces()].reverse().find(x=>inside(e.clientX-r.left,e.clientY-r.top,x.p));if(hit)showSurface(hit.f)}}drag=null}};canvas.onwheel=e=>{{e.preventDefault();zoom=Math.max(.35,Math.min(3,zoom*(e.deltaY>0?.9:1.1)));draw()}};canvas.onkeydown=e=>{{let ok=true;if(e.key==='ArrowLeft')yaw-=.1;else if(e.key==='ArrowRight')yaw+=.1;else if(e.key==='ArrowUp')pitch=Math.min(1.4,pitch+.1);else if(e.key==='ArrowDown')pitch=Math.max(-1.4,pitch-.1);else if(e.key==='+'||e.key==='=')zoom=Math.min(3,zoom*1.1);else if(e.key==='-')zoom=Math.max(.35,zoom*.9);else if(e.key==='Home'){{yaw=resetYaw;pitch=resetPitch;zoom=1}}else ok=false;if(ok){{e.preventDefault();draw()}}}};search.oninput=applyFilter;story.oninput=applyFilter;story.onchange=applyFilter;sort.oninput=listSpaces;sort.onchange=listSpaces;sub.onchange=()=>{{listSurfaces();applyFilter()}};shade.onchange=()=>{{listSurfaces();applyFilter()}};$('#reset').onclick=()=>{{yaw=resetYaw;pitch=resetPitch;zoom=1;selected=null;selectedFaceId=null;detail.style.display='none';listSpaces();draw()}};$('#showall').onclick=()=>{{search.value='';story.value='';selected=null;selectedFaceId=null;detail.style.display='none';applyFilter()}};[...new Set(scene.spaces.map(s=>s.story))].sort().forEach(v=>story.add(new Option(v,v)));$('#summary').textContent=`${{scene.source_model}} · ${{scene.counts.spaces}} spaces · ${{scene.counts.stories}} stories · ${{scene.counts.faces}} faces${{scene.warnings.length?' · '+scene.warnings.length+' warnings':''}}`;listSurfaces();applyFilter();addEventListener('resize',resize);resize();</script></body></html>"""
