"""Freeze a synthetic workload and independent map-reference observations before timing."""
import argparse
import hashlib
import json
import random
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'review'))
from reference import ReferenceBook,decode_itch
SEED=20261023
PRELOAD=8+2048
UPDATES=50000
SESSION=b'BENCH00001'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def u(value,n):return value.to_bytes(n,'big')
def header(kind,locate,time):return kind.encode()+u(locate,2)+b'\x12\x34'+u(time,6)
def packet(first,events):return SESSION+u(first,8)+u(len(events),2)+b''.join(u(len(e),2)+e for e in events)


def quote_from_reference(book,locate):
    # Read the frozen independent map's admitted orders; rebuild both best quantities.
    # This avoids 50,000 full snapshots, without reusing any product level algorithm.
    levels={'B':{},'S':{}}
    for order in book.model.orders.values():
        if order['locate']==locate:
            side=levels[order['side']];price=order['price']
            side[price]=side.get(price,0)+order['quantity']
    def best(side):
        if not levels[side]:return ('-','-')
        price=(max if side=='B' else min)(levels[side])
        return str(price),str(levels[side][price])
    return (*best('B'),*best('S'))


def freeze(directory):
    directory.mkdir(parents=True,exist_ok=False)
    randomizer=random.Random(SEED);book=ReferenceBook();events=[];slots=[];next_id=2**63+1
    symbols={i:f'SYM{i:05d}'.encode() for i in range(1,9)}
    def emit(event):
        book.apply(decode_itch(event));events.append(event)
    def clock():return randomizer.randrange(86_400_000_000_000)
    def price():return randomizer.choice([0,2_000_000_000]) if randomizer.randrange(100)==0 else 100000+randomizer.randrange(100)*10
    def add(locate,side,attributed):
        nonlocal next_id
        ident=next_id;next_id+=1
        data=header('F' if attributed else 'A',locate,clock())+u(ident,8)+side.encode()+u(randomizer.randint(50,500),4)+symbols[locate]+u(price(),4)
        if attributed:data+=b'ABCD'
        emit(data);return ident
    for locate in range(1,9):emit(header('R',locate,clock())+symbols[locate]+b'\0'*20)
    for index in range(2048):slots.append(add(index%8+1,'B' if (index//8)%2==0 else 'S',index%3==0))
    queries=directory/'oracle-quotes.tsv';pending=None
    with queries.open('x') as output:
        for index in range(UPDATES):
            kind=index%10
            if kind==5:
                slot,locate,side=pending;slots[slot]=add(locate,side,index%3==0);pending=None
            else:
                slot=randomizer.randrange(len(slots));ident=slots[slot]
                order=book.model.orders[ident];locate=order['locate'];h=lambda t:header(t,locate,clock())
                if kind in (0,6):
                    replacement=next_id;next_id+=1
                    emit(h('U')+u(ident,8)+u(replacement,8)+u(randomizer.randint(50,500),4)+u(price(),4));slots[slot]=replacement
                elif kind in (1,2,3):
                    quantity=randomizer.randint(0,min(order['quantity']-1,50));typ={1:'E',2:'C',3:'X'}[kind]
                    data=h(typ)+u(ident,8)+u(quantity,4)
                    if typ in 'EC':data+=u(index,8)
                    if typ=='C':data+=(b'Y' if index%4==0 else b'N')+u(price(),4)
                    emit(data)
                elif kind==4:
                    pending=(slot,locate,order['side']);emit(h('D')+u(ident,8))
                elif kind==7:emit(h('P')+u(0,8)+b'B'+u(10,4)+symbols[locate]+u(price(),4)+u(index,8))
                elif kind==8:emit(h('Q')+u(0 if index%4==0 else 100,8)+symbols[locate]+u(price(),4)+u(index,8)+b'O')
                else:emit(h('B')+u(index,8))
            query_locate=index%8+1
            values=quote_from_reference(book,query_locate)
            # Periodic cross-check against the frozen author's complete snapshot method.
            if index<16 or index%1000==0:
                instrument=next(i for i in book.snapshot(0)['instruments'] if i['locate']==query_locate)
                expected=[]
                for key in ('best_bid','best_ask'):
                    level=instrument[key];expected.extend(('-', '-') if level is None else (str(level['price']),level['quantity']))
                assert values==tuple(expected)
            output.write(' '.join(map(str,(index,query_locate,*values,0,0)))+'\n')
    raw=directory/'workload.frcp'
    with raw.open('xb') as output:
        output.write(b'FRCP0001')
        for offset in range(0,len(events),128):
            data=packet(offset+1,events[offset:offset+128]);output.write(b'\0'+u(len(data),4)+data)
        end=SESSION+u(len(events)+1,8)+b'\xff\xff';output.write(b'\0'+u(len(end),4)+end)
    final=directory/'oracle-final.json';final.write_text(json.dumps(book.snapshot(0),sort_keys=True,separators=(',',':'))+'\n')
    manifest={'schema_version':1,'seed':SEED,'preload_events':PRELOAD,'initial_live_orders':2048,'instruments':8,'updates':UPDATES,'query_frequencies':[1,32,256],'query_locate':'update_index modulo 8 plus 1','query_depth':0,'timing_policy':'one warmup pair, eight measured pairs per frequency, alternating indexed/scan order; no tuning after timing','reference_freeze_sha256':sha(ROOT/'review/freeze-v1.json'),'generator_sha256':sha(Path(__file__)),'files':{p.name:sha(p) for p in (raw,queries,final)},'reference_every_event_applied':len(events),'reference_quotes_checked':UPDATES,'scope':'synthetic displayed-book workload; no exchange traffic'}
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path)
    freeze(parser.parse_args().directory)
