import json
import random
import struct
import subprocess
import pytest
from test_codec import ROOT,PROBE,VECTORS
from reference import ReferenceBook,ReferenceError,decode_itch

def rows(values,engine='indexed',limits=None,depth=5):
 limits=limits or {};book=ReferenceBook(**limits)
 command=[str(PROBE),'book',engine,str(limits.get('max_orders',100000)),str(limits.get('max_ids',1000000)),str(limits.get('max_instruments',4096)),str(depth)]
 # Bound correctness streams; compare one full snapshot at a time, never persist the stream.
 with subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
  for data in values:
   code=None
   try:book.apply(decode_itch(data))
   except ReferenceError as error:code=error.code
   p.stdin.write(data.hex()+'\n');p.stdin.flush()
   actual=json.loads(p.stdout.readline())
   assert actual=={'error':code,'book':book.snapshot(depth)},(data.hex(),actual,code,book.snapshot(depth))
  p.stdin.close();assert p.wait(timeout=10)==0,p.stderr.read()

@pytest.mark.parametrize('engine',['indexed','scan'])
@pytest.mark.parametrize('depth',[0,1,5,20])
def test_every_literal_lifecycle_state(engine,depth):
 names=json.loads((ROOT/'review/lifecycle_anchors.json').read_text())['events']
 rows([bytes.fromhex(VECTORS[n]['hex']) for n in names],engine,depth=depth)

def header(kind,locate=1,time=1):return kind.encode()+struct.pack('>HH',locate,0)+time.to_bytes(6,'big')
def add(oid,shares,price,locate=1,side='B'):
 return header('A',locate)+struct.pack('>QcI',oid,side.encode(),shares)+(b'ALPHA   ' if locate==1 else b'BETA    ')+struct.pack('>I',price)
def change(kind,oid,shares=0,locate=1,newid=0,price=1):
 base=header(kind,locate)+struct.pack('>Q',oid)
 if kind=='D':return base
 if kind=='U':return base+struct.pack('>QII',newid,shares,price)
 return base+struct.pack('>I',shares)

@pytest.mark.parametrize('engine',['indexed','scan'])
def test_rejections_preserve_levels_and_seen_ids(engine):
 values=[bytes.fromhex(VECTORS['alpha']['hex']),bytes.fromhex(VECTORS['beta']['hex']),add(1,10,0),add(2,20,0),
  add(1,3,1),change('X',1,11),change('X',1,0),change('X',999,0),change('D',1,locate=2),
  change('U',1,5,newid=2),change('U',1,0,newid=3),add(3,7,0),change('U',1,5,newid=1),
  change('D',1),add(1,1,0),change('U',2,1,newid=1),change('U',2,30,newid=4),add(2,1,0)]
 rows(values,engine)

@pytest.mark.parametrize('engine',['indexed','scan'])
def test_limits_and_replacement_at_full_live_capacity(engine):
 directory=bytes.fromhex(VECTORS['alpha']['hex'])
 rows([directory,add(1,10,0),add(2,1,0),change('U',1,20,newid=3),change('D',3),add(4,1,0),add(1,1,0)],engine,{'max_orders':1,'max_ids':2})
 rows([directory,bytes.fromhex(VECTORS['beta']['hex']),directory],engine,{'max_instruments':1})

@pytest.mark.parametrize('engine',['indexed','scan'])
def test_seeded_events_compare_every_state_with_reference(engine):
 rng=random.Random(20261023)
 values=[bytes.fromhex(VECTORS['alpha']['hex']),bytes.fromhex(VECTORS['beta']['hex'])]
 # Deliberate mixed-validity stream keeps at most 64 potential IDs and 1024 events.
 for _ in range(1024):
  oid=(1<<63)+rng.randrange(64);locate=rng.choice([1,2]);kind=rng.choice(['A','X','D','U'])
  if kind=='A':values.append(add(oid,rng.randrange(0,101),rng.choice([0,1,100000,2000000000]),locate,rng.choice(['B','S'])))
  else:values.append(change(kind,oid,rng.randrange(0,101),locate,(1<<63)+rng.randrange(64),rng.randrange(10)))
 rows(values,engine)
