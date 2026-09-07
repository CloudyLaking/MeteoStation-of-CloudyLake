"""Synoptic charts using the same visual language as the public website.

The same physical fields and rendering rules apply to every map domain.
No temperature/rainfall inference is made from colour alone; the returned
reading notes state which quantities and diagnostic candidates are shown.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.collections import LineCollection
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import Arc, Circle
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import Bbox
from scipy.ndimage import maximum_filter, minimum_filter

from .analysis import smooth_field, detect_height_axes, detect_surface_fronts
from .fields import WeatherGrid
from .models import CycloneMarker

FONT_SIZE = 17
PAPER = '#fbfbf8'
INK = '#24343a'
INK_SOFT = '#707876'
TEAL = '#126e68'
ORANGE = '#d9a083'
VIOLET = '#746489'
BRICK = '#a5574f'
HALO = [pe.withStroke(linewidth=2.2, foreground='white', alpha=.94)]


@dataclass
class Chart:
    figure: object
    bounds: dict
    markers: list
    features: list
    notes: list[str]
    recipe: dict


def pressure_mask(grid, level):
    """True where a pressure level lies above the surface, including a buffer."""
    surface = grid.fields.get('surface_pressure_hpa')
    if surface is None:
        return np.ones((len(grid.latitude), len(grid.longitude)), dtype=bool)
    return np.isfinite(surface) & (surface >= level + 5)


def filtered(grid, name, level=None, sigma=1.4):
    values = grid.fields[name]
    mask = pressure_mask(grid, level) if level else np.isfinite(values)
    # Reapply after smoothing: a NaN-aware filter otherwise fills underground cells.
    result = smooth_field(np.where(mask, values, np.nan), sigma_gridpoints=sigma)
    return np.where(mask, result, np.nan)


def closed_centres(grid, domain, level=None, maximum=6):
    """Select closed extrema using eight surrounding directions, in either hemisphere."""
    name = f'geopotential_height_{level}_gpm' if level else 'mslp_hpa'
    values = filtered(grid, name, level, sigma=2)
    eligible = pressure_mask(grid, level or 850)
    spacing = max(abs(float(np.median(np.diff(grid.latitude)))), .1)
    radius = max(3, round(5 / spacing))
    window = radius * 2 + 1
    prominence = 12 if level else 1.5
    selected = []
    for kind, sign in [('low-pressure', 1), ('high-pressure', -1)]:
        signed = values * sign
        extrema = minimum_filter(np.where(np.isfinite(signed), signed, np.inf), size=window)
        candidates = np.argwhere(eligible & np.isfinite(signed) & (signed == extrema))
        ranked = []
        for y, x in candidates:
            if y < radius or x < radius or y >= values.shape[0]-radius or x >= values.shape[1]-radius:
                continue
            if abs(grid.latitude[y]) < 12:
                continue
            ring = np.array([signed[y+dy*radius, x+dx*radius] for dx,dy in
                [(-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)]])
            if not np.isfinite(ring).all():
                continue
            depth = float(np.min(ring) - signed[y,x])
            if depth >= prominence:
                ranked.append((depth, y, x))
        for depth, y, x in sorted(ranked, reverse=True):
            lat, lon = float(grid.latitude[y]), float(grid.longitude[x])
            if any(np.hypot((lon-m.longitude)*np.cos(np.radians(lat)), lat-m.latitude) < 6 for m in selected):
                continue
            selected.append(CycloneMarker(id=f'auto-{kind}-{len(selected)+1}', kind=kind,
                valid_at=grid.valid_at, latitude=lat, longitude=lon,
                central_pressure_hpa=round(float(values[y,x])) if not level else None,
                central_height_dam=round(float(values[y,x])/10) if level else None,
                source='IFS closed-extremum diagnostic; eight-direction enclosure', confidence='medium'))
            if sum(m.kind == kind for m in selected) >= maximum:
                break
    return selected


def colour_recipe(grid, layer):
    if layer == 'composite':
        anomaly = 'temperature_850_climatology_c' in grid.fields
        values = filtered(grid, 'temperature_850_c', 850)
        if anomaly:
            values = np.where(pressure_mask(grid,850),smooth_field(values-grid.fields['temperature_850_climatology_c'],sigma_gridpoints=2.2),np.nan)
            return values, [-16,-12,-8,-4,-2,2,4,8,12,16], ['#827296','#a598b3','#c8bed2','#e6e0ea','#ffffff','#f4e9e1','#e8cdbb','#ce9a82','#ad6457'], '850-hPa T anomaly (°C)', '850 hPa 温度距平；中性区间 ±2°C 留白', 500
        return values, [-40,-20,-10,0,10,20,25,30,40], ['#8d80a0','#b8afc8','#e0dce8','#f4f2f4','#ffffff','#f2e3d7','#dcb79e','#b77562'], '850-hPa Temperature (°C)', '850 hPa 实际温度（本区域无气候距平资料）', 500
    if layer == '850':
        return filtered(grid,'relative_humidity_850_pct',850), [0,40,60,70,80,90,100], ['#ffffff','#f4f0eb','#e4eeea','#c3dcd5','#8fbfb4','#559e91'], '850-hPa RH (%)', '850 hPa 湿度与风；高湿不等于正在降雨', 850
    if layer == '500':
        if 'geopotential_height_500_climatology_gpm' in grid.fields:
            values = filtered(grid,'geopotential_height_500_gpm',500) - grid.fields['geopotential_height_500_climatology_gpm']
            return values, [-400,-240,-160,-80,-40,40,80,160,240,400], ['#827296','#a598b3','#c8bed2','#e6e0ea','#ffffff','#f4e9e1','#e8cdbb','#ce9a82','#ad6457'], '500-hPa Z anomaly (gpm)', '500 hPa 高度距平、等高线与槽脊诊断', 500
        values = filtered(grid,'relative_humidity_500_pct',500)
        return values, [0,40,60,70,80,90,100], ['#ffffff','#f4f0eb','#e4eeea','#c3dcd5','#8fbfb4','#559e91'], '500-hPa RH (%)', '500 hPa 湿度与环流（本区域无气候距平资料）', 500
    if layer == '200':
        u,v=filtered(grid,'wind_u_200_ms',200),filtered(grid,'wind_v_200_ms',200)
        return np.hypot(u,v), [0,20,30,40,50,60,80,100], ['#ffffff','#f1f5f3','#d3e6e0','#a5ccc0','#e6cbb0','#c9977e','#897593'], '200-hPa Wind (m/s)', '200 hPa 急流；30 m/s 以下弱化显示', 200
    if 'precipitation_accumulation_mm' in grid.fields and grid.metadata.get('precipitation'):
        hours=grid.metadata['precipitation']['hours']
        return grid.fields['precipitation_accumulation_mm'], [0,.1,1,5,10,25,50,100,200], ['#ffffff','#f1f6f3','#d7e9e0','#adcfc1','#6eac97','#37907e','#897799','#a96159'], f'{hours:g}-h Precipitation (mm)', f'有效时刻前 {hours:g} 小时模式累计降水；不是雷达或雨量站实况。', None
    return filtered(grid,'temperature_2m_c'), [-60,-40,-20,-10,0,10,20,30,35,40,50], ['#817296','#a89db7','#d0c8d9','#e6e1ec','#f3f1f3','#ffffff','#f7f2ec','#ecd9c7','#d4ad93','#b67563'], '2-m Temperature (°C)', '地面温度、海平面气压与十米风', None


def draw_chart(grid, *, layer, domain, font_path=None, cyclones=(), base_map=None, boundary=None, supplied_features=None):
    from .render import draw_south_china_sea_inset
    global_map = domain.east-domain.west > 180
    font = FontProperties(fname=str(font_path), size=FONT_SIZE) if font_path and font_path.is_file() else FontProperties(size=FONT_SIZE)
    if font_path and font_path.is_file():
        fontManager.addfont(str(font_path))
    with plt.rc_context({'font.family':font.get_name(), 'font.size':FONT_SIZE}):
        ratio=(domain.east-domain.west)*np.cos(np.radians((domain.north+domain.south)/2))/(domain.north-domain.south)
        regional_width=max(10.5,min(16,ratio*10*.79/.8))
        fig = plt.figure(figsize=(18,9) if global_map else (regional_width,10), facecolor=PAPER)
        ax = fig.add_axes([.055,.105,.80,.79])
        ax.set(xlim=(domain.west,domain.east), ylim=(domain.south,domain.north), facecolor='white')
        ax.set_aspect(1 if global_map else 1/max(.35,np.cos(np.radians((domain.north+domain.south)/2))), adjustable='box')
        fig.canvas.draw()
        lon,lat=np.meshgrid(grid.longitude,grid.latitude)
        values, levels, colours, colour_label, recipe_note, level = colour_recipe(grid,layer)
        cmap=ListedColormap(colours)
        extend='max' if any(name in colour_label for name in ('RH','Wind','Precipitation')) else 'both'
        shaded=ax.contourf(lon,lat,values,levels=levels,cmap=cmap,norm=BoundaryNorm(levels,cmap.N),extend=extend,zorder=1)
        terrain_level = 850 if layer == 'composite' else level
        mask = pressure_mask(grid, terrain_level) if terrain_level else pressure_mask(grid,850)
        if terrain_level and not mask.all():
            # Background fills masked corner cells too; a second masked
            # contourf produces white cracks at the terrain boundary.
            ax.set_facecolor('#f0eeeb')
        height_name = f'geopotential_height_{level}_gpm' if level else 'mslp_hpa'
        height=filtered(grid,height_name,level,sigma=2)
        if not level:
            height=np.where(mask,height,np.nan)
        interval = (30 if level == 850 else 40 if level == 500 else 120) if level else 4
        if global_map: interval *= 2
        finite=height[np.isfinite(height)]
        contour_labels=[]
        if finite.size:
            steps=np.arange(np.floor(finite.min()/interval)*interval,np.ceil(finite.max()/interval)*interval+.1,interval)
            contours=ax.contour(lon,lat,height,levels=steps,colors=INK,linewidths=1.1,zorder=4)
            contour_labels=ax.clabel(contours,inline=False,fontsize=FONT_SIZE,fmt=(lambda v:f'{v/10:.0f}') if level else '%d')
            for text in contour_labels: text.set_path_effects(HALO)
        # Sparse, uniform wind field. Barb increments are explicitly m/s.
        wind_level=850 if layer=='composite' else level
        suffix=str(wind_level) if wind_level else '10m'
        u=filtered(grid,f'wind_u_{suffix}_ms',wind_level,sigma=.5)
        v=filtered(grid,f'wind_v_{suffix}_ms',wind_level,sigma=.5)
        ys=max(1,len(grid.latitude)//(15 if not global_map else 18))
        xs=max(1,len(grid.longitude)//(25 if not global_map else 46))
        sel=np.s_[::ys,::xs]
        visible=np.isfinite(u[sel]) & np.isfinite(v[sel]) & (np.hypot(u[sel],v[sel])>=2.5)
        ax.barbs(lon[sel][visible],lat[sel][visible],u[sel][visible],v[sel][visible],length=4.3,linewidth=.55,color='#6b8983',alpha=.8,barb_increments={'half':2.5,'full':5,'flag':25},flip_barb=lat[sel][visible]<0,zorder=3)
        if base_map is not None:
            ax.imshow(base_map.boundaries,extent=base_map.extent,origin='upper',zorder=5,alpha=.7)
            ax.set_aspect(1 if global_map else 1/max(.35,np.cos(np.radians((domain.north+domain.south)/2))), adjustable='box')
        coast_path=Path(__file__).resolve().parents[2]/('config/maps/coastline-110m.json' if global_map else 'config/maps/coastline-50m.json')
        if coast_path.is_file():
            coast_lines=[]
            for coordinates in json.loads(coast_path.read_text(encoding='utf8'))['lines']:
                p=np.asarray(coordinates,dtype=float)
                p[:,0]=(p[:,0]-domain.west)%360+domain.west
                for segment in np.split(p,np.flatnonzero(np.abs(np.diff(p[:,0]))>180)+1):
                    if len(segment)>1:coast_lines.append(segment)
            ax.add_collection(LineCollection(coast_lines,colors='#718a80',linewidths=.55,alpha=.8,zorder=5))
        if boundary is not None:
            ax.add_collection(LineCollection(boundary.province_lines,colors='#899d95',linewidths=.4,alpha=.72,zorder=5))
            ax.add_collection(LineCollection(boundary.boundary_lines,colors='#607c72',linewidths=.75,zorder=5))
            if domain.west==70 and domain.east==145 and domain.south==15 and domain.north==60:
                draw_south_china_sea_inset(ax,boundary,font=font)
        # Existing front/axis methods are regional diagnostics, not global truth.
        features=list(supplied_features or [])
        if supplied_features is None and not global_map:
            features=detect_surface_fronts(grid,domain=domain) if layer=='surface' else detect_height_axes(grid,domain=domain,pressure_hpa=500) if layer in ('composite','500') else []
        features=[f for f in features if not any(np.min(np.hypot(np.asarray(f.coordinates)[:,0]-t.longitude,np.asarray(f.coordinates)[:,1]-t.latitude))<5 for t in cyclones)]
        features=sorted(features,key=lambda f:f.score,reverse=True)[:(3 if layer=='surface' else 4)]
        feature_boxes=[]
        for feature in features:
            p=np.asarray(feature.coordinates)
            pixels=ax.transData.transform(p)
            for a,b in zip(pixels[:-1],pixels[1:]):
                feature_boxes.append(Bbox.from_extents(min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])).padded(7 if 'front' in feature.kind else 3))
            color=VIOLET if feature.kind=='trough-axis' else '#b58350' if feature.kind=='ridge-axis' else TEAL if feature.kind=='cold-front' else BRICK
            line,=ax.plot(p[:,0],p[:,1],color=color,lw=2.0,ls=(0,(5,3)) if 'axis' in feature.kind else '-',zorder=6)
            line.set_path_effects([pe.withStroke(linewidth=3.2,foreground='white',alpha=.8)])
            if 'front' in feature.kind:
                from metpy.plots import ColdFront, WarmFront, StationaryFront
                cls={'cold-front':ColdFront,'warm-front':WarmFront,'stationary-front':StationaryFront}[feature.kind]
                front_colours={'colors':(BRICK,TEAL)} if feature.kind=='stationary-front' else {'color':color}
                line.set_path_effects([cls(size=6,spacing=3,**front_colours)])
        markers=[]
        for m in cyclones:
            x=((m.longitude-domain.west)%360)+domain.west
            if domain.west <= x <= domain.east and domain.south <= m.latitude <= domain.north:
                markers.append(m.model_copy(update={'longitude':x}))
        centres=closed_centres(grid,domain,level,maximum=8 if global_map else 3)
        centres=[m for m in centres if not any(np.hypot((m.longitude-t.longitude)*np.cos(np.radians(m.latitude)),m.latitude-t.latitude)<5 for t in markers)]
        fig.canvas.draw()
        renderer=fig.canvas.get_renderer()
        occupied=[a.get_window_extent(renderer).padded(3) for a in ax.child_axes]+feature_boxes
        annotation_texts=[]
        for m in [*markers,*centres]:
            if m.kind=='tropical':
                symbol=DrawingArea(24,24,0,0)
                symbol.add_artist(Circle((12,12),2.4,fill=False,color=BRICK,lw=1.7))
                symbol.add_artist(Arc((9,12),15,10,theta1=145,theta2=348,color=BRICK,lw=1.8))
                symbol.add_artist(Arc((15,12),15,10,theta1=-35,theta2=168,color=BRICK,lw=1.8))
                artist=AnnotationBbox(symbol,(m.longitude,m.latitude),frameon=False,zorder=9)
                ax.add_artist(artist)
                fig.canvas.draw()
                occupied.append(artist.get_window_extent(fig.canvas.get_renderer()).padded(2))
                label=m.id; color=BRICK
            else:
                label='H' if m.kind=='high-pressure' else 'L';color='#b58350' if label=='H' else VIOLET
                value=m.central_height_dam if level else m.central_pressure_hpa
                label+=f' {value:.0f}'
            text=ax.annotate(label,(m.longitude,m.latitude),xytext=(0,18 if m.kind=='tropical' else 0),textcoords='offset points',ha='center',va='center',fontsize=FONT_SIZE,fontproperties=font,color=color,zorder=10,path_effects=HALO)
            candidate_positions=([(0,18),(28,0),(-28,0),(0,-18),(0,35)] if m.kind=='tropical' else [(0,0),(0,18),(0,-18),(35,0),(-35,0)])+[(35,25),(-35,25),(35,-25),(-35,-25)]
            frame=ax.get_window_extent(renderer)
            best=None
            for dx,dy in candidate_positions:
                text.set_position((dx,dy)); box=text.get_window_extent(renderer).padded(3)
                score=sum(box.overlaps(b) for b in occupied)*100 + (0 if frame.contains(box.x0,box.y0) and frame.contains(box.x1,box.y1) else 1000)+abs(dx)*.01+abs(dy)*.01
                if best is None or score<best[0]:best=(score,dx,dy,box)
            text.set_position(best[1:3]);occupied.append(best[3]);annotation_texts.append(text)
            if m.kind!='tropical' and best[1:3]!=(0,0):
                # A shifted label must retain the actual diagnosed centre.
                origin=ax.transData.transform((m.longitude,m.latitude))
                end=origin+np.asarray(best[1:3])*fig.dpi/72*.55
                endpoint=ax.transData.inverted().transform(end)
                ax.plot([m.longitude,endpoint[0]],[m.latitude,endpoint[1]],color=color,lw=.65,zorder=8)
                ax.plot(m.longitude,m.latitude,marker='+',color=color,ms=4,mew=.8,zorder=9)
        # Suppress only real intersections, never a broad circle around storms.
        frame=ax.get_window_extent(renderer)
        for text in contour_labels:
            box=text.get_window_extent(renderer).padded(2)
            if not (frame.contains(box.x0,box.y0) and frame.contains(box.x1,box.y1)) or any(box.overlaps(b) for b in occupied):text.set_visible(False)
            else:occupied.append(box)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=8,integer=True))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=7,integer=True))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x,_:f'{abs((x+180)%360-180):g}°'+('W' if (x+180)%360-180<0 else 'E')))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda y,_:f'{abs(y):g}°'+('S' if y<0 else 'N')))
        ax.tick_params(labelsize=FONT_SIZE,colors=INK,length=2,width=.5)
        ax.grid(alpha=.10,color=INK,lw=.45,ls='-')
        for spine in ax.spines.values():spine.set(color='#8fa39d',linewidth=.65)
        fig.canvas.draw(); pos=ax.get_position()
        cax=fig.add_axes([pos.x1+.025,pos.y0,.016,pos.height])
        ticks=([-16,-8,-4,0,4,8,16] if layer=='composite' and 'anomaly' in colour_label else [0,60,80,100] if 'RH' in colour_label else levels[::2])
        if layer=='500' and 'anomaly' in colour_label: ticks=[-400,-160,-80,0,80,160,400]
        if layer=='200': ticks=[0,30,50,80,100]
        bar=fig.colorbar(shaded,cax=cax,ticks=ticks)
        bar.set_label(colour_label,fontsize=FONT_SIZE,color=INK,labelpad=10)
        bar.ax.tick_params(labelsize=FONT_SIZE,colors=INK,length=2)
        bar.outline.set_linewidth(.4)
        titles={'composite':'COMPOSITE / 850 T + WIND / 500 Z','surface':'SURFACE / 2-m T / MSLP / 10-m WIND','850':'850 hPa / MOISTURE / HEIGHT / WIND','500':'500 hPa / CIRCULATION','200':'200 hPa / JET STREAM'}
        if layer=='surface' and grid.metadata.get('precipitation'): titles['surface']='SURFACE | Rain · MSLP · 10-m Wind'
        if layer=='surface' and grid.metadata.get('precipitation'): titles['surface']='SURFACE / ACCUMULATED RAIN / MSLP / 10-m WIND'
        title_font=font.copy();title_font.set_size(18);title_font.set_weight(700)
        meta_font=font.copy();meta_font.set_size(13)
        fig.add_artist(plt.Line2D([pos.x0,pos.x1+.041],[pos.y1+.063,pos.y1+.063],transform=fig.transFigure,color='#c9d3cf',lw=.8))
        fig.add_artist(plt.Line2D([pos.x0,pos.x0+.055],[pos.y1+.063,pos.y1+.063],transform=fig.transFigure,color=ORANGE,lw=3))
        fig.text(pos.x0,pos.y1+.018,titles[layer],ha='left',va='bottom',fontproperties=title_font,color=INK)
        fig.text(pos.x1,pos.y1+.019,f'VALID / {grid.valid_at:%Y-%m-%d %H:%M UTC}',ha='right',va='bottom',fontproperties=meta_font,color=INK_SOFT)
        init=grid.metadata.get('initialized_at')
        init_text=f" · INIT {str(init)[5:16].replace('T',' ')}Z +{grid.metadata.get('forecast_step_hours',0)}h" if init else ''
        display_text=' · DISPLAY 1°' if global_map else ''
        fig.add_artist(plt.Line2D([pos.x0,pos.x1+.041],[.079,.079],transform=fig.transFigure,color='#c9d3cf',lw=.7))
        fig.text(pos.x0,.035,'ECMWF OPEN DATA / IFS 0.25°'+display_text+init_text+' · meteostation.top',fontproperties=meta_font,color=INK_SOFT)
        notes=['模式天气场来源：ECMWF Open Data IFS；有效时刻、起报时刻与预报时效见图内。',recipe_note,'风羽：半划 2.5 m/s、长划 5 m/s、旗形 25 m/s；高空高度线为十位势米。']
        if 'RH' in colour_label: notes.append('湿度保留模式原值，寒冷环境可能超过 100%；色条顶端延伸表示超出 100%，不强制截断。')
        if global_map: notes.append('全球采用 1° 网格展示，原始资料为 IFS 0.25°；极区与小尺度系统需使用区域产品。')
        if 'anomaly' in colour_label: notes.append('距平基准：ERA5 1991—2020 年同月平均；不是逐日气候态。')
        if terrain_level:notes.append('浅灰区域为该气压面位于地表以下，未绘制地下场。' if 'surface_pressure_hpa' in grid.fields else '缺少地面气压，无法核验气压面地形遮罩。')
        for m in markers:
            details=[f'{m.id} {m.name or ""}'.strip(),f'{m.valid_at:%m-%d %H:%M} UTC']
            if m.central_pressure_hpa is not None:details.append(f'{m.central_pressure_hpa:g} hPa')
            if m.maximum_wind_kt is not None:details.append(f'{m.maximum_wind_kt:g} kt')
            source_upper=(m.source or '').upper()
            agency='NHC/CPHC' if ('NHC' in source_upper and 'CPHC' in source_upper) else 'CPHC' if 'CPHC' in source_upper else 'NHC' if 'NHC' in source_upper else 'JTWC'
            mirror='NRL 备用镜像' if 'NRL' in m.source else 'UCAR 镜像'
            notes.append(f'热带气旋（{agency}，经 {mirror}）：'+' · '.join(details))
        if centres or features:notes.append('H/L、槽脊与锋面为模式场自动诊断候选，不代表人工分析或官方预警。')
        notes.extend(signal_notes(grid,layer,values))
        return Chart(fig,{'left':pos.x0,'right':pos.x1,'bottom':pos.y0,'top':pos.y1},[*markers,*centres],features,notes,{'shading':colour_label,'levels':levels,'wind_unit':'m/s','font_pt':FONT_SIZE,'terrain_masked':bool(terrain_level and 'surface_pressure_hpa' in grid.fields),'version':'3.0'})


def signal_notes(grid,layer,values):
    """Describe measured extrema, without pretending humidity is observed rainfall."""
    if not np.isfinite(values).any():return []
    y,x=np.unravel_index(np.nanargmax(values),values.shape)
    longitude=(grid.longitude[x]+180)%360-180
    where=f'{abs(grid.latitude[y]):.1f}°'+('N' if grid.latitude[y]>=0 else 'S')+f'，{abs(longitude):.1f}°'+('E' if longitude>=0 else 'W')
    if layer=='200':return [f'急流核心参考：{where}，200 hPa 风速 {values[y,x]:.0f} m/s。']
    if layer=='surface':
        if grid.metadata.get('precipitation') and 'precipitation_accumulation_mm' in grid.fields:
            return [f'图域模式累计降水最大格点：{values[y,x]:.1f} mm（{where}）；局地峰值不能代表整个地区。']
        return [f'图域最高二米温度：{values[y,x]:.1f}°C（{where}，模式值）。']
    if layer=='850':
        mask=pressure_mask(grid,850); u=grid.fields['wind_u_850_ms'];v=grid.fields['wind_v_850_ms']
        signal=mask & (values>=80) & (np.hypot(u,v)>=12)
        if signal.any():
            yy,xx=np.where(signal)
            return [f'高湿与较强低层风重合区：纬度 {grid.latitude[yy].min():.0f}—{grid.latitude[yy].max():.0f}°；需结合降水或雷达判断实际降雨。']
    return []
