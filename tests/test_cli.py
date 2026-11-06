import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_codec import ROOT,VECTORS
from reference import reference_sequence
from test_session import CASES,packet,marker
BINARY=Path(os.environ.get('FEED_BINARY',Path(os.environ.get('FEED_CACHE',Path.home()/'.cache/job-apps-runtime/feed-replay'))/'build/feed_replay'))

def capture(path,packets,flags=0):
 with path.open('wb') as f:
  f.write(b'FRCP0001')
  for data in packets:f.write(bytes([flags])+len(data).to_bytes(4,'big')+data)
 return path

def invoke(source,out,*args):
 return subprocess.run([str(BINARY),'replay','--capture',str(source),'--session','REVIEW0001','--output',str(out),'--include-orders','1',*map(str,args)],capture_output=True,text=True,timeout=20)

def complete_source(tmp_path):
 data=[bytes.fromhex(x) for x in CASES[0]['packets']]
 return capture(tmp_path/'input.frcp',data),data

def test_complete_replay_publishes_exact_book_and_offline_flags(tmp_path):
 source,data=complete_source(tmp_path);out=tmp_path/'out';p=invoke(source,out)
 assert p.returncode==0,p.stderr
 s=json.loads((out/'summary.json').read_text());book=json.loads((out/'book.json').read_text())
 expected=reference_sequence(data)['states'][-1]
 assert s['status']=='Complete' and s['expected']==expected['expected']
 assert s['transport_complete'] and not s['live_fresh'] and not s['quote_usable']
 assert book==expected['book']
 assert not list(tmp_path.glob('out.tmp-*'))

def test_gap_free_eof_without_terminal_is_incomplete(tmp_path):
 source=capture(tmp_path/'in.frcp',[bytes.fromhex(CASES[0]['packets'][0])]);out=tmp_path/'out';p=invoke(source,out)
 assert p.returncode==3,p.stderr
 s=json.loads((out/'summary.json').read_text());assert s['status']=='Incomplete' and not s['quote_usable'] and not s['live_fresh']

def test_invalid_semantics_publish_honest_prefix(tmp_path):
 case=next(c for c in CASES if c['name']=='semantic_error_retains_packet_prefix') if any(c['name']=='semantic_error_retains_packet_prefix' for c in CASES) else next(c for c in CASES if 'semantic' in c['name'])
 data=[bytes.fromhex(x) for x in case['packets']];source=capture(tmp_path/'in.frcp',data);out=tmp_path/'out';p=invoke(source,out)
 assert p.returncode==4,p.stderr
 s=json.loads((out/'summary.json').read_text());expected=reference_sequence(data)['states'][-1]
 assert s['status']=='Invalid' and s['error']['code']==expected['error'] and not s['quote_usable']
 assert s['expected']==expected['expected'] and json.loads((out/'book.json').read_text())==expected['book']

@pytest.mark.parametrize('extra', [['--depth','-1'],['--depth','21'],['--depth','1.5'],['--session','short'],['--session','REVIEW0001'],['--unknown','x'],['--include-orders','2']])
def test_invalid_cli_preserves_output_absence(tmp_path,extra):
 source,_=complete_source(tmp_path);out=tmp_path/'out'
 assert invoke(source,out,*extra).returncode==2 and not out.exists()

@pytest.mark.parametrize('data',[b'',b'FRCP0002',b'FRCP0001\0\0',b'FRCP0001\x02\0\0\0\0',b'FRCP0001\0\0\x01\0\0',b'FRCP0001\0\0\0\0\x14bad'])
def test_malformed_capture_never_publishes_success(tmp_path,data):
 source=tmp_path/'in.frcp';source.write_bytes(data);out=tmp_path/'out'
 assert invoke(source,out).returncode==2 and not out.exists()

def test_capture_size_bound_checked_before_read(tmp_path):
 source=tmp_path/'big.frcp'
 with source.open('wb') as f:f.truncate(64*1024**2+1)
 assert invoke(source,tmp_path/'out').returncode==2

def test_existing_output_and_symlink_remain_untouched(tmp_path):
 source,_=complete_source(tmp_path);out=tmp_path/'out';out.mkdir();(out/'sentinel').write_text('keep')
 assert invoke(source,out).returncode==2 and (out/'sentinel').read_text()=='keep'
 link=tmp_path/'link';link.symlink_to(tmp_path/'missing')
 assert invoke(source,link).returncode==2 and link.is_symlink()

def test_competing_processes_publish_one_coherent_output(tmp_path):
 source,data=complete_source(tmp_path);out=tmp_path/'out';barrier=threading.Barrier(2)
 def worker():barrier.wait();return invoke(source,out)
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:worker(),range(2)))
 assert sorted(p.returncode for p in results)==[0,2],[p.stderr for p in results]
 assert json.loads((out/'book.json').read_text())==reference_sequence(data)['states'][-1]['book']
 assert not list(tmp_path.glob('out.tmp-*'))

def test_graphic_symbol_is_json_escaped_and_depth_zero_keeps_best(tmp_path):
 symbol=b'A"\\B    ';r=bytearray.fromhex(VECTORS['alpha']['hex']);r[11:19]=symbol
 a=bytearray.fromhex(VECTORS['add_bid']['hex']);a[24:32]=symbol
 data=[packet(1,[bytes(r),bytes(a)]),marker(3,True)]
 source=capture(tmp_path/'in.frcp',data);out=tmp_path/'out';p=invoke(source,out,'--depth',0)
 assert p.returncode==0,p.stderr
 i=json.loads((out/'book.json').read_text())['instruments'][0]
 assert i['symbol']=='A"\\B' and i['bids']==[] and i['best_bid']=={'price':100000,'quantity':'100'}


def test_output_cap_refuses_large_full_book_before_publication(tmp_path):
 # Exactly the live-order hard limit, but its full JSON exceeds the separate 8 MiB cap.
 template=bytearray.fromhex(VECTORS['add_attributed_ask']['hex'])
 template[20:24]=(2**32-1).to_bytes(4,'big');template[32:36]=(2_000_000_000).to_bytes(4,'big')
 source=tmp_path/'large.frcp'
 with source.open('wb') as f:
  f.write(b'FRCP0001');sequence=1
  def record(data):f.write(b'\0'+len(data).to_bytes(4,'big')+data)
  record(packet(sequence,[bytes.fromhex(VECTORS['alpha']['hex'])]));sequence+=1
  for offset in range(0,100000,200):
   block=[]
   for index in range(offset,offset+200):
    event=bytearray(template);event[11:19]=(10_000_000_000_000_000_000+index).to_bytes(8,'big');block.append(bytes(event))
   record(packet(sequence,block));sequence+=len(block)
  record(marker(sequence,True))
 out=tmp_path/'out';p=invoke(source,out)
 assert p.returncode==2 and 'output_limit' in p.stderr and not out.exists()
 assert not list(tmp_path.glob('out.tmp-*'))
