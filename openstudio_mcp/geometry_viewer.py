"""Build the data and self-contained page used by the OSM geometry viewer."""

from __future__ import annotations

import json
import math
from typing import Any


def _name(item: Any, fallback: str) -> str:
    value = item.nameString() if hasattr(item, "nameString") else ""
    return value or fallback


def _optional_name(optional: Any, fallback: str = "Unassigned") -> str:
    return _name(optional.get(), fallback) if optional.is_initialized() else fallback


def _handle(item: Any) -> str:
    return str(item.handle())


def _vertices(item: Any, transformation: Any | None = None) -> list[list[float]]:
    vertices = item.vertices()
    if transformation is not None:
        vertices = [transformation * vertex for vertex in vertices]
    return [[float(v.x()), float(v.y()), float(v.z())] for v in vertices]


def _finite_polygon(vertices: list[list[float]]) -> bool:
    return len(vertices) >= 3 and all(
        math.isfinite(value) for point in vertices for value in point
    )


def _surface_record(
    surface: Any,
    space_id: str,
    kind: str,
    *,
    transformation: Any | None = None,
) -> dict[str, Any] | None:
    vertices = _vertices(surface, transformation)
    if not _finite_polygon(vertices):
        return None
    if kind == "surface":
        surface_type = surface.surfaceType()
        area = surface.grossArea()
        boundary_condition = surface.outsideBoundaryCondition()
    elif kind == "subsurface":
        surface_type = surface.subSurfaceType()
        area = surface.netArea()
        boundary_condition = ""
    else:
        surface_type = "Shading"
        area = surface.grossArea()
        boundary_condition = ""
    return {
        "id": _handle(surface),
        "space_id": space_id,
        "name": _name(surface, "Unnamed surface"),
        "kind": kind,
        "surface_type": surface_type,
        "boundary_condition": boundary_condition,
        "area_m2": round(float(area), 3),
        "vertices": vertices,
    }


