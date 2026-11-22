"""CI-only browser acceptance; all local-import fixtures are explicitly synthetic."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
import threading
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def main():
    screenshots=ROOT/'browser-checks';screenshots.mkdir(exist_ok=True)
    times=['2026-02-01T00:00:00Z','2026-02-01T01:00:00Z','2026-02-01T02:00:00Z','2026-02-01T03:00:00Z']
    fixture={'schema':1,'tool':'radarscope','status':'ready','captured_at':'2026-02-01T04:00:00Z','checked_at':'2026-02-01T04:00:00Z','coverage':'Synthetic browser-test fixture only','sources':[],'warnings':[],'traffic':[{'country':c,'name':c,'timestamps':times,'values':[.2,None,.8,1],'normalization':'MIN0_MAX','unit':'normalized index','source_url':'https://radar.cloudflare.com/traffic/'+c.lower()} for c in ['CA','US','GB']],'ip_versions':[{'country':c,'timestamps':times,'ipv4':[60,None,58,55],'ipv6':[40,None,42,45],'normalization':'PERCENTAGE'} for c in ['CA','US','GB']],'outages':[{'id':'test-one','start_at':times[0],'end_at':None,'description':'<img src=x onerror=alert(1)>','event_type':'OUTAGE','countries':['CA'],'asns':['64500'],'scope':'country','cause':'Synthetic test only','outage_type':'test','source_url':'https://radar.cloudflare.com/outage-center'},{'id':'test-two','start_at':times[1],'end_at':times[3],'description':'Synthetic US event','event_type':'ANOMALY','countries':['US'],'asns':[],'scope':'country','cause':'Synthetic test only','outage_type':'test','source_url':'https://radar.cloudflare.com/outage-center'}]}
    with tempfile.TemporaryDirectory() as temporary:
        site=Path(temporary)/'radarscope';shutil.copytree(ROOT/'dist',site)
        (site/'archive/2026-02').mkdir(parents=True,exist_ok=True);(site/'archive/2026-02/synthetic-test.json').write_text(json.dumps(fixture));(site/'data/history.json').write_text(json.dumps([{'captured_at':fixture['captured_at'],'file':'archive/2026-02/synthetic-test.json','sha256':'test-only'}]))
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=temporary));threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch();page=browser.new_page(viewport={'width':1280,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/radarscope/');expect(page.locator('#status')).not_to_contain_text('Loading')
                page.locator('#import-file').set_input_files({'name':'synthetic-browser-test.json','mimeType':'application/json','buffer':json.dumps(fixture).encode()});expect(page.locator('#status')).to_contain_text('LOCAL FILE')
                assert page.locator('#traffic-stat').inner_text()=='1.000';assert page.locator('#ipv6-stat').inner_text()=='45.0%';assert page.locator('#outage-stat').inner_text()=='1'
                assert page.locator('#events .event').count()==1;assert page.locator('#events img').count()==0
                page.locator('.countries input[value="US"]').check();assert page.locator('#traffic-chart svg').count()==1
                assert page.locator('#traffic-chart path.series').count()==2
                page.locator('#window').select_option('24');page.locator('#ip-country').select_option('GB');assert page.locator('#ipv6-value').inner_text()=='45.0%'
                page.locator('#traffic-chart circle').first.focus();expect(page.locator('#chart-readout')).to_contain_text('Canada')
                page.locator('#outage-country').select_option('all');assert page.locator('#events .event').count()==2
                page.locator('#outage-type').select_option('ANOMALY');assert page.locator('#events .event').count()==1
                page.locator('#outage-query').fill('no match');assert page.locator('#outage-empty').is_visible()
                page.locator('#reset-events').click();assert page.locator('#events .event').count()==1
                for button,name in[('#traffic-csv','radarscope-traffic.csv'),('#ip-csv','radarscope-ip-shares.csv'),('#outage-csv','radarscope-outages.csv'),('#snapshot-json','radarscope-snapshot.json')]:
                    with page.expect_download() as info:page.locator(button).click()
                    assert info.value.suggested_filename==name
                page.locator('#import-file').set_input_files({'name':'invalid.json','mimeType':'application/json','buffer':b'{"schema":999}'});expect(page.locator('#import-status')).to_contain_text('Could not open file');assert page.locator('#traffic-stat').inner_text()=='1.000'
                page.locator('#snapshot').select_option('archive/2026-02/synthetic-test.json');expect(page.locator('#status')).to_contain_text('ARCHIVED CAPTURE')
                page.screenshot(path=str(screenshots/'desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth');page.screenshot(path=str(screenshots/'mobile.png'),full_page=True)
                page.locator('#restore').click();expect(page.locator('#restore')).to_be_hidden();assert 'ARCHIVED CAPTURE' not in page.locator('#status').inner_text()
                assert not errors,errors;browser.close()
            print('Browser acceptance passed: local source data, normalized charts, null gaps, country/event filters, exports, archive switching, safe text, restore and mobile.')
        finally:server.shutdown()
if __name__=='__main__':main()
