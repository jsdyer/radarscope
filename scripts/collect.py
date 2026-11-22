#!/usr/bin/env python3
"""Daily bounded Cloudflare Radar collection; all tokens remain in the environment."""
import argparse, hashlib, json, math, os, re, socket, ssl, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
ROOT=Path(__file__).resolve().parents[1]
BASE='https://api.cloudflare.com/client/v4'
COUNTRIES={'CA':'Canada','US':'United States','GB':'United Kingdom'}
MAX_BYTES=8_000_000
COVERAGE='Cloudflare-observed HTTP traffic: 7 days, hourly; Canada with optional US and GB comparisons. Each country is normalized separately to its own maximum. Canadian outage annotations: 30-day source window, at most 500.'
LICENCE='https://creativecommons.org/licenses/by-nc/4.0/'

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def iso(value,optional=False):
    if optional and value in (None,''):return None
    if not isinstance(value,str):raise ValueError('Source timestamp is not a string')
    try:date=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('Invalid source timestamp') from None
    if date.tzinfo is None:raise ValueError('Source timestamp must specify a timezone')
    return date.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
def safe_url(value):
    if not isinstance(value,str):return ''
    p=urlsplit(value)
    return value if p.scheme=='https' and p.hostname and not p.username and not p.password and not re.search(r'(?i)(?:key|token|secret)=',p.query) else ''
def number(value,high):
    if value is None or value=='':return None
    if isinstance(value,bool):raise ValueError('Boolean source measurement')
    try:n=float(value)
    except (TypeError,ValueError):raise ValueError('Non-numeric source measurement') from None
    if not math.isfinite(n) or not 0<=n<=high+1e-6:raise ValueError('Source measurement outside declared normalization')
    return n

def network_failure(exc):
    """Classify network exceptions without logging URLs, headers or exception text."""
    reason=exc.reason if isinstance(exc,URLError) else exc
    if isinstance(reason,(TimeoutError,socket.timeout)):return 'network timeout'
    if isinstance(reason,socket.gaierror):return 'DNS resolution failure'
    if isinstance(reason,ssl.SSLError):return 'TLS connection failure'
    if isinstance(reason,ConnectionResetError):return 'connection reset'
    if isinstance(reason,ConnectionRefusedError):return 'connection refused'
    if isinstance(reason,OSError):return 'network OS error'+(' errno='+str(reason.errno) if isinstance(reason.errno,int) else '')
    return 'network transport failure'

