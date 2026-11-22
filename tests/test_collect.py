import copy,io,json,socket,ssl,sys,tempfile,unittest
from contextlib import redirect_stdout
from urllib.error import HTTPError,URLError
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect
TS=['2026-11-20T00:00:00Z','2026-11-20T01:00:00Z','2026-11-20T02:00:00Z']
def result(ip=False):
 return {'custom_named_series':{'timestamps':TS,**({'IPv4':['65','60',None],'IPv6':['35','40',None]} if ip else {'values':['0.5','1',None]})},'meta':{'normalization':'PERCENTAGE' if ip else 'MIN0_MAX','aggInterval':'ONE_HOUR','dateRange':[{'startTime':TS[0],'endTime':'2026-11-20T03:00:00Z'}],'lastUpdated':'2026-11-21T00:00:00Z','units':[{'name':'*','value':'requests'}]}}
def collected():
 return {'traffic':[collect.normalize_traffic(result(),c) for c in collect.COUNTRIES],'ip_versions':[collect.normalize_ip(result(True),c) for c in collect.COUNTRIES],'outages':[],'sources':[{'url':collect.BASE+'/radar/http/timeseries'}],'warnings':[],'outage_coverage':{'country':'CA','date_range':'30d','received':0,'limit':500,'truncated':False}}
