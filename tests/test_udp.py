import json
import os
from pathlib import Path
import select
import signal
import shutil
import socket
import subprocess
import sys
import time
import pytest
from test_cli import BINARY
from test_codec import ROOT, VECTORS
from test_session import packet, marker
from reference import reference_sequence


def read_json(proc, timeout=3):
    # Unbuffered binary stdout avoids select() missing Python text-buffered lines.
    end = time.monotonic() + timeout
    line = bytearray()
    while time.monotonic() < end:
        if select.select([proc.stdout], [], [], max(0, end-time.monotonic()))[0]:
            byte = os.read(proc.stdout.fileno(), 1)
            if not byte:
                raise AssertionError(f'process exited {proc.poll()}: {proc.stderr.read().decode()}')
            if byte == b'\n':
                value=json.loads(line)
                if "request" in value and os.environ.get("FEED_EVIDENCE_DIR"):
                    path=Path(os.environ["FEED_EVIDENCE_DIR"]);path.mkdir(parents=True,exist_ok=True)
                    with (path/"observed-requests.jsonl").open("a") as log:
                        log.write(json.dumps({"test":os.environ.get("PYTEST_CURRENT_TEST"),**value})+"\n")
                return value
            line.extend(byte)
    raise AssertionError('subprocess readiness/output timeout')


