import json
import subprocess
import pytest
from test_codec import ROOT,PROBE,VECTORS,ANCHORS
from reference import reference_sequence

CASES=json.loads((ROOT/'review/literal_fixtures.json').read_text())['cases']
def run(lines,live=False,limits=None):
 limits=limits or {}
 args=[str(PROBE),'session','live' if live else 'offline',str(limits.get('max_orders',100000)),str(limits.get('max_ids',1000000)),str(limits.get('max_instruments',4096))]
 p=subprocess.run(args,input=''.join((v.hex() if isinstance(v,bytes) else v)+'\n' for v in lines),text=True,capture_output=True,timeout=10)
 assert p.returncode==0,p.stderr
 return [json.loads(x) for x in p.stdout.splitlines()]

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_frozen_sequence_cases_match_independent_prefix_oracle(case):
 data=[bytes.fromhex(x) for x in case['packets']]
 expected=reference_sequence(data,**case.get('limits',{}))['states']
 actual=run(data,limits=case.get('limits',{}))
 for state in actual:assert state.pop('requests')==[]
 assert actual==expected

def packet(first,messages):
 return b'REVIEW0001'+first.to_bytes(8,'big')+len(messages).to_bytes(2,'big')+b''.join(len(m).to_bytes(2,'big')+m for m in messages)
def marker(first,end=False):return b'REVIEW0001'+first.to_bytes(8,'big')+(65535 if end else 0).to_bytes(2,'big')

def test_recovery_requests_and_retry_exhaustion_at_exact_times():
 states=run([marker(200),'@49999999','@50000000','@100000000','@150000000'],True)
 assert [len(s['requests']) for s in states]==[1,0,1,1,0]
 for s in [states[0],states[2],states[3]]:assert s['requests'][0]['first']=='1' and s['requests'][0]['count']==128
 assert states[-1]['status']=='RecoveryFailed' and states[-1]['error']=='recovery_exhausted'
 assert states[-1]['expected']=='1' and not states[-1]['quote_usable']

def test_progress_moves_request_cursor_without_losing_high_water():
 start=bytes.fromhex(VECTORS['start']['hex'])
 s=run([marker(4),packet(1,[start]),'@50000000'],True)
 assert s[1]['expected']=='2' and s[1]['high_water_next']=='4'
 assert s[1]['requests'][0]['first']=='2' and s[1]['requests'][0]['count']==2
 assert s[2]['requests'][0]['first']=='2'

def test_old_duplicate_does_not_refresh_silence_but_heartbeat_does():
 p=bytes.fromhex(ANCHORS['multi_message']['hex'])
 s=run([p,'@1499999999',p,'@1500000000',marker(4)],True)
 assert s[1]['status']=='CurrentObserved' and s[2]['status']=='CurrentObserved'
 assert s[3]['status']=='Stale' and not s[3]['quote_usable']
 assert s[4]['status']=='CurrentObserved' and s[4]['quote_usable']

def test_duplicate_traffic_cannot_extend_recovery_deadline():
 p=bytes.fromhex(ANCHORS['multi_message']['hex'])
 s=run([p,marker(10),'@50000000',p,'@100000000',p,'@150000000',p],True)
 assert s[-1]['status']=='RecoveryFailed' and s[-1]['expected']=='4'

def test_completion_not_silence_or_itch_end_controls_transport():
 p=bytes.fromhex(ANCHORS['multi_message']['hex'])
 s=run([p,marker(4,True),'@2000000000'],True)
 assert s[-1]['status']=='Complete' and not s[-1]['live_fresh']
 assert s[-1]['end_next']=='4'

def test_invalid_latches_and_stops_recovery():
 s=run([marker(5),b'bad','@50000000',marker(8)],True)
 assert s[-1]['status']=='Invalid' and all(not x['requests'] for x in s[1:])

def test_overall_deadline_and_cancellation():
 assert run(['@10000000000'],True)[0]['error']=='deadline'
 s=run([marker(4),'!cancel','@50000000'],True)
 assert s[-1]['status']=='Cancelled' and not s[-1]['requests']

def test_tiny_progress_does_not_extend_continuous_gap_budget():
 start=bytes.fromhex(VECTORS['start']['hex']);lines=[marker(1000)]
 for n in range(1,10):lines.extend([f'@{n*100000000}',packet(n,[start])])
 lines.append('@1000000000');s=run(lines,True)
 assert s[-2]['expected']=='10' and s[-1]['expected']=='10'
 assert s[-1]['status']=='RecoveryFailed' and not s[-1]['requests']

def test_reversed_injected_clock_invalidates():
 states=run(['@1','@0'],True)
 assert states[-1]['status']=='Invalid' and states[-1]['error']=='field_domain'
