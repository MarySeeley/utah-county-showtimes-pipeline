"""Generate a self-contained, interactive HTML view from the DuckDB warehouse."""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    print("DuckDB is missing. Install dependencies with: python -m pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)


PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "data" / "warehouse" / "utah_county_showtimes.duckdb"
RAW_DIR = PROJECT_DIR / "data" / "raw"
OUTPUT_PATH = PROJECT_DIR / "data" / "visualization" / "showtimes_dashboard.html"
RUN_LOG_PATH = PROJECT_DIR / "data" / "logs" / "pipeline_runs.jsonl"


def read_rows(con, table: str) -> list[dict]:
    result = con.execute(f'SELECT * FROM "{table}"')
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def read_query_rows(con, query: str) -> list[dict]:
    result = con.execute(query)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def read_collection_dates() -> list[str]:
    if not RUN_LOG_PATH.exists():
        return []
    dates = []
    with RUN_LOG_PATH.open(encoding="utf-8") as log_file:
        for line in log_file:
            try:
                run = json.loads(line)
            except json.JSONDecodeError:
                continue
            if run.get("status") == "success" and run.get("run_started_at_utc"):
                dates.append(run["run_started_at_utc"])
    return dates


def build_payload() -> dict:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Warehouse not found: {DB_PATH}. Run the pipeline first.")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return {
            "showtimes": read_rows(con, "showtimes_current"),
            "changes": read_rows(con, "showtime_changes"),
            "collections": read_collection_dates(),
            "cinemaLocations": read_query_rows(
                con,
                "SELECT DISTINCT cinema_id, cinema_name, city "
                "FROM showtime_observations",
            ),
            "generatedAt": __import__("datetime").datetime.now().astimezone().isoformat(timespec="minutes"),
        }
    finally:
        con.close()


PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Utah County Showtimes</title>
<style>
:root{--ink:#17233a;--muted:#66738a;--paper:#f4f6fb;--card:#fff;--line:#e3e8f1;--blue:#536dfe;--cyan:#23b9b0;--orange:#f0a34a;--shadow:0 12px 35px #1c31500c}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.shell{max-width:1320px;margin:auto;padding:34px 28px 52px}.hero{display:flex;align-items:flex-end;justify-content:space-between;gap:22px;margin-bottom:25px}.eyebrow{color:var(--blue);font-weight:750;letter-spacing:.12em;text-transform:uppercase;font-size:11px}.hero h1{font-size:clamp(30px,4vw,46px);letter-spacing:-.04em;line-height:1.08;margin:9px 0 8px}.hero p{color:var(--muted);margin:0}.stamp{font-size:12px;color:var(--muted);text-align:right;white-space:nowrap}
.filters{display:flex;flex-wrap:wrap;gap:13px;align-items:end;background:var(--card);border:1px solid var(--line);padding:17px;border-radius:16px;box-shadow:var(--shadow);margin-bottom:17px}.filter{display:grid;gap:6px;min-width:180px}.filter label{font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}select{appearance:none;border:1px solid var(--line);background:#fff;border-radius:9px;padding:10px 34px 10px 12px;color:var(--ink);font:inherit;background-image:linear-gradient(45deg,transparent 50%,#748099 50%),linear-gradient(135deg,#748099 50%,transparent 50%);background-position:calc(100% - 17px) 15px,calc(100% - 12px) 15px;background-size:5px 5px;background-repeat:no-repeat}.reset{border:0;background:#edf0ff;color:#394bd0;border-radius:9px;padding:11px 14px;font:inherit;font-weight:700;cursor:pointer}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:17px}.metric,.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)}.metric{padding:18px 19px}.metric .label{font-size:12px;color:var(--muted);font-weight:650}.metric .value{font-size:29px;letter-spacing:-.04em;font-weight:780;margin-top:6px}.metric .hint{font-size:11px;color:var(--muted);margin-top:3px}
.grid{display:grid;grid-template-columns:1.12fr .88fr;gap:16px;margin-bottom:16px}.panel{padding:20px;min-width:0}.panel h2{font-size:16px;margin:0 0 4px;letter-spacing:-.02em}.sub{font-size:12px;color:var(--muted);margin-bottom:16px}.bars{display:grid;gap:10px}.barrow{display:grid;grid-template-columns:minmax(95px,155px) 1fr 36px;gap:10px;align-items:center;font-size:12px}.barlabel{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#45536b}.track{height:10px;background:#eff2f8;border-radius:99px;overflow:hidden}.fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--blue),#8e9bff)}.barrow:nth-child(3n+2) .fill{background:linear-gradient(90deg,var(--cyan),#8adbd4)}.barrow:nth-child(3n) .fill{background:linear-gradient(90deg,var(--orange),#ffd39d)}.barvalue{text-align:right;font-variant-numeric:tabular-nums;font-weight:700;color:#34425b}
.timeline{display:grid;grid-template-columns:repeat(12,minmax(12px,1fr));align-items:end;gap:7px;height:130px;padding:0 4px 20px;border-bottom:1px solid var(--line)}.daycol{height:100%;display:flex;align-items:end;position:relative}.daybar{width:100%;min-height:3px;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,#46c9bb,#239b9b)}.daylabel{position:absolute;top:calc(100% + 5px);left:50%;transform:translateX(-50%);font-size:9px;color:var(--muted);white-space:nowrap}.legend{display:flex;gap:14px;font-size:11px;color:var(--muted);margin-top:12px}.dot{width:8px;height:8px;display:inline-block;border-radius:50%;margin-right:5px;background:var(--cyan)}
.activity{display:grid;grid-template-columns:repeat(14,minmax(14px,1fr));align-items:end;gap:6px;height:150px;padding:0 3px 22px;border-bottom:1px solid var(--line)}.activity-day{height:100%;display:flex;align-items:end;position:relative}.activity-bar{width:100%;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,#536dfe,#8391ff)}.activity-day.zero .activity-bar{height:3px!important;background:#23b9b0}.activity-day.missed .activity-bar{display:none}.activity-day.missed:after{content:"";position:absolute;bottom:0;left:0;right:0;border-bottom:2px dotted #c4cad6}.activity-day.future:after{content:"";position:absolute;bottom:0;left:12%;right:12%;height:70%;border:1px dashed #cbd2fa;border-radius:5px 5px 2px 2px;background:#f6f7ff}.activity-label{position:absolute;top:calc(100% + 5px);left:50%;transform:translateX(-50%);font-size:9px;color:var(--muted);white-space:nowrap}.activity-day.today .activity-label{color:#394bd0;font-weight:800}.activity-legend{display:flex;flex-wrap:wrap;gap:10px 16px;font-size:11px;color:var(--muted);margin-top:12px}.legend-chip{display:flex;align-items:center;gap:6px}.legend-mark{width:10px;height:10px;border-radius:3px;background:#657afe}.legend-mark.zero{height:3px;border-radius:2px;background:#23b9b0}.legend-mark.missed{height:0;background:transparent;border-bottom:2px dotted #aab2c2;border-radius:0}.legend-mark.future{background:#f6f7ff;border:1px dashed #aeb8f1}
.chart-wrap{width:100%;overflow-x:auto}.movie-chart{display:block;width:100%;min-width:850px;height:auto}.chart-grid{stroke:#e7ebf2;stroke-width:1}.chart-axis{fill:#758197;font-size:11px}.chart-line{fill:none;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.chart-point{stroke:#fff;stroke-width:2}.movie-legend{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:10px}.movie-legend-item{display:flex;align-items:center;gap:7px;font-size:11px;color:#45536b}.movie-swatch{width:17px;height:3px;border-radius:3px}.movie-legend-count{color:var(--muted)}
.tablewrap{overflow:auto;max-height:560px;border:1px solid var(--line);border-radius:11px}.shows{width:100%;border-collapse:collapse;min-width:720px}.shows th{position:sticky;top:0;background:#f8f9fc;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);padding:11px 12px}.shows td{padding:11px 12px;border-top:1px solid #edf0f5;font-size:12px;vertical-align:middle}.shows tr:hover td{background:#fafbff}.time{font-weight:750;font-variant-numeric:tabular-nums;white-space:nowrap}.title{font-size:13px;font-weight:700}.venue{color:var(--muted)}.tag{display:inline-block;border-radius:99px;background:#eef1ff;color:#4657d5;padding:3px 8px;font-size:10px;font-weight:700;margin:2px}.ticket a{color:#4657d5;font-weight:700;text-decoration:none}.ticket a:hover{text-decoration:underline}.notice{margin-top:15px;background:#fff8eb;border:1px solid #f3dfbd;color:#73521c;border-radius:12px;padding:13px 15px;font-size:12px}.empty{padding:24px;text-align:center;color:var(--muted)}.footer{color:var(--muted);font-size:11px;text-align:center;margin-top:22px}
@media(max-width:850px){.grid{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.shell{padding:22px 14px 38px}.hero{display:block}.stamp{text-align:left;margin-top:12px}.metrics{gap:9px}.metric{padding:14px}.metric .value{font-size:24px}.filter{min-width:140px;flex:1}}
</style></head><body><main class="shell">
<header class="hero"><div><div class="eyebrow">Utah County Â· Movie guide</div><h1>Find your next showtime.</h1><p>Explore upcoming screenings across Utah County.</p></div><div class="stamp" id="updated"></div></header>
<section class="filters"><div class="filter"><label for="date">Show date</label><select id="date"></select></div><div class="filter"><label for="city">City</label><select id="city"></select></div><div class="filter"><label for="cinema">Theater</label><select id="cinema"></select></div><button class="reset" id="reset">Reset filters</button></section>
<div class="notice" style="margin:0 0 17px">Showtimes are limited to today through the next 6 days. The API may have incomplete listings beyond this 7-day window while theaters publish their schedules.</div>
<section class="metrics" id="metrics"></section>
<section class="grid"><article class="panel"><h2>Showtimes by hour</h2><div class="sub">When screenings begin for this selection</div><div class="bars" id="hours"></div></article><article class="panel"><h2>Most scheduled movies</h2><div class="sub">Titles ranked by number of screenings</div><div class="bars" id="movies"></div></article></section>
<section class="grid"><article class="panel"><h2>Busiest theaters</h2><div class="sub">Upcoming screenings by theater</div><div class="bars" id="theaters"></div></article><article class="panel"><h2>Screen formats and versions</h2><div class="sub">Source-provided format and language/version tags</div><div class="bars" id="formats"></div><div class="notice" style="margin-top:18px">Movie ratings and ticket prices are not included because this source does not provide them. Format and version labels are shown as supplied by the API.</div></article></section>
<section class="panel" style="margin-bottom:16px"><h2>Movie showtimes by date</h2><div class="sub">Showtime counts from the selected date through the end of the current 7-day window. City and theater filters apply.</div><div class="chart-wrap" id="movie-history"></div><div class="movie-legend" id="movie-legend"></div><div class="sub" id="movie-history-note" style="margin:12px 0 0"></div></section>
<section class="grid"><article class="panel"><h2>Theaters with most schedule changes</h2><div class="sub">Source-reported reschedules and removals. First-seen imports are excluded so the initial load does not skew the ranking.</div><div class="bars" id="change-theaters"></div><div class="sub" id="change-note" style="margin:14px 0 0"></div></article><article class="panel"><h2>Changes as the history grows</h2><div class="sub">Actual reschedules and removals by collection day. The next seven days fill in as your pipeline runs.</div><div class="activity" id="change-activity"></div><div class="activity-legend"><span class="legend-chip"><i class="legend-mark"></i>Changes recorded</span><span class="legend-chip"><i class="legend-mark zero"></i>Collected, no changes</span><span class="legend-chip"><i class="legend-mark missed"></i>No saved collection</span><span class="legend-chip"><i class="legend-mark future"></i>Upcoming day</span></div><div class="sub" id="activity-note" style="margin:12px 0 0"></div></article></section>
<section class="panel"><h2>Upcoming screenings</h2><div class="sub" id="table-sub"></div><div class="tablewrap"><table class="shows"><thead><tr><th>Time</th><th>Movie</th><th>Theater</th><th>City</th><th>Format / version</th><th>Booking</th></tr></thead><tbody id="show-list"></tbody></table></div><div class="sub" style="margin:12px 2px 0">Cinemark links open the theaterâ€™s official showtime page; choose the listed movie and time there. AMC links go directly to ticketing.</div></section>
<div class="footer">Local dashboard generated from the projectâ€™s DuckDB warehouse. Data reflects the theater APIâ€™s latest collected schedule.</div></main>
<script>
const DATA=__DATA__;
const uniq=a=>[...new Set(a.filter(v=>v))].sort((a,b)=>a.localeCompare(b));
const dateOf=s=>(s||'').slice(0,10), timeOf=s=>(s||'').slice(11,16);
const localDay=s=>{const d=new Date(s);return Number.isNaN(d.getTime())?'':`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
const addDays=(day,n)=>{const d=new Date(`${day}T12:00:00`);d.setDate(d.getDate()+n);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
const today=localDay(new Date()),lastShowtimeDay=addDays(today,6);
const windowShowtimes=DATA.showtimes.filter(x=>{const d=dateOf(x.starts_at_local);return d>=today&&d<=lastShowtimeDay});
const allDates=uniq(windowShowtimes.map(x=>dateOf(x.starts_at_local))).sort();
const dateSel=document.querySelector('#date'),citySel=document.querySelector('#city'),cinemaSel=document.querySelector('#cinema');
function options(el,values,allLabel,selected,labelFn){el.innerHTML='';const all=document.createElement('option');all.value='';all.textContent=allLabel;el.append(all);for(const v of values){const o=document.createElement('option');o.value=v;o.textContent=labelFn?labelFn(v):v;el.append(o)}if(selected!==undefined)el.value=selected}
options(dateSel,allDates,'All dates in 7-day window',allDates[0]||'');options(citySel,uniq(windowShowtimes.map(x=>x.city)),'All cities','');
document.querySelector('#updated').textContent='Warehouse snapshot Â· '+new Date(DATA.generatedAt).toLocaleString();
function selection(){return windowShowtimes.filter(x=>(!dateSel.value||dateOf(x.starts_at_local)===dateSel.value)&&(!citySel.value||x.city===citySel.value)&&(!cinemaSel.value||x.cinema_name===cinemaSel.value))}
function updateDates(){const counts=new Map();for(const r of windowShowtimes){if((!citySel.value||r.city===citySel.value)&&(!cinemaSel.value||r.cinema_name===cinemaSel.value)){const d=dateOf(r.starts_at_local);counts.set(d,(counts.get(d)||0)+1)}}const available=[...counts.keys()].sort();const current=dateSel.value;const next=available.includes(current)?current:(available[0]||'');options(dateSel,available,'All dates in 7-day window',next,d=>`${new Date(d+'T12:00:00').toLocaleDateString(undefined,{month:'short',day:'numeric',weekday:'short'})} Â· ${counts.get(d)} shows`)}
function drawBars(target,items){const el=document.querySelector(target);if(!items.length){el.innerHTML='<div class="empty">No data for this selection.</div>';return}const max=Math.max(...items.map(x=>x[1]),1);el.innerHTML=items.map(([name,value])=>`<div class="barrow"><div class="barlabel" title="${esc(name)}">${esc(name)}</div><div class="track"><div class="fill" style="width:${Math.max(value/max*100,2)}%"></div></div><div class="barvalue">${value}</div></div>`).join('')}
function countBy(rows,key){const m=new Map();for(const r of rows){const v=r[key]||'Not specified';m.set(v,(m.get(v)||0)+1)}return [...m].sort((a,b)=>b[1]-a[1])}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function ticketLink(r){const pages={'Cinemark Provo 16':'https://mobile.cinemark.com/theatres/ut-provo/cinemark-provo-16','Cinemark University Mall':'https://mobile.cinemark.com/theatres/ut-orem/cinemark-university-mall-and-screenx'};if(pages[r.cinema_name])return {url:pages[r.cinema_name],label:'Cinemark showtimes â†—'};return r.booking_url?{url:r.booking_url,label:'Buy tickets â†—'}:null}
function render(){const rows=selection();document.querySelector('#metrics').innerHTML=[[rows.length,'Upcoming screenings','Across the selected date and places'],[uniq(rows.map(x=>x.movie_title)).length,'Movies','Distinct titles scheduled'],[uniq(rows.map(x=>x.cinema_name)).length,'Theaters','Venues with screenings'],[uniq(rows.map(x=>x.city)).length,'Cities','Cities represented']].map(([v,l,h])=>`<article class="metric"><div class="label">${l}</div><div class="value">${v.toLocaleString()}</div><div class="hint">${h}</div></article>`).join('');
const hourCounts=new Map();for(const r of rows){const h=Number(timeOf(r.starts_at_local).slice(0,2));if(Number.isFinite(h))hourCounts.set(h,(hourCounts.get(h)||0)+1)}drawBars('#hours',[...hourCounts].sort((a,b)=>a[0]-b[0]).map(([h,n])=>[`${String(h%12||12).padStart(2,'0')}:00 ${h<12?'AM':'PM'}`,n]));
drawBars('#movies',countBy(rows,'movie_title').slice(0,8));drawBars('#theaters',countBy(rows,'cinema_name').slice(0,8));
const fmt=countBy(rows,'format').map(([k,v])=>[`Format: ${k}`,v]);const ver=countBy(rows,'screening_version').map(([k,v])=>[`Version: ${k}`,v]);drawBars('#formats',[...fmt,...ver].slice(0,10));
const sorted=[...rows].sort((a,b)=>(a.starts_at_local||'').localeCompare(b.starts_at_local||''));document.querySelector('#table-sub').textContent=`${sorted.length.toLocaleString()} screenings Â· sorted by local start time`;
const body=document.querySelector('#show-list');body.innerHTML=sorted.map(r=>{const link=ticketLink(r);return `<tr><td class="time">${esc(timeOf(r.starts_at_local))}</td><td><div class="title">${esc(r.movie_title||'Untitled')}</div>${r.tmdb_id?`<div class="venue">TMDB ID ${esc(r.tmdb_id)}</div>`:''}</td><td>${esc(r.cinema_name||'')}</td><td>${esc(r.city||'')}</td><td>${r.format?`<span class="tag">${esc(r.format)}</span>`:''}${r.screening_version?`<span class="tag">${esc(r.screening_version)}</span>`:''}</td><td class="ticket">${link?`<a href="${esc(link.url)}" target="_blank" rel="noopener noreferrer">${esc(link.label)}</a>`:'â€”'}</td></tr>`}).join('')||'<tr><td colspan="6" class="empty">No upcoming screenings match these filters.</td></tr>';
drawMovieDateRange();drawChangeInsights();}
function drawMovieDateRange(){
const firstDate=dateSel.value||today,chart=document.querySelector('#movie-history'),legend=document.querySelector('#movie-legend');
if(!firstDate){chart.innerHTML='<div class="empty">No upcoming showtime dates are available.</div>';legend.innerHTML='';document.querySelector('#movie-history-note').textContent='';return}
const chartStart=firstDate<today?today:firstDate,chartDayCount=Math.max(1,Math.round((new Date(`${lastShowtimeDay}T12:00:00`)-new Date(`${chartStart}T12:00:00`))/86400000)+1),dates=Array.from({length:chartDayCount},(_,i)=>addDays(chartStart,i));
const inScope=r=>(!citySel.value||r.city===citySel.value)&&(!cinemaSel.value||r.cinema_name===cinemaSel.value),normalizedTitle=r=>String(r.movie_title||'Unknown title').trim().replace(/\s+/g,' ').toLocaleLowerCase();
const tmdbByTitle=new Map();for(const r of windowShowtimes){if(!inScope(r)||!r.tmdb_id)continue;const title=normalizedTitle(r);if(!tmdbByTitle.has(title))tmdbByTitle.set(title,new Set());tmdbByTitle.get(title).add(String(r.tmdb_id))}
const movieCounts=new Map(),titles=new Map();for(const r of windowShowtimes){const date=dateOf(r.starts_at_local);if(!dates.includes(date)||!inScope(r))continue;const titleKey=normalizedTitle(r),known=tmdbByTitle.get(titleKey),key=r.tmdb_id?`tmdb:${r.tmdb_id}`:(known?.size===1?`tmdb:${[...known][0]}`:`title:${titleKey}`);titles.set(key,r.movie_title||'Unknown title');if(!movieCounts.has(key))movieCounts.set(key,Array(dates.length).fill(0));movieCounts.get(key)[dates.indexOf(date)]++}
const ranked=[...movieCounts].map(([key,values])=>[key,values.reduce((a,b)=>a+b,0)]).sort((a,b)=>b[1]-a[1]).slice(0,10);
if(!ranked.length){chart.innerHTML='<div class="empty">No upcoming showtimes for this 7-day window and selection.</div>';legend.innerHTML='';document.querySelector('#movie-history-note').textContent='Try another start date, city, or theater.';return}
const colors=['#536dfe','#23a89e','#ef9b3f','#d85e88','#7862c8','#537e9b','#be6bd5','#70a83b','#cf7044','#378bb8'],left=58,right=22,topPad=18,bottom=58,width=1000,height=440,plotWidth=width-left-right,plotHeight=height-topPad-bottom;
const maxDaily=Math.max(...ranked.map(([key])=>Math.max(...movieCounts.get(key))),1),step=Math.max(1,Math.ceil(maxDaily/4)),yMax=Math.max(step,Math.ceil(maxDaily/step)*step);
let svg=`<svg class="movie-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Daily movie showtimes within the next seven days">`;
for(let i=0;i<=4;i++){const value=yMax*i/4,y=topPad+plotHeight*(1-i/4);svg+=`<line class="chart-grid" x1="${left}" y1="${y}" x2="${width-right}" y2="${y}"/><text class="chart-axis" x="${left-10}" y="${y+4}" text-anchor="end">${Math.round(value)}</text>`}
const xAt=i=>dates.length===1?left+plotWidth/2:left+i*plotWidth/(dates.length-1),yAt=value=>topPad+plotHeight*(1-value/yMax);
for(let m=0;m<ranked.length;m++){const key=ranked[m][0],values=movieCounts.get(key),color=colors[m%colors.length],path=values.map((v,i)=>`${i?'L':'M'} ${xAt(i)} ${yAt(v)}`).join(' ');svg+=`<path class="chart-line" d="${path}" stroke="${color}"/>`;for(let i=0;i<values.length;i++){const label=new Date(`${dates[i]}T12:00:00`).toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'});svg+=`<circle class="chart-point" cx="${xAt(i)}" cy="${yAt(values[i])}" r="4" fill="${color}"><title>${esc(titles.get(key)||'Unknown title')}: ${values[i]} showings on ${esc(label)}</title></circle>`}}
for(let i=0;i<dates.length;i++){const label=new Date(`${dates[i]}T12:00:00`).toLocaleDateString(undefined,{weekday:'short',month:'numeric',day:'numeric'});svg+=`<text class="chart-axis" x="${xAt(i)}" y="${height-19}" text-anchor="middle">${esc(label)}</text>`}svg+='</svg>';chart.innerHTML=svg;
legend.innerHTML=ranked.map(([key,total],i)=>`<span class="movie-legend-item"><i class="movie-swatch" style="background:${colors[i%colors.length]}"></i>${esc(titles.get(key)||'Unknown title')} <span class="movie-legend-count">Window total ${total.toLocaleString()}</span></span>`).join('');
const format=d=>new Date(`${d}T12:00:00`).toLocaleDateString(undefined,{month:'long',day:'numeric',year:'numeric'});document.querySelector('#movie-history-note').textContent=`Y-axis: showings on each date. Window: ${format(dates[0])} through ${format(dates[dates.length-1])}. Same-title listings with one shared TMDB match are combined.`
}
function scopedChangeEvents(){return DATA.changes.filter(e=>{if(e.event_type!=='changed'&&e.event_type!=='removed')return false;const loc=DATA.cinemaLocations.find(x=>x.cinema_id===e.cinema_id);return (!citySel.value||loc?.city===citySel.value)&&(!cinemaSel.value||e.cinema_name===cinemaSel.value)})}
function drawChangeInsights(){const events=scopedChangeEvents();const theaterCounts=new Map();for(const e of events){const loc=DATA.cinemaLocations.find(x=>x.cinema_id===e.cinema_id);const label=`${loc?.city||'City unknown'} Â· ${e.cinema_name||'Unknown theater'}`;theaterCounts.set(label,(theaterCounts.get(label)||0)+1)}drawBars('#change-theaters',[...theaterCounts].sort((a,b)=>b[1]-a[1]).slice(0,8));document.querySelector('#change-note').textContent=`${events.length.toLocaleString()} reschedules or removals in the selected area. First-seen records are not counted.`;
const today=localDay(DATA.generatedAt);const collectionDays=new Set(DATA.collections.map(localDay).filter(Boolean));const counts=new Map();for(const e of events){const d=localDay(e.event_observed_at_utc);if(d)counts.set(d,(counts.get(d)||0)+1)}const dates=Array.from({length:14},(_,i)=>addDays(today,i-6));const max=Math.max(...dates.map(d=>counts.get(d)||0),1);const html=dates.map(d=>{const n=counts.get(d)||0;const isFuture=d>today;const hasRun=collectionDays.has(d);const cls=[d===today?'today':'',isFuture?'future':(hasRun?(n?'has-changes':'zero'):'missed')].filter(Boolean).join(' ');const state=isFuture?'upcoming collection day':(hasRun?`${n} reschedules/removals`:'no saved collection');const height=n?Math.max(n/max*100,4):'3';return `<div class="activity-day ${cls}" title="${esc(d)}: ${esc(state)}"><div class="activity-bar" style="height:${height}%"></div><div class="activity-label">${d.slice(5)}</div></div>`}).join('');document.querySelector('#change-activity').innerHTML=html;const windowDays=new Set(dates.filter(d=>collectionDays.has(d)));const windowEvents=dates.reduce((sum,d)=>sum+(counts.get(d)||0),0);document.querySelector('#activity-note').textContent=`${windowEvents.toLocaleString()} reschedules/removals across ${windowDays.size} collected day${windowDays.size===1?'':'s'} in this view. Future dates are placeholders; the chart updates after each pipeline run.`}
function updateCinemas(){const current=cinemaSel.value;const list=uniq(windowShowtimes.filter(x=>!citySel.value||x.city===citySel.value).map(x=>x.cinema_name));options(cinemaSel,list,'All theaters',list.includes(current)?current:'')}
dateSel.addEventListener('change',render);citySel.addEventListener('change',()=>{updateCinemas();updateDates();render()});cinemaSel.addEventListener('change',()=>{updateDates();render()});document.querySelector('#reset').addEventListener('click',()=>{citySel.value='';updateCinemas();cinemaSel.value='';dateSel.value=allDates[0]||'';updateDates();render()});updateCinemas();updateDates();render();
</script></body></html>'''


def main() -> int:
    try:
        payload = build_payload()
        encoded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        page = PAGE.replace("__DATA__", encoded)
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(page, encoding="utf-8")
    except Exception as exc:
        print(f"Dashboard generation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Dashboard written: {OUTPUT_PATH.relative_to(PROJECT_DIR)}")
    print(f"Upcoming showtimes included: {len(payload['showtimes']):,}")
    print(f"Recorded change events included: {len(payload['changes']):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