class Peer:
    def __init__(self, **config):
        self.proc = subprocess.Popen([sys.executable, str(ROOT/'scripts/udp_fixture.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.command(config)
        self.port = read_json(self.proc)['port']

    def command(self, value):
        self.proc.stdin.write(json.dumps(value).encode()+b'\n')
        self.proc.stdin.flush()

    def send(self, port, packets):
        self.command({'op':'send','port':port,'packets':[x.hex() for x in packets]})
        assert read_json(self.proc)['sent'] == len(packets)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.communicate(timeout=3)


@pytest.fixture
def peers():
    owned=[]
    def make(**config):
        p=Peer(**config);owned.append(p);return p
    yield make
    for p in owned:p.stop()


def free_port():
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]


OWNED_RECEIVERS=[]

@pytest.fixture(autouse=True)
def cleanup_receivers():
    yield
    for proc in OWNED_RECEIVERS:
        if proc.poll() is None:proc.terminate()
        proc.communicate(timeout=3)
    OWNED_RECEIVERS.clear()

def receiver(tmp_path, source, recovery, **options):
    port=free_port();out=tmp_path/'out';capture=tmp_path/'wire.frcp'
    args=[str(BINARY),'listen','--listen-port',str(port),'--source-port',str(source.port),'--recovery-port',str(recovery.port),'--session','REVIEW0001','--capture',str(capture),'--output',str(out),'--include-orders','1']
    for key,value in options.items():args += ['--'+key.replace('_','-'),str(value)]
    proc=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0)
    OWNED_RECEIVERS.append(proc)
    try:assert read_json(proc)['ready'] is True
    except BaseException:
        if proc.poll() is None:proc.kill()
        proc.communicate();raise
    return proc,port,out,capture


def finish(proc,out,expected):
    stdout,stderr=proc.communicate(timeout=4)
    assert proc.returncode==expected,(stdout,stderr)
    if os.environ.get('FEED_EVIDENCE_DIR'):
        saved=Path(os.environ['FEED_EVIDENCE_DIR'])/(out.parent.name+'-'+out.name)
        shutil.copytree(out,saved)
        for name in ('wire.frcp','race.frcp'):
            capture=out.parent/name
            if capture.exists():shutil.copyfile(capture,saved/name)
        (saved/'process.json').write_text(json.dumps({'returncode':proc.returncode,'stdout':stdout.decode(),'stderr':stderr.decode()})+'\n')
    return json.loads((out/'summary.json').read_text()),json.loads((out/'book.json').read_text())


def messages():return [bytes.fromhex(VECTORS[n]['hex']) for n in ['alpha','add_bid','add_attributed_ask']]


def replay_matches(capture,output,book):
    proc=subprocess.run([str(BINARY),'replay','--capture',str(capture),'--output',str(output),'--session','REVIEW0001','--include-orders','1'],capture_output=True,timeout=3)
    assert proc.returncode==0,proc.stderr
    assert json.loads((output/'book.json').read_text())==book


@pytest.mark.parametrize('tail',['future','heartbeat','end'])
@pytest.mark.parametrize('partial',[1,128])
def test_actual_gap_recovery_and_partial_responses(tmp_path,peers,tail,partial):
    msgs=messages();source=peers();recovery=peers(messages=[m.hex() for m in msgs],partial=partial)
    proc,port,out,cap=receiver(tmp_path,source,recovery)
    if tail=='future':frames=[packet(1,msgs[:1]),packet(3,msgs[2:]),marker(4,True)]
    elif tail=='heartbeat':frames=[packet(1,msgs[:1]),marker(4),marker(4,True)]
    else:frames=[packet(1,msgs[:1]),marker(4,True)]
    source.send(port,frames)
    summary,book=finish(proc,out,0)
    request=read_json(recovery.proc)
    wire=bytes.fromhex(request['request'])
    assert wire[:10]==b'REVIEW0001' and int.from_bytes(wire[10:18],'big')==2 and int.from_bytes(wire[18:20],'big')==2
    assert request['peer_port']==port
    assert summary['status']=='Complete' and summary['expected']=='4' and not summary['quote_usable']
    assert book==reference_sequence([packet(1,msgs),marker(4,True)])['states'][-1]['book']
    replay_matches(cap,tmp_path/'replay',book)


def test_actual_overlap_and_old_duplicate(tmp_path,peers):
    msgs=messages();s=peers();r=peers(drop=True);p,port,out,_=receiver(tmp_path,s,r)
    s.send(port,[packet(1,msgs[:2]),packet(1,msgs[:2]),packet(2,msgs[1:]),marker(4,True)])
    summary,book=finish(p,out,0)
    assert summary['counters']['old_messages']=='3' and summary['counters']['requests_generated']=='0'
    assert book['order_count']==2


@pytest.mark.parametrize('foreign',[False,True])
def test_flood_does_not_extend_stalled_gap_deadline(tmp_path,peers,foreign):
    msgs=messages();s=peers();r=peers(drop=True);f=peers() if foreign else s
    p,port,out,_=receiver(tmp_path,s,r)
    s.send(port,[packet(1,msgs[:1]),marker(4)])
    start=time.monotonic();f.command({'op':'flood','port':port,'packet':packet(1,msgs[:1]).hex(),'seconds':0.35})
    summary,_=finish(p,out,3)
    assert time.monotonic()-start<0.8 and summary['status']=='RecoveryFailed'
    assert summary['error']['code']=='recovery_exhausted' and summary['counters']['requests_generated']=='3'
    assert summary['expected']=='2'
    if foreign:assert summary['counters']['foreign']!='0'


def test_kernel_recvmsg_truncation_is_invalid(tmp_path,peers):
    s=peers();r=peers(drop=True);p,port,out,cap=receiver(tmp_path,s,r,recv_buffer=20)
    s.send(port,[packet(1,messages())]);summary,book=finish(p,out,4)
    assert summary['error']['code']=='truncated_datagram' and summary['expected']=='1' and book['order_count']==0
    assert cap.read_bytes()[8]==1


@pytest.mark.parametrize('kind',['wrong_session','terminal_conflict','malformed'])
def test_pinned_invalid_traffic_preserves_prefix(tmp_path,peers,kind):
    s=peers();r=peers(drop=True);p,port,out,_=receiver(tmp_path,s,r)
    msgs=messages();first=packet(1,msgs[:1])
    bad={'wrong_session':b'WRONG00001'+marker(2)[10:], 'terminal_conflict':marker(1,True), 'malformed':packet(2,msgs[1:])+b'extra'}[kind]
    s.send(port,[first,bad]);summary,book=finish(p,out,4)
    assert summary['expected']=='2' and book['order_count']==0 and not summary['quote_usable']
    assert summary['error']['code']=={'wrong_session':'session_mismatch','terminal_conflict':'terminal_conflict','malformed':'mold_trailing'}[kind]


def test_foreign_only_traffic_cannot_evade_overall_deadline(tmp_path,peers):
    s=peers();r=peers(drop=True);f=peers();p,port,out,cap=receiver(tmp_path,s,r,overall_ms=200)
    f.command({'op':'flood','port':port,'packet':packet(1,messages()).hex(),'seconds':0.35})
    summary,book=finish(p,out,3)
    assert summary['status']=='RecoveryFailed' and summary['error']['code']=='deadline'
    assert summary['counters']['foreign']!='0' and summary['counters']['datagrams']=='0' and book['order_count']==0
    assert cap.read_bytes()==b'FRCP0001'


@pytest.mark.parametrize('bound',['receive_bytes','receive_count'])
def test_foreign_traffic_charged_to_receive_caps(tmp_path,peers,bound):
    s=peers();r=peers(drop=True);f=peers();p,port,out,_=receiver(tmp_path,s,r,**{bound:64 if bound=='receive_bytes' else 2})
    f.send(port,[packet(1,messages())]*3);summary,_=finish(p,out,4)
    assert summary['error']['code']=='resource_limit' and summary['counters']['datagrams']=='0'


def test_signal_cancellation_closes_and_publishes_prefix(tmp_path,peers):
    s=peers();r=peers(drop=True);p,port,out,cap=receiver(tmp_path,s,r)
    s.send(port,[packet(1,messages())])
    # A receiver-generated recovery request is an explicit processing handshake.
    s.send(port,[marker(5)])
    assert 'request' in read_json(r.proc)
    p.send_signal(signal.SIGTERM);summary,book=finish(p,out,3)
    assert summary['status']=='Cancelled' and summary['expected']=='4' and book['order_count']==2
    assert not summary['quote_usable'] and cap.stat().st_size>8


def test_terminated_recovery_peer_fails_bounded(tmp_path,peers):
    s=peers();r=peers(drop=True);p,port,out,_=receiver(tmp_path,s,r)
    r.stop();s.send(port,[marker(4,True)])
    summary,_=finish(p,out,3)
    assert summary['status']=='RecoveryFailed' and summary['counters']['requests_generated']=='3'


def test_exclusive_capture_never_truncates_existing(tmp_path,peers):
    s=peers();r=peers(drop=True);cap=tmp_path/'wire.frcp';cap.write_bytes(b'preserve')
    args=[str(BINARY),'listen','--listen-port',str(free_port()),'--source-port',str(s.port),'--recovery-port',str(r.port),'--session','REVIEW0001','--capture',str(cap),'--output',str(tmp_path/'out')]
    p=subprocess.run(args,capture_output=True,timeout=3)
    assert p.returncode==2 and cap.read_bytes()==b'preserve' and not (tmp_path/'out').exists()


def test_competing_capture_creators_have_exactly_one_owner(tmp_path,peers):
    s=peers();r=peers(drop=True);cap=tmp_path/'race.frcp';owned=[]
    for index in range(2):
        port=free_port();out=tmp_path/f'out{index}'
        args=[str(BINARY),'listen','--listen-port',str(port),'--source-port',str(s.port),'--recovery-port',str(r.port),'--session','REVIEW0001','--capture',str(cap),'--output',str(out)]
        owned.append((subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0),port,out))
    winners=[];losers=[]
    try:
        for p,port,out in owned:
            line=p.stdout.readline()
            if line:
                assert json.loads(line)['ready'];winners.append((p,port,out))
            else:
                _,stderr=p.communicate(timeout=3);assert p.returncode==2 and b'capture' in stderr;losers.append(out)
        assert len(winners)==len(losers)==1
        p,port,out=winners[0];s.send(port,[marker(1,True)])
        summary,_=finish(p,out,0);assert summary['expected']=='1'
        assert not losers[0].exists()
        assert cap.read_bytes()==b'FRCP0001\0'+(20).to_bytes(4,'big')+marker(1,True)
    finally:
        for p,_,_ in owned:
            if p.poll() is None:p.kill()
            p.communicate(timeout=3)


@pytest.mark.parametrize('option,value', [('recv-buffer','19'),('recv-buffer','65508'),('overall-ms','0'),('overall-ms','10001'),('receive-count','2000001'),('receive-bytes','67108865'),('listen-port','65536'),('source-port','0')])
def test_live_bounds_refused_without_creating_capture(tmp_path,peers,option,value):
    s=peers();r=peers(drop=True);args=[str(BINARY),'listen','--listen-port',str(free_port()),'--source-port',str(s.port),'--recovery-port',str(r.port),'--session','REVIEW0001','--capture',str(tmp_path/'c'),'--output',str(tmp_path/'o')]
    # Replace the option when it is required, otherwise append it.
    if '--'+option in args:args[args.index('--'+option)+1]=value
    else:args+=['--'+option,value]
    p=subprocess.run(args,capture_output=True,timeout=3)
    assert p.returncode==2 and not (tmp_path/'c').exists() and not (tmp_path/'o').exists()
