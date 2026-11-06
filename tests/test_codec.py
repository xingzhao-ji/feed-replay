import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'review'))
from reference import decode_itch,decode_mold,ReferenceError
PROBE=Path(os.environ.get('FEED_PROBE',Path(os.environ.get('FEED_CACHE',Path.home()/'.cache/job-apps-runtime/feed-replay'))/'build/probe'))
VECTORS=json.loads((ROOT/'review/literal_vectors.json').read_text())['messages']
ANCHORS=json.loads((ROOT/'review/mold_anchors.json').read_text())

def probe(mode,values):
 p=subprocess.run([str(PROBE),mode],input=''.join(v.hex()+'\n' for v in values),text=True,capture_output=True,timeout=20)
 assert p.returncode==0,p.stderr
 rows=[json.loads(line) for line in p.stdout.splitlines()]
 assert len(rows)==len(values)
 return rows

def expected(decoder,data):
 try:return decoder(data)
 except ReferenceError as error:return {'error':error.code}

def test_independent_golden_files_remain_frozen():
 f=json.loads((ROOT/'review/freeze-v1.json').read_text())
 for item in f['files']:assert hashlib.sha256((ROOT/'review'/item['path']).read_bytes()).hexdigest()==item['sha256']

def test_every_literal_field_matches_independent_oracle():
 values=[bytes.fromhex(v['hex']) for v in VECTORS.values()]
 assert probe('itch',values)==[decode_itch(v) for v in values]

def test_all_itch_truncations_and_extra_octets_rejected():
 values=[data[:n] for v in VECTORS.values() for data in [bytes.fromhex(v['hex'])] for n in range(len(data))]
 values += [bytes.fromhex(v['hex'])+b'\0' for v in VECTORS.values()]
 assert probe('itch',values)==[expected(decode_itch,v) for v in values]

def test_literal_mold_and_all_truncated_prefixes():
 data=bytes.fromhex(ANCHORS['multi_message']['hex'])
 values=[data,bytes.fromhex(ANCHORS['heartbeat']['hex']),bytes.fromhex(ANCHORS['end']['hex'])]+[data[:n] for n in range(len(data))]
 assert probe('mold',values)==[expected(decode_mold,v) for v in values]

def test_request_matches_handwritten_octets():
 p=subprocess.run([str(PROBE),'request','REVIEW0001','4','128'],capture_output=True,text=True,timeout=5)
 assert p.returncode==0,p.stderr
 assert json.loads(p.stdout)==ANCHORS['request']['hex']

@pytest.mark.parametrize('first,count,code',[(0,1,'field_domain'),(1,0,'field_domain'),(1,129,'field_domain'),((1<<64)-1,1,'counter_overflow')])
def test_request_rejects_invalid_bounded_range(first,count,code):
 p=subprocess.run([str(PROBE),'request','REVIEW0001',str(first),str(count)],capture_output=True,text=True,timeout=5)
 assert p.returncode==0 and json.loads(p.stdout)=={'error':code}

def test_seeded_decoder_mutations_are_bounded_and_differential():
 rng=random.Random(20261023);values=[];base=bytes.fromhex(ANCHORS['multi_message']['hex'])
 for _ in range(1000):
  data=bytearray(base)
  for _ in range(rng.randrange(1,5)):data[rng.randrange(len(data))]=rng.randrange(256)
  values.append(bytes(data))
 assert probe('mold',values)==[expected(decode_mold,v) for v in values]

@pytest.mark.parametrize('name',['add_bid','nonprintable','replace','zero_cross'])
def test_field_boundary_mutations_match_independent_decoder(name):
 b=bytes.fromhex(VECTORS[name]['hex']);values=[]
 for n in range(len(b)):
  for value in (0,32,255):
   v=bytearray(b);v[n]=value;values.append(bytes(v))
 assert probe('itch',values)==[expected(decode_itch,v) for v in values]