def request(path,params,token):
    url=BASE+path+'?'+urlencode(params)
    label=path+' ['+str(params.get('location','unspecified'))+']'
    last_failure='unknown failure'
    for attempt in range(3):
        delay=2**(attempt+1);started=time.monotonic()
        try:
            req=Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json','User-Agent':'RadarScope/1.0 (+https://coolcode.ca/radarscope/)'})
            with urlopen(req,timeout=45) as response:raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES:raise ValueError('Source response exceeds 8 MB bound')
            data=json.loads(raw)
            if not isinstance(data,dict) or data.get('success') is not True or not isinstance(data.get('result'),dict):raise ValueError('Cloudflare did not return a successful result for '+label)
            print('Cloudflare '+label+' succeeded in '+format(time.monotonic()-started,'.1f')+' seconds',flush=True)
            time.sleep(1)
            return data['result'],{'url':BASE+path,'parameters':params,'response_sha256':sha(raw)}
        except HTTPError as exc:
            last_failure='HTTP '+str(exc.code)
            if exc.code in (401,403):raise RuntimeError('Cloudflare '+label+' authentication/permission failure ('+last_failure+'); check CLOUDFLARE_RADAR_API_TOKEN permission, expiry and IP restrictions') from None
            if exc.code!=429 and exc.code<500:raise RuntimeError('Cloudflare '+label+' request rejected ('+last_failure+'); last good deployment retained') from None
            if exc.code==429:
                retry=exc.headers.get('Retry-After','') if exc.headers else ''
                if retry.isdigit():
                    if int(retry)>60:raise RuntimeError('Cloudflare '+label+' HTTP 429 requested Retry-After '+retry+' seconds; retry next collection') from None
                    delay=max(delay,int(retry))
        except (URLError,TimeoutError,OSError) as exc:last_failure=network_failure(exc)
        print('Cloudflare '+label+' attempt '+str(attempt+1)+'/3 failed: '+last_failure+' after '+format(time.monotonic()-started,'.1f')+' seconds'+('; retrying in '+str(delay)+' seconds' if attempt<2 else ''),flush=True)
        if attempt<2:time.sleep(delay)
    raise RuntimeError('Cloudflare '+label+' unavailable after three attempts: '+last_failure+'; last good deployment retained') from None

def series_object(result):
    # Named series keys are dynamic. Accept exactly one timestamp-bearing object for a one-country request.
    candidates=[v for k,v in result.items() if k!='meta' and isinstance(v,dict) and isinstance(v.get('timestamps'),list)]
    if len(candidates)!=1:raise ValueError('Expected one timestamp-bearing source series; received result fields: '+', '.join(sorted(str(k) for k in result)))
    return candidates[0]
def series_metadata(result,expected):
    meta=result.get('meta')
    if not isinstance(meta,dict) or meta.get('normalization')!=expected:raise ValueError('Unexpected source normalization; refusing to relabel values')
    if meta.get('aggInterval') not in ('ONE_HOUR','1h'):raise ValueError('Source did not return the requested hourly aggregation')
    ranges=meta.get('dateRange',[])
    if isinstance(ranges,dict):ranges=[ranges]
    if not isinstance(ranges,list) or len(ranges)!=1:raise ValueError('Expected exactly one source date range')
    period={'start':iso(ranges[0].get('startTime')),'end':iso(ranges[0].get('endTime'))}
    if period['start']>=period['end']:raise ValueError('Source date range is reversed')
    return {'normalization':expected,'last_updated':iso(meta.get('lastUpdated'),optional=True),'date_range':period,'aggregation':'1h','confidence':meta.get('confidenceInfo',{}),'source_units':meta.get('units',[])}
def aligned(timestamps,arrays,high):
    if not isinstance(timestamps,list) or not 2<=len(timestamps)<=192:raise ValueError('Expected 2–192 hourly points for the requested seven-day window')
    ts=[iso(t) for t in timestamps]
    if ts!=sorted(set(ts)):raise ValueError('Source timestamps are duplicated or unordered')
    for left,right in zip(ts,ts[1:]):
        delta=(datetime.fromisoformat(right.replace('Z','+00:00'))-datetime.fromisoformat(left.replace('Z','+00:00'))).total_seconds()
        if delta<3600 or delta%3600:raise ValueError('Source timestamps are not aligned to hourly intervals')
    parsed=[]
    for values in arrays:
        if not isinstance(values,list) or len(values)!=len(ts):raise ValueError('Series timestamp/value lengths differ')
        nums=[number(v,high) for v in values]
        if all(v is None for v in nums):raise ValueError('Source series contains no measurements')
        parsed.append(nums)
    # Explicitly insert absent hours as null. Missing observations must remain chart gaps.
    expanded_ts=[];expanded=[[] for _ in arrays]
    for i,stamp in enumerate(ts):
        if i:
            left=datetime.fromisoformat(ts[i-1].replace('Z','+00:00')).timestamp();right=datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()
            for epoch in range(int(left+3600),int(right),3600):
                expanded_ts.append(datetime.fromtimestamp(epoch,timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'))
                for values in expanded:values.append(None)
        expanded_ts.append(stamp)
        for values,nums in zip(expanded,parsed):values.append(nums[i])
    if len(expanded_ts)>192:raise ValueError('Source series time span exceeds seven-day bound')
    return expanded_ts,expanded

def normalize_traffic(result,country):
    metadata=series_metadata(result,'MIN0_MAX');series=series_object(result)
    ts,values=aligned(series['timestamps'],[series.get('values')],1)
    return {'country':country,'name':COUNTRIES[country],'timestamps':ts,'values':values[0],'unit':'normalized index','source_url':'https://radar.cloudflare.com/traffic/'+country.lower(),**metadata}
def normalize_ip(result,country):
    metadata=series_metadata(result,'PERCENTAGE');series=series_object(result)
    names={k.casefold():v for k,v in series.items()}
    if 'ipv4' not in names or 'ipv6' not in names:raise ValueError('Source IP series lacks IPv4/IPv6 categories; received fields: '+', '.join(sorted(names)))
    ts,values=aligned(series['timestamps'],[names['ipv4'],names['ipv6']],100)
    for v4,v6 in zip(*values):
        if v4 is not None and v6 is not None and abs(v4+v6-100)>0.2:raise ValueError('Source IP shares do not total 100%')
    return {'country':country,'name':COUNTRIES[country],'timestamps':ts,'ipv4':values[0],'ipv6':values[1],'unit':'percent','source_url':'https://radar.cloudflare.com/adoption-and-usage/'+country.lower(),**metadata}
def normalize_outage(row):
    if not isinstance(row,dict) or not isinstance(row.get('id'),(str,int)) or not str(row['id']).strip():raise ValueError('Source annotation has no identity')
    locations=row.get('locations')
    if not isinstance(locations,list) or not all(isinstance(v,str) for v in locations):raise ValueError('Source annotation countries are invalid')
    if 'CA' not in locations:raise ValueError('Source returned an annotation outside requested Canadian scope')
    asns=row.get('asns',[])
    if not isinstance(asns,list) or not all(isinstance(v,(int,str)) and str(v).isdigit() for v in asns):raise ValueError('Source annotation ASNs are invalid')
    start=iso(row.get('startDate'));end=iso(row.get('endDate'),optional=True)
    if end and end<start:raise ValueError('Source outage end precedes start')
    outage=row.get('outage') or {}
    if not isinstance(outage,dict):raise ValueError('Source outage details are invalid')
    return {'id':str(row['id']),'start_at':start,'end_at':end,'description':str(row.get('description') or ''),'event_type':str(row.get('eventType') or 'UNSPECIFIED'),
      'countries':locations,'asns':[str(v) for v in asns],'scope':str(row.get('scope') or ''),'cause':str(outage.get('outageCause') or 'UNSPECIFIED'),
      'outage_type':str(outage.get('outageType') or 'UNSPECIFIED'),'source_url':safe_url(row.get('linkedUrl')) or 'https://radar.cloudflare.com/outage-center/ca',
      'radar_url':'https://radar.cloudflare.com/outage-center/ca'}

def collect(token):
    if not token:raise ValueError('CLOUDFLARE_RADAR_API_TOKEN is required; no data was replaced')
    traffic=[];ips=[];sources=[];warnings=[]
    for country in COUNTRIES:
        print('Collecting Cloudflare HTTP and IP series for '+country)
        params={'location':country,'dateRange':'7d','aggInterval':'1h','normalization':'MIN0_MAX','format':'JSON'}
        result,source=request('/radar/http/timeseries',params,token);item=normalize_traffic(result,country);traffic.append(item);source['metadata']={k:item[k] for k in ('normalization','date_range','last_updated','aggregation','confidence')};sources.append(source)
        params={**params,'normalization':'PERCENTAGE'}
        result,source=request('/radar/http/timeseries_groups/IP_VERSION',params,token);item=normalize_ip(result,country);ips.append(item);source['metadata']={k:item[k] for k in ('normalization','date_range','last_updated','aggregation','confidence')};sources.append(source)
    outages={};received=0;truncated=False
    for offset in range(0,500,100):
        params={'location':'CA','dateRange':'30d','limit':100,'offset':offset,'format':'JSON'}
        result,source=request('/radar/annotations/outages',params,token);rows=result.get('annotations')
        if not isinstance(rows,list) or len(rows)>100:raise ValueError('Invalid bounded outage annotation response')
        source['received']=len(rows);sources.append(source);received+=len(rows)
        for row in rows:
            parsed=normalize_outage(row)
            if parsed['id'] in outages:raise ValueError('Source outage pagination repeated an identity')
            outages[parsed['id']]=parsed
        if len(rows)<100:break
        if offset==400:truncated=True;warnings.append('Outage annotations reached the 500-record cap; this capture may omit additional source events.')
    return {'traffic':traffic,'ip_versions':ips,'outages':sorted(outages.values(),key=lambda r:r['start_at'],reverse=True),
      'sources':sources,'warnings':warnings,'outage_coverage':{'country':'CA','date_range':'30d','received':received,'limit':500,'truncated':truncated}}

def validate(payload):
    if not isinstance(payload,dict) or payload.get('schema')!=1 or payload.get('tool')!='radarscope' or payload.get('status') not in ('ready','pending'):raise ValueError('Invalid Radar Scope dataset')
    for key in ('traffic','ip_versions','outages'):
        if not isinstance(payload.get(key),list):raise ValueError('Missing dataset collection '+key)
    if payload['status']=='pending':
        if payload['traffic'] or payload['ip_versions'] or payload['outages']:raise ValueError('Pending data cannot contain observations')
        return payload
    if {r.get('country') for r in payload['traffic']}!=set(COUNTRIES) or len(payload['traffic'])!=3:raise ValueError('Incomplete traffic country coverage')
    if {r.get('country') for r in payload['ip_versions']}!=set(COUNTRIES) or len(payload['ip_versions'])!=3:raise ValueError('Incomplete IP country coverage')
    for rows,keys,normal,high in [(payload['traffic'],['values'],'MIN0_MAX',1),(payload['ip_versions'],['ipv4','ipv6'],'PERCENTAGE',100)]:
        for row in rows:
            if row.get('normalization')!=normal:raise ValueError('Invalid saved normalization')
            aligned(row.get('timestamps'),[row.get(k) for k in keys],high)
    ids=[r.get('id') for r in payload['outages']]
    if len(ids)>500 or len(set(ids))!=len(ids):raise ValueError('Invalid saved outage identities')
    for row in payload['outages']:
        iso(row.get('start_at'));iso(row.get('end_at'),optional=True)
        if 'CA' not in row.get('countries',[]) or not safe_url(row.get('source_url')):raise ValueError('Invalid saved outage attribution')
    encode(payload);return payload

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp');temp.write_bytes(encode(value));temp.replace(path)
def save(collected,root=ROOT):
    stamp=now();folder=root/'data';folder.mkdir(exist_ok=True)
    previous=json.loads((folder/'current.json').read_text()) if (folder/'current.json').exists() else {}
    history=json.loads((folder/'history.json').read_text()) if (folder/'history.json').exists() else []
    content_sha=sha(encode({k:collected[k] for k in ('traffic','ip_versions','outages','outage_coverage')}))
    payload=validate({'schema':1,'tool':'radarscope','status':'ready','captured_at':stamp,'checked_at':stamp,'coverage':COVERAGE,'licence_url':LICENCE,'attribution':'Cloudflare Radar; normalized and presented by CoolCode','content_sha256':content_sha,**collected})
    if previous.get('content_sha256')==content_sha:
        payload['captured_at']=previous['captured_at'];payload['snapshot']=previous['snapshot']
    else:
        filename='archive/'+stamp[:7]+'/'+stamp.replace('-','').replace(':','')+'-'+content_sha[:12]+'.json';payload['snapshot']=filename
        raw=encode(payload);path=root/filename;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:f.write(raw)
        history.append({'captured_at':stamp,'file':filename,'sha256':sha(raw),'outage_count':len(payload['outages']),'countries':list(COUNTRIES),'point_count':sum(len(r['timestamps']) for r in payload['traffic'])})
    atomic(folder/'current.json',payload);atomic(folder/'history.json',history)
    atomic(folder/'index.json',{'schema':1,'tool':'radarscope','status':'ready','source':'Cloudflare Radar','source_url':'https://radar.cloudflare.com/ca','licence_url':LICENCE,
      'captured_at':payload['captured_at'],'checked_at':stamp,'record_count':sum(len(r['timestamps']) for r in payload['traffic']),
      'outage_count':len(payload['outages']),'snapshot_count':len(history),'coverage':COVERAGE,'latest':'current.json','history':'history.json','warnings':payload['warnings']})
    print(f'Saved 3 country series, {len(payload["outages"])} Canadian annotations and {len(history)} immutable snapshots')
    return payload

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--if-missing',action='store_true');args=parser.parse_args()
    path=ROOT/'data/current.json';baseline=validate(json.loads(path.read_text())) if path.exists() else None
    if args.if_missing and baseline and baseline['status']=='ready':print('Using saved Cloudflare snapshot');return
    token=os.environ.get('CLOUDFLARE_RADAR_API_TOKEN','').strip()
    if args.if_missing and not token and baseline and baseline['status']=='pending':print('No Actions token yet; retaining explicit pending state');return
    save(collect(token))
if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,OSError) as exc:raise SystemExit(str(exc)) from None
