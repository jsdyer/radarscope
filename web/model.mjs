export const COUNTRIES={CA:'Canada',US:'United States',GB:'United Kingdom'};
export const COLORS={CA:'#e9a24a',US:'#79b7bd',GB:'#b4a4d0',ipv4:'#79b7bd',ipv6:'#e9a24a'};
export function safeURL(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:null;}catch{return null;}}
function seriesCheck(series,keys,limit){
  if(!COUNTRIES[series.country]||!Array.isArray(series.timestamps)||series.timestamps.length>192)throw Error('Invalid country or timeline.');
  if(series.timestamps.some((t,i)=>typeof t!=='string'||!Number.isFinite(Date.parse(t))||(i>0&&Date.parse(t)<=Date.parse(series.timestamps[i-1]))))throw Error('Timeline timestamps must be valid and strictly increasing.');
  for(const key of keys){const values=series[key];if(!Array.isArray(values)||values.length!==series.timestamps.length||values.some(v=>v!==null&&(typeof v!=='number'||!Number.isFinite(v)||v<0||v>limit)))throw Error('Timeline values have invalid units, length or range.');}
}
export function validate(data){
  if(!data||data.schema!==1||!['ready','pending'].includes(data.status)||!Array.isArray(data.traffic)||!Array.isArray(data.ip_versions)||!Array.isArray(data.outages)||data.traffic.length>3||data.ip_versions.length>3||data.outages.length>500)throw Error('Choose a Radar Scope JSON snapshot.');
  if(data.tool!=='radarscope')throw Error('This snapshot belongs to another tool.');
  if(data.status==='pending'&&(data.traffic.length||data.ip_versions.length||data.outages.length))throw Error('Pending snapshots cannot contain measurements.');
  if(data.sources!==undefined&&(!Array.isArray(data.sources)||data.sources.length>200||data.sources.some(s=>!s||typeof s!=='object')))throw Error('Invalid source metadata.');
  if(data.warnings!==undefined&&(!Array.isArray(data.warnings)||data.warnings.length>200))throw Error('Invalid coverage warnings.');
  if(data.status==='ready'&&(!data.traffic.length||!data.ip_versions.length))throw Error('Ready snapshots need traffic and IP-version series.');
  if(data.status==='ready'&&!Number.isFinite(Date.parse(data.captured_at)))throw Error('A ready snapshot needs a valid capture timestamp.');
  for(const [type,keys,max] of [['traffic',['values'],1],['ip_versions',['ipv4','ipv6'],100]]){const seen=new Set();for(const s of data[type]){seriesCheck(s,keys,max);if(seen.has(s.country))throw Error('Duplicate country series.');seen.add(s.country);if(s.normalization!==(type==='traffic'?'MIN0_MAX':'PERCENTAGE'))throw Error('The normalization method is not supported.');}}
  for(const s of data.ip_versions)for(let i=0;i<s.timestamps.length;i++)if(s.ipv4[i]!==null&&s.ipv6[i]!==null&&Math.abs(s.ipv4[i]+s.ipv6[i]-100)>.2)throw Error('IP shares must total 100 percent.');
  const ids=new Set();for(const e of data.outages){if(typeof e.id!=='string'||!e.id||ids.has(e.id)||typeof e.description!=='string'||!Number.isFinite(Date.parse(e.start_at))||!Array.isArray(e.countries)||!Array.isArray(e.asns)||!safeURL(e.source_url))throw Error('An outage has invalid identity, date or provenance.');if(e.end_at&&(!Number.isFinite(Date.parse(e.end_at))||Date.parse(e.end_at)<Date.parse(e.start_at)))throw Error('Invalid outage end date.');ids.add(e.id);}
  return data;
}
export function latestPair(series,key='values'){if(!series)return null;for(let i=series.timestamps.length-1;i>=0;i--)if(series[key][i]!==null)return{timestamp:series.timestamps[i],value:series[key][i],index:i};return null;}
export function trimSeries(series,keys,hours='all'){
  if(hours==='all'||!series.timestamps.length)return series;const end=Date.parse(series.timestamps.at(-1));const first=series.timestamps.findIndex(t=>Date.parse(t)>=end-Number(hours)*3600000);return{...series,timestamps:series.timestamps.slice(first),...Object.fromEntries(keys.map(k=>[k,series[k].slice(first)]))};
}
export function chartSegments(timestamps,values,{width=900,height=250,pad=42,yMax=1,xMin,xMax}={}){
  const times=timestamps.map(Date.parse);const low=xMin??Math.min(...times),high=xMax??Math.max(...times);const groups=[];let current=[];const gaps=[];const intervals=times.slice(1).map((t,i)=>t-times[i]).filter(v=>v>0).sort((a,b)=>a-b);const step=intervals.length?intervals[Math.floor((intervals.length-1)/2)]:Infinity;
  for(let i=0;i<times.length;i++){const value=values[i];if(i>0&&times[i]-times[i-1]>step*1.8&&current.length){groups.push(current);current=[];}if(value===null){if(current.length)groups.push(current);current=[];gaps.push(i);continue;}const point={x:pad+(times[i]-low)/Math.max(1,high-low)*(width-pad*2),y:height-pad-value/yMax*(height-pad*2),value,timestamp:timestamps[i]};current.push(point);}
  if(current.length)groups.push(current);return{groups,gaps};
}
export function filterOutages(data,{country='CA',query='',type='all'}={}){const q=query.trim().toLowerCase();return data.outages.filter(e=>(country==='all'||e.countries.includes(country))&&(type==='all'||e.event_type===type)&&[e.description,e.cause,e.scope,...e.asns].join(' ').toLowerCase().includes(q)).sort((a,b)=>Date.parse(b.start_at)-Date.parse(a.start_at));}
export function csvCell(value){const s=String(value??'');return '"'+s.replaceAll('"','""').replace(/^[=+@-]/,"'$&")+'"';}
function csv(rows){return rows.map(row=>row.map(csvCell).join(',')).join('\r\n');}
export function trafficCSV(series,captured){return csv([['country','timestamp_utc','normalized_index','normalization','unit','source','captured_at'],...series.flatMap(s=>s.timestamps.map((t,i)=>[s.country,t,s.values[i],s.normalization,'normalized index (0–1)',s.source_url||'https://radar.cloudflare.com/',captured]))]);}
export function ipCSV(series,captured){return csv([['country','timestamp_utc','ipv4_percent','ipv6_percent','normalization','source','captured_at'],...series.timestamps.map((t,i)=>[series.country,t,series.ipv4[i],series.ipv6[i],series.normalization,series.source_url||'https://radar.cloudflare.com/',captured])]);}
export function outageCSV(events,captured){return csv([['event_id','start_utc','end_utc','countries','asns','event_type','description','scope','cause','outage_type','source','captured_at'],...events.map(e=>[e.id,e.start_at,e.end_at,e.countries.join(';'),e.asns.join(';'),e.event_type,e.description,e.scope,e.cause,e.outage_type,e.source_url,captured])]);}
export function parseSnapshot(text){if(text.length>8_000_000)throw Error('Choose a JSON file smaller than 8 MB.');return validate(JSON.parse(text));}