class CollectorTests(unittest.TestCase):
 def test_dynamic_series_preserves_actual_values_and_nulls(self):
  row=collect.normalize_traffic(result(),'CA');self.assertEqual(row['values'],[.5,1,None]);self.assertEqual(row['normalization'],'MIN0_MAX');self.assertEqual(row['timestamps'],TS)
 def test_missing_hours_are_explicit_gaps_not_zero(self):
  data=result();data['custom_named_series']={'timestamps':[TS[0],TS[2]],'values':['0.5','1']}
  row=collect.normalize_traffic(data,'CA');self.assertEqual(row['timestamps'],TS);self.assertEqual(row['values'],[.5,None,1])
 def test_normalization_wrong_aggregation_and_missing_series_rejected(self):
  for mutation in ['normalization','aggInterval','missing']:
   data=result()
   if mutation=='missing':del data['custom_named_series']
   else:data['meta'][mutation]='wrong'
   with self.assertRaises(ValueError):collect.normalize_traffic(data,'CA')
 def test_nonfinite_boolean_misaligned_and_unsorted_values_rejected(self):
  for values in [[True,.2,.3],[float('nan'),.2,.3],['2',.2,.3],[.2]]:
   data=result();data['custom_named_series']['values']=values
   with self.assertRaises(ValueError):collect.normalize_traffic(data,'CA')
  data=result();data['custom_named_series']['timestamps']=list(reversed(TS))
  with self.assertRaises(ValueError):collect.normalize_traffic(data,'CA')
 def test_ip_percentages_do_not_become_volume_and_sum_validation(self):
  data=result(True);row=collect.normalize_ip(data,'CA');self.assertEqual(row['ipv6'],[35,40,None]);self.assertEqual(row['unit'],'percent')
  data['custom_named_series']['IPv6'][0]='99'
  with self.assertRaisesRegex(ValueError,'100%'):collect.normalize_ip(data,'CA')
 def test_outage_null_end_and_unsafe_source_url(self):
  raw={'id':'event-1','startDate':TS[0],'endDate':None,'locations':['CA'],'asns':[123],'description':'Source description','eventType':'OUTAGE','linkedUrl':'javascript:alert(1)','outage':{'outageCause':'POWER_OUTAGE','outageType':'REGIONAL'}}
  row=collect.normalize_outage(raw);self.assertIsNone(row['end_at']);self.assertEqual(row['source_url'],'https://radar.cloudflare.com/outage-center/ca');self.assertEqual(row['asns'],['123'])
  with self.assertRaises(ValueError):collect.normalize_outage({**raw,'locations':['US']})
 def test_missing_token_does_not_request(self):
  with patch.object(collect,'request') as request:
   with self.assertRaisesRegex(ValueError,'required'):collect.collect('')
   request.assert_not_called()
 def test_transient_failures_report_safe_status_and_retry_bounds(self):
  failures=[TimeoutError('never print this TEST-TOKEN'),URLError(socket.gaierror(-2,'never print DNS target')),
            HTTPError('https://example.test/?token=TEST-TOKEN',503,'never print source body',{},None)]
  for failure in failures:
   output=io.StringIO()
   with patch.object(collect,'urlopen',side_effect=failure) as fetch,patch.object(collect.time,'sleep'),redirect_stdout(output):
    with self.assertRaises(RuntimeError) as raised:collect.request('/radar/http/timeseries',{'location':'CA','format':'JSON'},'TEST-TOKEN')
   combined=output.getvalue()+str(raised.exception)
   self.assertEqual(fetch.call_count,3);self.assertIn('/radar/http/timeseries [CA]',combined);self.assertNotIn('TEST-TOKEN',combined);self.assertNotIn('never print',combined)
   expected='HTTP 503' if isinstance(failure,HTTPError) else 'DNS resolution failure' if isinstance(failure,URLError) else 'network timeout'
   self.assertIn(expected,combined)
 def test_auth_failure_is_not_retried_and_long_rate_pause_aborts(self):
  for status,headers,expected in [(401,{},'authentication/permission'),(429,{'Retry-After':'120'},'Retry-After 120')]:
   error=HTTPError('https://example.test',status,'sensitive response',headers,None)
   with patch.object(collect,'urlopen',side_effect=error) as fetch,patch.object(collect.time,'sleep'):
    with self.assertRaisesRegex(RuntimeError,expected):collect.request('/radar/http/timeseries',{'location':'CA'},'TEST-ONLY')
    self.assertEqual(fetch.call_count,1)
 def test_collection_uses_uppercase_dimension_and_separate_normalization(self):
  paths=[]
  def request(path,params,token):
   paths.append((path,params));return ({'annotations':[]} if path.endswith('outages') else result(path.endswith('IP_VERSION'))),{'url':collect.BASE+path,'parameters':params}
  with patch.object(collect,'request',side_effect=request):data=collect.collect('TEST ONLY')
  self.assertTrue(all(params.get('format')=='JSON' for _,params in paths));self.assertEqual(len(paths),7);self.assertEqual(len(data['traffic']),3);self.assertTrue(any(path.endswith('IP_VERSION') for path,_ in paths));self.assertNotIn('TEST ONLY',json.dumps(data))
 def test_bounded_outage_pagination_is_explicit(self):
  def request(path,params,token):
   if path.endswith('outages'):
    rows=[{'id':str(params['offset']+i),'startDate':TS[0],'locations':['CA'],'asns':[],'outage':{}} for i in range(100)]
    return {'annotations':rows},{'url':collect.BASE+path}
   return result(path.endswith('IP_VERSION')),{'url':collect.BASE+path}
  with patch.object(collect,'request',side_effect=request) as fetch:data=collect.collect('TEST ONLY')
  self.assertEqual(len(data['outages']),500);self.assertTrue(data['outage_coverage']['truncated']);self.assertEqual(fetch.call_count,11);self.assertTrue(data['warnings'])
 def test_immutable_archive_and_unchanged_check(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   with patch.object(collect,'now',return_value='2026-11-21T01:00:00Z'):first=collect.save(collected(),root)
   path=root/first['snapshot'];before=path.read_bytes()
   with patch.object(collect,'now',return_value='2026-11-22T01:00:00Z'):second=collect.save(collected(),root)
   self.assertEqual(second['captured_at'],first['captured_at']);self.assertNotEqual(second['checked_at'],first['checked_at']);self.assertEqual(path.read_bytes(),before)
   history=json.loads((root/'data/history.json').read_text());self.assertEqual(len(history),1);self.assertEqual(history[0]['sha256'],collect.sha(before))
   changed=collected();changed['traffic'][0]['values'][0]=.7
   with patch.object(collect,'now',return_value='2026-11-23T01:00:00Z'):collect.save(changed,root)
   self.assertEqual(len(json.loads((root/'data/history.json').read_text())),2);self.assertLess((root/'data/index.json').stat().st_size,2000)
