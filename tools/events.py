"""Resolve FMOD Studio bank events -> leaf instruments (programmer keys / embedded waveforms)."""
import sys, os, struct, json
sys.path.insert(0, os.path.dirname(__file__))
from fev import *

INST_LISTS = {'LIST:MUIT', 'LIST:PRIT', 'LIST:WAIT', 'LIST:EVIT', 'LIST:SPIT', 'LIST:CMIT', 'LIST:SLIT', 'LIST:SNIT', 'LIST:EFIT'}
BODY = {'MUIB', 'PRIB', 'WAIB', 'EVIB', 'SPIB', 'CMIB', 'SLIB', 'SNIB', 'EFIB'}

def list_entries(b, hdr_off):
    """Generic FMOD list: u16 (2n+1), u16 entry_size, entries..."""
    flags, esz = struct.unpack_from('<HH', b, hdr_off)
    n = (flags - 1) // 2
    return [b[hdr_off + 4 + i*esz: hdr_off + 4 + (i+1)*esz] for i in range(n)]

def parse_bank(path, assets_path=None):
    data, form, total, tree = load_bank(path)
    objs, events, timelines, sheets = {}, {}, {}, {}
    def walk(t, p, cur):
        for cc, off, sz, ch in t:
            name = cc.decode(errors='replace')
            if name in INST_LISTS:
                cur = {'type': name[5:], 'guid': None, 'parent': None, 'children': [], 'name': None, 'wave': None}
            if ch is not None:
                walk(ch, p + [name], cur); continue
            b = data[off:off+sz]
            if name == 'EVTB':
                events[b[0:16].hex()] = {'guid': b[0:16].hex(), 'timeline': b[32:48].hex(), 'raw': b}
            elif name == 'TLNB':
                timelines[b[0:16].hex()] = [e[0:16].hex() for e in list_entries(b, 16)]
            elif name == 'PMLB':
                sheets[b[0:16].hex()] = [e[0:16].hex() for e in list_entries(b, 32)]
            elif name in BODY:
                cur['guid'] = b[0:16].hex()
                if name == 'PRIB':
                    n = struct.unpack_from('<H', b, 16)[0]; cur['name'] = b[18:18+n].decode('latin1')
                if name == 'WAIB': cur['wave'] = b[16:32].hex()
                if name == 'EVIB': cur['ref'] = b[16:32].hex()
                objs[cur['guid']] = cur
            elif name == 'PLST':
                if len(b) >= 12:
                    for e in list_entries(b, 8):
                        cur['children'].append((e[0:16].hex(), struct.unpack('<f', e[16:20])[0]))
            elif name == 'INST':
                cur['parent'] = b[0:16].hex()
    walk(tree, [], None)
    wave_names = {}
    if assets_path:
        adata, aform, atotal, atree = load_bank(assets_path)
        (soff, ssz), = find_chunks(atree, b'SND ')
        f = FSB5(adata, adata.find(b'FSB5', soff, soff+64))
        for off, sz in find_chunks(atree, b'WAV '):
            b = adata[off:off+sz]
            wave_names[b[0:16].hex()] = f.samples[struct.unpack_from('<I', b, 22)[0]]['name']
    # sheet -> event (EVTB references sheet guid)
    sheet_event = {}
    for sg in sheets:
        gb = bytes.fromhex(sg)
        for eg, ev in events.items():
            if gb in ev['raw'][80:]:
                sheet_event[sg] = eg; break
    def expand(o):
        if o['type'] == 'MUIT':
            out = []
            for cg, w in o['children']:
                c = objs.get(cg)
                out.extend(expand(c) if c else [('missing', cg)])
            return out
        if o['type'] == 'PRIT': return [('key', o['name'])]
        if o['type'] == 'WAIT': return [('wave', wave_names.get(o['wave'], 'wave:' + o['wave']))]
        return [(o['type'], o.get('ref') or o['guid'])]
    result = {}
    for g, ev in events.items():
        tops = list(timelines.get(ev['timeline'], []))
        for sg, lst in sheets.items():
            if sheet_event.get(sg) == g: tops.extend(lst)
        items = []
        for tg in tops:
            o = objs.get(tg)
            items.extend(expand(o) if o else [('missing', tg)])
        result[g] = {'timeline': ev['timeline'], 'items': items}
    reached = set()
    def mark(o):
        reached.add(o['guid'])
        for cg, w in o['children']:
            if cg in objs: mark(objs[cg])
    for v in result.values(): pass
    for g, ev in events.items():
        for tg in list(timelines.get(ev['timeline'], [])) + [x for sg, l in sheets.items() if sheet_event.get(sg) == g for x in l]:
            if tg in objs: mark(objs[tg])
    unreached = [g for g in objs if g not in reached]
    return result, objs, unreached, sheets, sheet_event

if __name__ == '__main__':
    path = sys.argv[1]; assets = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != '-' else None
    out = sys.argv[3] if len(sys.argv) > 3 else None
    result, objs, unreached, sheets, sheet_event = parse_bank(path, assets)
    from collections import Counter
    print(path, 'events', len(result), 'objs', len(objs), 'sheets', len(sheets), 'sheets linked', len(sheet_event))
    print(' unreached instruments:', len(unreached), Counter(objs[g]['type'] for g in unreached))
    print(' leaf kinds:', Counter(k for v in result.values() for k, _ in v['items']))
    print(' events with 0 items:', sum(1 for v in result.values() if not v['items']))
    if out:
        json.dump({g: {'timeline': v['timeline'], 'items': v['items']} for g, v in result.items()}, open(out, 'w'), indent=1)