def build_geometry_scene(
    model: Any,
    *,
    source_model: str,
    include_subsurfaces: bool,
    include_shading: bool,
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
        if bounds is None:
            bounds = current
        else:
            bounds = [
                min(bounds[0], current[0]),
                min(bounds[1], current[1]),
                min(bounds[2], current[2]),
                max(bounds[3], current[3]),
                max(bounds[4], current[4]),
                max(bounds[5], current[5]),
            ]

    for space in model.getSpaces():
        space_id = _handle(space)
        story = _optional_name(space.buildingStory())
        zone = _optional_name(space.thermalZone())
        space_type = _optional_name(space.spaceType())
        surfaces = list(space.surfaces())
        transformation = space.siteTransformation()
        spaces.append(
            {
                "id": space_id,
                "name": _name(space, "Unnamed space"),
                "story": story,
                "thermal_zone": zone,
                "space_type": space_type,
                "floor_area_m2": round(float(space.floorArea()), 3),
                "volume_m3": round(float(space.volume()), 3),
                "surface_count": len(surfaces),
            }
        )
        for surface in surfaces:
            record = _surface_record(
                surface, space_id, "surface", transformation=transformation
            )
            if record is None:
                warnings.append(
                    f"Skipped invalid surface: {_name(surface, _handle(surface))}"
                )
            else:
                add_face(record)
            if include_subsurfaces:
                for subsurface in surface.subSurfaces():
                    record = _surface_record(
                        subsurface,
                        space_id,
                        "subsurface",
                        transformation=transformation,
                    )
                    if record is None:
                        warnings.append(
                            f"Skipped invalid subsurface: {_name(subsurface, _handle(subsurface))}"
                        )
                    else:
                        add_face(record)

    if include_shading:
        for shading in model.getShadingSurfaces():
            group = shading.shadingSurfaceGroup()
            transformation = (
                group.get().siteTransformation() if group.is_initialized() else None
            )
            record = _surface_record(
                shading,
                "__shading__",
                "shading",
                transformation=transformation,
            )
            if record is None:
                warnings.append(
                    f"Skipped invalid shading surface: {_name(shading, _handle(shading))}"
                )
            else:
                add_face(record)

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
    """Create a fully offline canvas viewer; no CDN, server, or local fetch is required."""
    # Escape every less-than sign so model-provided strings cannot form an HTML
    # tag (including mixed-case </script>) inside the embedded JSON script.
    payload = json.dumps(scene, separators=(",", ":")).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>OpenStudio Geometry Viewer</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;font:14px system-ui,sans-serif;background:#f4f7fb;color:#172033}} header{{height:58px;padding:11px 18px;background:#102a43;color:white;display:flex;align-items:center;justify-content:space-between}} h1{{font-size:17px;margin:0}} #layout{{display:grid;grid-template-columns:320px 1fr;min-height:calc(100vh - 58px)}} aside{{padding:14px;background:#fff;border-right:1px solid #d9e2ec;overflow:auto}} label{{display:block;font-size:12px;font-weight:650;margin-top:12px}} input,select,button{{width:100%;padding:8px;margin-top:4px;border:1px solid #bcccdc;border-radius:5px;background:white}} button{{cursor:pointer;background:#edf2f7}} #spaces{{list-style:none;padding:0;margin:12px 0}} .space{{padding:9px;border-bottom:1px solid #edf2f7;cursor:pointer}} .space:hover,.space.active{{background:#d9eaf7}} .meta{{font-size:12px;color:#627d98;margin-top:3px}} main{{position:relative;min-width:0}} canvas{{display:block;width:100%;height:calc(100vh - 58px);background:linear-gradient(#eaf4ff,#f8fbff)}} #detail{{position:absolute;right:16px;top:16px;background:#fffdfaee;border:1px solid #bcccdc;border-radius:6px;padding:10px;max-width:290px;display:none}} #hint{{position:absolute;bottom:12px;right:16px;color:#486581;background:#ffffffcc;padding:6px 9px;border-radius:4px;font-size:12px}} .checks{{display:flex;gap:8px;align-items:center;margin-top:8px}} .checks label{{margin:0;font-weight:400}} .checks input{{width:auto;margin-right:4px}}
</style></head><body><header><div><h1>OpenStudio Geometry Viewer</h1><div id=\"summary\"></div></div><button id=\"reset\" style=\"width:auto;color:#102a43\">Reset view</button></header><div id=\"layout\"><aside><label>Search spaces<input id=\"search\" placeholder=\"Name, floor, zone, type\"></label><label>Floor / story<select id=\"story\"><option value=\"\">All floors</option></select></label><label>Sort spaces<select id=\"sort\"><option value=\"name\">Name</option><option value=\"story\">Floor / story</option><option value=\"area\">Floor area</option><option value=\"volume\">Volume</option></select></label><div class=\"checks\"><label><input type=\"checkbox\" id=\"sub\" checked>Windows & doors</label></div><div class=\"checks\"><label><input type=\"checkbox\" id=\"shade\" checked>Shading</label></div><button id=\"showall\">Show all spaces</button><ul id=\"spaces\"></ul></aside><main><canvas id=\"canvas\"></canvas><div id=\"detail\"></div><div id=\"hint\">Drag to orbit · scroll to zoom · click a space in the list</div></main></div>
<script>const scene={payload};
const canvas=document.querySelector('#canvas'),ctx=canvas.getContext('2d'),list=document.querySelector('#spaces'),detail=document.querySelector('#detail');let selected=null,yaw=-.7,pitch=.55,zoom=1,drag=null;
const colors={{Wall:'#7aa7d9',Floor:'#91c788',RoofCeiling:'#d7a7d9',default:'#9eb7ca',FixedWindow:'#f7c873',OperableWindow:'#f7c873',GlassDoor:'#f7c873',Door:'#b9805b',shading:'#8b8f98'}};
function resize(){{canvas.width=canvas.clientWidth*devicePixelRatio;canvas.height=canvas.clientHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);draw()}} addEventListener('resize',resize);
const b=scene.bounds,cx=(b[0]+b[3])/2,cy=(b[1]+b[4])/2,cz=(b[2]+b[5])/2,span=Math.max(b[3]-b[0],b[4]-b[1],b[5]-b[2],1);
function project(p){{let x=p[0]-cx,y=p[1]-cy,z=p[2]-cz,ca=Math.cos(yaw),sa=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);let rx=x*ca-y*sa,ry=x*sa+y*ca,rz=z;let py=ry*cp-rz*sp,pz=ry*sp+rz*cp+span*2.2;let scale=Math.min(canvas.clientWidth,canvas.clientHeight)/span*zoom;return [canvas.clientWidth/2+rx/pz*scale*span,canvas.clientHeight/2-py/pz*scale*span,pz]}}
function visible(face){{if(face.kind==='subsurface'&&!document.querySelector('#sub').checked)return false;if(face.kind==='shading'&&!document.querySelector('#shade').checked)return false;return !selected||face.space_id===selected||face.space_id==='__shading__'}}
function draw(){{ctx.clearRect(0,0,canvas.clientWidth,canvas.clientHeight);let faces=scene.faces.filter(visible).map(f=>({{f,p:f.vertices.map(project)}})).sort((a,b)=>b.p.reduce((s,x)=>s+x[2],0)/b.p.length-a.p.reduce((s,x)=>s+x[2],0)/a.p.length);for(const item of faces){{let p=item.p;ctx.beginPath();ctx.moveTo(p[0][0],p[0][1]);for(let i=1;i<p.length;i++)ctx.lineTo(p[i][0],p[i][1]);ctx.closePath();let f=item.f;ctx.fillStyle=f.space_id===selected?'#ef5b5b':(colors[f.kind==='shading'?'shading':f.surface_type]||colors.default);ctx.globalAlpha=f.kind==='subsurface'?.92:.62;ctx.fill();ctx.globalAlpha=1;ctx.strokeStyle=f.space_id===selected?'#9b1c1c':'#ffffffaa';ctx.lineWidth=f.space_id===selected?2:1;ctx.stroke()}}}}
function filtered(){{let q=search.value.trim().toLowerCase(),story=storySelect.value;return scene.spaces.filter(s=>{{let hay=[s.name,s.story,s.thermal_zone,s.space_type].join(' ').toLowerCase();return(!q||hay.includes(q))&&(!story||s.story===story)}})}}
function renderList(){{let items=filtered(),mode=sortSelect.value;items.sort((a,b)=>mode==='name'?a.name.localeCompare(b.name):mode==='story'?a.story.localeCompare(b.story)||a.name.localeCompare(b.name):b[mode==='area'?'floor_area_m2':'volume_m3']-a[mode==='area'?'floor_area_m2':'volume_m3']);list.innerHTML=items.map(s=>`<li class=\"space ${{s.id===selected?'active':''}}\" data-id=\"${{s.id}}\"><strong>${{escape(s.name)}}</strong><div class=\"meta\">${{escape(s.story)}} · ${{s.floor_area_m2}} m² · ${{escape(s.thermal_zone)}}</div></li>`).join('')||'<li class=\"meta\">No matching spaces.</li>';list.querySelectorAll('[data-id]').forEach(el=>el.onclick=()=>select(el.dataset.id))}}
function escape(v){{return String(v).replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]))}} function select(id){{selected=id;let s=scene.spaces.find(x=>x.id===id);detail.style.display='block';detail.innerHTML=`<strong>${{escape(s.name)}}</strong><div class=\"meta\">${{escape(s.story)}}<br>${{escape(s.space_type)}}<br>Zone: ${{escape(s.thermal_zone)}}<br>${{s.floor_area_m2}} m² · ${{s.volume_m3}} m³<br>${{s.surface_count}} surfaces</div>`;renderList();draw()}}
const search=document.querySelector('#search'),storySelect=document.querySelector('#story'),sortSelect=document.querySelector('#sort');[search,storySelect,sortSelect].forEach(e=>e.oninput=renderList);document.querySelector('#sub').onchange=()=>{{renderList();draw()}};document.querySelector('#shade').onchange=()=>{{renderList();draw()}};document.querySelector('#showall').onclick=()=>{{selected=null;detail.style.display='none';renderList();draw()}};document.querySelector('#reset').onclick=()=>{{yaw=-.7;pitch=.55;zoom=1;draw()}};canvas.onpointerdown=e=>{{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId)}};canvas.onpointermove=e=>{{if(!drag)return;yaw+=(e.clientX-drag[0])*.01;pitch=Math.max(-1.4,Math.min(1.4,pitch+(e.clientY-drag[1])*.01));drag=[e.clientX,e.clientY];draw()}};canvas.onpointerup=()=>drag=null;canvas.onwheel=e=>{{e.preventDefault();zoom=Math.max(.35,Math.min(3,zoom*(e.deltaY>0?.9:1.1)));draw()}};
[...new Set(scene.spaces.map(s=>s.story))].sort().forEach(v=>storySelect.add(new Option(v,v)));document.querySelector('#summary').textContent=`${{scene.source_model}} · ${{scene.counts.spaces}} spaces · ${{scene.counts.stories}} stories · ${{scene.counts.faces}} faces${{scene.warnings.length?' · '+scene.warnings.length+' warnings':''}}`;renderList();resize();
</script><script>
// Keep the original renderer small, then layer exact face selection over it.
let selectedFaceId=null,faceDrag=null,visibleSpaceIds=new Set(scene.spaces.map(space=>space.id));
const baseDraw=draw;
canvas.tabIndex=0;
canvas.setAttribute('aria-label','Building geometry. Use the surface list to inspect individual surfaces.');
const surfacePanel=document.createElement('details');
surfacePanel.open=true;
surfacePanel.innerHTML='<summary>Surfaces</summary><ul id="surface-list" aria-label="Surfaces"></ul>';
document.querySelector('aside').appendChild(surfacePanel);
const surfaceList=document.querySelector('#surface-list');
const facesById=new Map(scene.faces.map(face=>[face.id,face]));
function renderSurfaceList(){{let faces=scene.faces.filter(face=>{{if(face.kind==='subsurface')return document.querySelector('#sub').checked;if(face.kind==='shading')return document.querySelector('#shade').checked;return true}}).sort((a,b)=>a.name.localeCompare(b.name));surfaceList.innerHTML=faces.map(face=>'<li><button type="button" class="space" data-face-id="'+face.id+'">'+escape(face.name)+'<span class="meta">'+escape(face.surface_type)+' · '+face.area_m2+' m²</span></button></li>').join('')||'<li class="meta">No visible surfaces.</li>';surfaceList.querySelectorAll('[data-face-id]').forEach(button=>button.onclick=()=>showSurface(facesById.get(button.dataset.faceId)));updateSurfaceList()}}
renderList=function(){{let items=filtered(),mode=sortSelect.value;items.sort((a,b)=>mode==='name'?a.name.localeCompare(b.name):mode==='story'?a.story.localeCompare(b.story)||a.name.localeCompare(b.name):b[mode==='area'?'floor_area_m2':'volume_m3']-a[mode==='area'?'floor_area_m2':'volume_m3']);list.innerHTML=items.map(space=>'<li><button type="button" class="space '+(space.id===selected?'active':'')+'" data-id="'+space.id+'" aria-pressed="'+(space.id===selected)+'"><strong>'+escape(space.name)+'</strong><span class="meta">'+escape(space.story)+' · '+space.floor_area_m2+' m² · '+escape(space.thermal_zone)+'</span></button></li>').join('')||'<li class="meta">No matching spaces.</li>';list.querySelectorAll('[data-id]').forEach(button=>button.onclick=()=>select(button.dataset.id))}};
const resetYaw=-.7,resetPitch=.65;
function camera(){{let c=Math.cos(pitch),s=Math.sin(pitch),co=Math.cos(yaw),si=Math.sin(yaw);return {{d:[si*c,-co*c,s],r:[co,si,0],u:[-si*s,co*s,c]}}}}
project=function(point){{let v=[point[0]-cx,point[1]-cy,point[2]-cz],cam=camera(),dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2],depth=span*3-dot(v,cam.d),scale=Math.min(canvas.clientWidth,canvas.clientHeight)/span*zoom;return [canvas.clientWidth/2+dot(v,cam.r)/depth*scale*span,canvas.clientHeight/2-dot(v,cam.u)/depth*scale*span,depth]}}
function polygonNormal(vertices){{let n=[0,0,0];for(let i=0;i<vertices.length;i++){{let a=vertices[i],b=vertices[(i+1)%vertices.length];n[0]+=(a[1]-b[1])*(a[2]+b[2]);n[1]+=(a[2]-b[2])*(a[0]+b[0]);n[2]+=(a[0]-b[0])*(a[1]+b[1])}}return n}}
function frontFacing(face){{let n=polygonNormal(face.vertices),d=camera().d;return n[0]*d[0]+n[1]*d[1]+n[2]*d[2]>1e-7}}
visible=function(face){{if(face.kind==='subsurface'&&!document.querySelector('#sub').checked)return false;if(face.kind==='shading'&&!document.querySelector('#shade').checked)return false;return (face.space_id==='__shading__'||visibleSpaceIds.has(face.space_id))&&(face.id===selectedFaceId||face.kind==='shading'||frontFacing(face))&&(!selected||face.space_id===selected||face.space_id==='__shading__')}}
function pointInPolygon(x,y,points){{let inside=false;for(let i=0,j=points.length-1;i<points.length;j=i++){{let a=points[i],b=points[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])inside=!inside}}return inside}}
function averageDepth(points){{return points.reduce((sum,point)=>sum+point[2],0)/points.length}}
function renderedFaces(){{return scene.faces.filter(face=>visible(face)).map(face=>({{face:face,points:face.vertices.map(project)}})).sort((a,b)=>averageDepth(b.points)-averageDepth(a.points))}}
draw=function(){{baseDraw();if(!selectedFaceId)return;let item=renderedFaces().find(item=>item.face.id===selectedFaceId);if(!item)return;let p=item.points;ctx.beginPath();ctx.moveTo(p[0][0],p[0][1]);for(let i=1;i<p.length;i++)ctx.lineTo(p[i][0],p[i][1]);ctx.closePath();ctx.fillStyle='#ef5b5b';ctx.globalAlpha=.92;ctx.fill();ctx.globalAlpha=1;ctx.strokeStyle='#8a1010';ctx.lineWidth=3;ctx.stroke()}}
function showSurface(face){{selected=null;selectedFaceId=face.id;let space=scene.spaces.find(space=>space.id===face.space_id),spaceName=space?space.name:'Shading geometry',story=space?space.story:'Unassigned';detail.style.display='block';detail.innerHTML='<strong>'+escape(face.name)+'</strong><div class="meta">Surface type: '+escape(face.surface_type)+'<br>Belongs to: '+escape(spaceName)+'<br>Floor: '+escape(story)+'<br>Area: '+face.area_m2+' m²<br>Boundary: '+escape(face.boundary_condition||'N/A')+'</div>';renderList();draw()}}
function updateSurfaceList(){{surfaceList.querySelectorAll('[data-face-id]').forEach(button=>{{let face=facesById.get(button.dataset.faceId);button.closest('li').hidden=face.space_id!=='__shading__'&&!visibleSpaceIds.has(face.space_id)}})}}
function clearHiddenFaceSelection(){{let face=selectedFaceId&&facesById.get(selectedFaceId);if(face&&!visible(face)){{selectedFaceId=null;detail.style.display='none'}}}}
function applySpaceFilter(){{visibleSpaceIds=new Set(filtered().map(space=>space.id));if(selected&&!visibleSpaceIds.has(selected)){{selected=null;selectedFaceId=null;detail.style.display='none'}}clearHiddenFaceSelection();renderList();updateSurfaceList();draw()}}
document.querySelector('#reset').onclick=()=>{{yaw=resetYaw;pitch=resetPitch;zoom=1;selected=null;selectedFaceId=null;detail.style.display='none';renderList();draw()}};
document.querySelector('#showall').onclick=()=>{{search.value='';storySelect.value='';selected=null;selectedFaceId=null;detail.style.display='none';applySpaceFilter()}};
document.querySelector('#sub').onchange=()=>{{renderSurfaceList();clearHiddenFaceSelection();draw()}};
document.querySelector('#shade').onchange=()=>{{renderSurfaceList();clearHiddenFaceSelection();draw()}};
search.oninput=applySpaceFilter;
storySelect.oninput=applySpaceFilter;
storySelect.onchange=applySpaceFilter;
sortSelect.oninput=renderList;
sortSelect.onchange=renderList;
list.addEventListener('click',()=>{{selectedFaceId=null}},{{capture:true}});
canvas.onpointerdown=event=>{{faceDrag={{x:event.clientX,y:event.clientY,moved:false}};canvas.setPointerCapture(event.pointerId)}};
canvas.onpointermove=event=>{{if(!faceDrag)return;let dx=event.clientX-faceDrag.x,dy=event.clientY-faceDrag.y;if(Math.abs(dx)+Math.abs(dy)>3)faceDrag.moved=true;yaw+=dx*.01;pitch=Math.max(-1.4,Math.min(1.4,pitch+dy*.01));faceDrag.x=event.clientX;faceDrag.y=event.clientY;draw()}};
canvas.onpointerup=event=>{{if(faceDrag&&!faceDrag.moved){{let rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,item=[...renderedFaces()].reverse().find(item=>pointInPolygon(x,y,item.points));if(item)showSurface(item.face)}}faceDrag=null}};
canvas.onkeydown=event=>{{let handled=true;if(event.key==='ArrowLeft')yaw-=.1;else if(event.key==='ArrowRight')yaw+=.1;else if(event.key==='ArrowUp')pitch=Math.min(1.4,pitch+.1);else if(event.key==='ArrowDown')pitch=Math.max(-1.4,pitch-.1);else if(event.key==='+'||event.key==='=')zoom=Math.min(3,zoom*1.1);else if(event.key==='-')zoom=Math.max(.35,zoom*.9);else if(event.key==='Home'){{yaw=resetYaw;pitch=resetPitch;zoom=1}}else handled=false;if(handled){{event.preventDefault();draw()}}}};
canvas.setAttribute('aria-label','Building geometry. Arrow keys orbit, plus and minus zoom, Home resets, and the surface list inspects individual surfaces.');
document.querySelector('#hint').textContent='Drag or arrow keys to orbit · scroll or +/- to zoom · Home resets · click any surface for details';
yaw=resetYaw;pitch=resetPitch;renderSurfaceList();applySpaceFilter();
</script></body></html>"""
