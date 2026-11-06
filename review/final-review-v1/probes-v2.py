#!/usr/bin/env python3
"""Fresh independent final-review probes. Frozen before execution; no product edits.

The reviewer supplies its own UDP orchestration/framing, uses the pre-product
reference for expected states, and preserves all results in a new run directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import select
import signal
import socket
import statistics
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'review'))
from reference import reference_sequence
CACHE=Path.home()/'.cache/job-apps-runtime/feed-replay/build'
VECTORS=json.loads((ROOT/'review/literal_vectors.json').read_text())['messages']
ORDER=json.loads((ROOT/'review/lifecycle_anchors.json').read_text())['events']
MESSAGES=[bytes.fromhex(VECTORS[name]['hex']) for name in ORDER]
SESSION=b'REVIEW0001'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def packet(first,messages):return SESSION+first.to_bytes(8,'big')+len(messages).to_bytes(2,'big')+b''.join(len(m).to_bytes(2,'big')+m for m in messages)
def marker(first,end=False):return SESSION+first.to_bytes(8,'big')+(65535 if end else 0).to_bytes(2,'big')
def capture(path,packets):
    with path.open('xb') as f:
        f.write(b'FRCP0001')
        for raw in packets:f.write(b'\0'+len(raw).to_bytes(4,'big')+raw)
def bound_socket():
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));return sock
def free_port():
    with bound_socket() as sock:return sock.getsockname()[1]
def stdout_line(proc,timeout=3):
    deadline=time.monotonic()+timeout;line=b''
    while time.monotonic()<deadline:
        if select.select([proc.stdout],[],[],max(0,deadline-time.monotonic()))[0]:
            character=os.read(proc.stdout.fileno(),1)
            if not character:raise AssertionError(('early exit',proc.poll(),proc.stderr.read().decode()))
            line+=character
            if character==b'\n':return json.loads(line)
    raise AssertionError('readiness timeout')

def launch(binary,directory,source,recovery,**options):
    directory.mkdir();port=free_port();out=directory/'out';cap=directory/'wire.frcp'
    args=[str(binary),'listen','--listen-port',str(port),'--source-port',str(source.getsockname()[1]),'--recovery-port',str(recovery.getsockname()[1]),'--session','REVIEW0001','--capture',str(cap),'--output',str(out),'--include-orders','1']
    for key,value in options.items():args+=['--'+key.replace('_','-'),str(value)]
    proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
    try:assert stdout_line(proc)['ready']
    except BaseException:
        proc.kill();proc.communicate();raise
    return proc,('127.0.0.1',port),out,cap
def finish(proc,out,code):
    stdout,stderr=proc.communicate(timeout=4)
    (out.parent/'process.json').write_text(json.dumps({'returncode':proc.returncode,'stdout':stdout.decode(),'stderr':stderr.decode()})+'\n')
    assert proc.returncode==code,(proc.returncode,stdout,stderr)
    return json.loads((out/'summary.json').read_text()),json.loads((out/'book.json').read_text())
def cleanup(proc):
    if proc.poll() is None:proc.kill()
    proc.communicate(timeout=3)

def evidence_integrity(_out,binary,probe):
    count=0
    frozen=json.loads((ROOT/'review/freeze-v1.json').read_text())
    for entry in frozen['files']:
        assert sha(ROOT/'review'/entry['path'])==entry['sha256'],entry['path'];count+=1
    index=json.loads((ROOT/'evidence/index.json').read_text())
    for name,entry in index['files'].items():
        assert sha(ROOT/name)==entry['sha256'],name;count+=1
    verification=json.loads((ROOT/'evidence/verification-20261023T212630Z/manifest.json').read_text())
    for name,digest in verification['source_hashes'].items():assert sha(ROOT/name)==digest,name
    for name,digest in verification['evidence_hashes'].items():assert sha(ROOT/'evidence/verification-20261023T212630Z'/name)==digest,name
    bench=json.loads((ROOT/'evidence/benchmark.json').read_text())
    for name,digest in bench['context']['source_sha256'].items():assert sha(ROOT/name)==digest,name
    assert sha(CACHE/'feed_benchmark')==bench['context']['binary_sha256']
    workload=json.loads((ROOT/'evidence/workload/manifest.json').read_text())
    for name,digest in workload['files'].items():assert sha(ROOT/'evidence/workload'/name)==digest,name
    assert sha(ROOT/'scripts/workload.py')==workload['generator_sha256']
    rows=[]
    for frequency in (1,32,256):
        values={name:[int(x['elapsed_ns']) for x in bench['result']['samples'] if x['frequency']==frequency and x['measured'] and x['engine']==name] for name in ('indexed','scan')}
        assert len(values['indexed'])==len(values['scan'])==8
        for pair in range(1,9):
            samples=sorted([s for s in bench['result']['samples'] if s['frequency']==frequency and s['pair']==pair],key=lambda x:x['position'])
            assert [x['engine'] for x in samples]==(['indexed','scan'] if pair%2 else ['scan','indexed'])
        row={'frequency':frequency,'indexed_median_ms':statistics.median(values['indexed'])/1e6,'scan_median_ms':statistics.median(values['scan'])/1e6,'ratio':statistics.median(values['scan'])/statistics.median(values['indexed'])}
        recorded=next(s for s in bench['summary'] if s['frequency']==frequency)
        assert abs(row['indexed_median_ms']-recorded['indexed_ms']['median'])<1e-12
        assert abs(row['scan_median_ms']-recorded['scan_ms']['median'])<1e-12
        assert abs(row['ratio']-recorded['median_scan_over_indexed'])<1e-12
        rows.append(row)
    parser=[int(s['elapsed_ns'])/1e6 for s in bench['result']['parser_samples'] if s['measured']]
    assert len(parser)==8
    return {'frozen_files':9,'index_files':len(index['files']),'verification_source_files':len(verification['source_hashes']),'verification_artifacts':len(verification['evidence_hashes']),'bench_rows':rows,'parser_median_ms':statistics.median(parser),'binary_sha256':sha(binary),'probe_sha256':sha(probe)}

def schedule_parity(out,_binary,probe):
    rng=random.Random(2026102307);cases=[];arrivals=0
    for case in range(96):
        packets=[]
        for _ in range(24):
            start=rng.randrange(1,18);width=rng.randrange(1,min(5,19-start))
            packets.append(packet(start,MESSAGES[start-1:start-1+width]))
            if rng.randrange(5)==0:packets.append(marker(18,rng.randrange(2)==0))
        # Recover the full declared prefix with different splits; overlap is intentional.
        start=1
        while start<18:
            width=rng.randrange(1,min(6,19-start));packets.append(packet(start,MESSAGES[start-1:start-1+width]));start+=width
        packets.append(marker(18,True))
        expected=reference_sequence(packets)['states']
        p=subprocess.run([str(probe),'session','offline','100000','1000000','4096'],input=''.join(x.hex()+'\n' for x in packets),text=True,capture_output=True,timeout=4)
        assert p.returncode==0,p.stderr
        actual=[json.loads(x) for x in p.stdout.splitlines()]
        for state in actual:assert state.pop('requests')==[]
        assert actual==expected,case
        assert actual[-1]['status']=='Complete' and actual[-1]['expected']=='18'
        cases.append({'case':case,'packets':[x.hex() for x in packets]});arrivals+=len(packets)
    (out/'random-schedules.json').write_text(json.dumps(cases)+'\n')
    return {'seed':2026102307,'schedules':len(cases),'arrivals_compared':arrivals}

def full_udp_tiny_recovery(out,binary,_probe):
    with bound_socket() as source,bound_socket() as recovery:
        proc,address,destination,cap=launch(binary,out/'tiny-recovery',source,recovery)
        requests=[]
        try:
            source.sendto(packet(1,MESSAGES[:3]),address);source.sendto(marker(18,True),address)
            recovery.settimeout(1)
            while len(requests)<7:
                raw,peer=recovery.recvfrom(65507)
                first=int.from_bytes(raw[10:18],'big');count=int.from_bytes(raw[18:20],'big')
                assert len(raw)==20 and raw[:10]==SESSION and peer[1]==address[1]
                assert first==4+2*len(requests) and count==18-first,(first,count)
                requests.append({'wire':raw.hex(),'peer':peer})
                recovery.sendto(packet(first,MESSAGES[first-1:first+1]),peer)
            summary,book=finish(proc,destination,0)
            assert summary['expected']=='18' and summary['counters']['requests_sent']=='7'
            assert not summary['quote_usable'] and not summary['live_fresh'] and summary['itch_end_seen']
            expected=reference_sequence([packet(1,MESSAGES),marker(18,True)])['states'][-1]['book']
            assert book==expected
            replay=subprocess.run([str(binary),'replay','--capture',str(cap),'--session','REVIEW0001','--output',str(cap.parent/'replay'),'--include-orders','1'],capture_output=True,timeout=4)
            assert replay.returncode==0,replay.stderr
            assert json.loads((cap.parent/'replay/book.json').read_text())==book
            (cap.parent/'observed-requests.json').write_text(json.dumps(requests,indent=2)+'\n')
            return {'requests':len(requests),'final_expected':summary['expected'],'live_orders':book['order_count']}
        finally:cleanup(proc)

def invalid_future(out,binary,_probe):
    with bound_socket() as source,bound_socket() as recovery:
        proc,address,destination,_=launch(binary,out/'future-malformed',source,recovery)
        try:
            source.sendto(packet(1,MESSAGES[:3]),address)
            source.sendto(packet(8,[MESSAGES[7],b'Z']),address)
            summary,book=finish(proc,destination,4)
            assert summary['error']['code']=='unsupported_type' and summary['error']['sequence']=='8'
            assert summary['expected']==summary['high_water_next']=='4' and book['order_count']==0
            assert summary['counters']['requests_sent']=='0'
            return {'status':summary['status'],'expected':summary['expected'],'high_water_next':summary['high_water_next']}
        finally:cleanup(proc)

def zero_datagram_budget(out,binary,_probe):
    with bound_socket() as source,bound_socket() as recovery,bound_socket() as foreign:
        proc,address,destination,cap=launch(binary,out/'zero-byte-budget',source,recovery,receive_count=4)
        try:
            for _ in range(5):foreign.sendto(b'',address)
            summary,_=finish(proc,destination,4)
            assert summary['error']['code']=='resource_limit'
            assert summary['counters']['udp_received']=='5' and summary['counters']['udp_received_bytes']=='0'
            assert summary['counters']['foreign']=='4' and summary['counters']['datagrams']=='0'
            assert cap.read_bytes()==b'FRCP0001'
            return {'received':5,'capture_bytes':cap.stat().st_size}
        finally:cleanup(proc)

def late_output_competitor(out,binary,_probe):
    with bound_socket() as source,bound_socket() as recovery:
        proc,address,destination,cap=launch(binary,out/'late-output',source,recovery)
        try:
            destination.mkdir();sentinel=destination/'sentinel';sentinel.write_bytes(b'preexisting\x00owner')
            source.sendto(marker(1,True),address)
            stdout,stderr=proc.communicate(timeout=4)
            assert proc.returncode==2,(stdout,stderr)
            assert sentinel.read_bytes()==b'preexisting\x00owner' and sorted(p.name for p in destination.iterdir())==['sentinel']
            assert not list(destination.parent.glob('out.tmp-*')) and cap.stat().st_size==33
            (destination.parent/'process.json').write_text(json.dumps({'returncode':proc.returncode,'stderr':stderr.decode()})+'\n')
            return {'returncode':2,'sentinel_preserved':True,'capture_bytes':33}
        finally:cleanup(proc)

def cancel_after_progress(out,binary,_probe):
    with bound_socket() as source,bound_socket() as recovery:
        proc,address,destination,_=launch(binary,out/'cancel-progress',source,recovery)
        try:
            source.sendto(packet(1,MESSAGES[:3]),address);source.sendto(marker(18,True),address)
            recovery.settimeout(1);first,peer=recovery.recvfrom(65507)
            assert int.from_bytes(first[10:18],'big')==4
            recovery.sendto(packet(4,[MESSAGES[3]]),peer)
            second,_=recovery.recvfrom(65507);assert int.from_bytes(second[10:18],'big')==5
            proc.send_signal(signal.SIGINT)
            summary,book=finish(proc,destination,3)
            assert summary['status']=='Cancelled' and summary['expected']=='5' and book['order_count']==1
            assert not summary['quote_usable'] and summary['counters']['requests_sent']=='2'
            return {'status':summary['status'],'expected':summary['expected'],'requests':2}
        finally:cleanup(proc)

def new_clock_limits(out,_binary,probe):
    lines=[marker(1000).hex()]+[packet(n,[MESSAGES[0]]).hex() for n in range(1,129)]
    p=subprocess.run([str(probe),'session','live','100000','1000000','4096'],input='\n'.join(lines)+'\n',text=True,capture_output=True,timeout=4)
    assert p.returncode==0,p.stderr
    states=[json.loads(s) for s in p.stdout.splitlines()]
    assert sum(len(s['requests']) for s in states)==128
    assert states[-1]['status']=='RecoveryFailed' and states[-1]['expected']=='129'
    assert states[-1]['error']=='recovery_exhausted' and not states[-1]['quote_usable']
    lines=[marker(18).hex(),'@149999999','@150000000',packet(1,MESSAGES).hex()]
    p=subprocess.run([str(probe),'session','live','100000','1000000','4096'],input='\n'.join(lines)+'\n',text=True,capture_output=True,timeout=4)
    assert p.returncode==0,p.stderr
    states=[json.loads(s) for s in p.stdout.splitlines()]
    assert states[-1]['status']=='RecoveryFailed' and states[-1]['expected']=='1'
    (out/'clock-boundaries.json').write_text(json.dumps(states,indent=2)+'\n')
    return {'request_cap':128,'final_expected_after_cap':'129','exact_deadline_kept_prefix':'1'}

TESTS=[evidence_integrity,schedule_parity,full_udp_tiny_recovery,invalid_future,zero_datagram_budget,late_output_competitor,cancel_after_progress,new_clock_limits]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--sanitized',action='store_true');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    suffix='_sanitized' if args.sanitized else '';binary=CACHE/('feed_replay'+suffix);probe=CACHE/('probe'+suffix)
    results=[]
    for test in TESTS:
        start=time.monotonic()
        try:result={'test':test.__name__,'passed':True,'details':test(args.output,binary,probe)}
        except BaseException:result={'test':test.__name__,'passed':False,'traceback':traceback.format_exc()}
        result['wall_seconds']=time.monotonic()-start;results.append(result)
        (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)
if __name__=='__main__':main()
