"""Port the 2024 'bubuki' War Thunder crew-voice mod onto the current game's bank layout.

For every current locale bank (_crew_dialogs_<kind>_<loc>.assets.bank) the key list, slot order and
sample table are kept untouched and only the audio is swapped: slots whose key the old mod covered get
the old mod's clip, everything else gets a short silent clip.
"""
import sys, os, json, difflib, glob, shutil, struct, argparse, zlib
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fev import *
from fsbwrite import read_assets, write_fsb, rebuild_assets_bank
from events import parse_bank


def split_key(k):
    return (k.rsplit('/', 1)[0], k.rsplit('/', 1)[1]) if '/' in k else ('', k)


def resolve_events(bank, assets=None):
    result, objs, unreached, sheets, sheet_event = parse_bank(bank, assets)
    return {g: v['items'] for g, v in result.items()}


def derive_map(new_ev, old_ev):
    """full key -> clip name (or None = muted). Keys come from programmer-instrument names in the current bank."""
    votes = defaultdict(list)
    stats = Counter()
    covered_events = {}
    for g, items in new_ev.items():
        keys = [x for k, x in items if k == 'key']
        if not keys:
            stats['current events without programmer keys (ignored)'] += 1
            continue
        old = old_ev.get(g)
        clips = [x for k, x in old if k == 'wave'] if old else []
        if old is None:
            stats['current events absent from old mod -> muted'] += 1
        elif not clips:
            stats['events the old mod left stock -> muted'] += 1
        else:
            stats['events covered by old mod clips'] += 1
            covered_events[g] = (keys, clips)
        # rotate the clip list per event so that events with fewer keys than clips do not all
        # end up on the same first clip (the old mod picked randomly among its clips)
        start = zlib.crc32(g.encode()) % len(clips) if clips else 0
        for i, k in enumerate(keys):
            votes[k].append(clips[(start + i) % len(clips)] if clips else None)
    full_map = {}
    conflicts = 0
    for k, lst in votes.items():
        real = [c for c in lst if c]
        if real:
            c = Counter(real).most_common()
            full_map[k] = c[0][0]
            if len(c) > 1:
                conflicts += 1
        else:
            full_map[k] = None
    base_votes = defaultdict(list)
    top_votes = defaultdict(list)
    for k, c in full_map.items():
        if c:
            d, b = split_key(k)
            base_votes[b].append(c)
            top_votes[(d.split('/')[0], b)].append(c)
    base_map = {b: Counter(v).most_common(1)[0][0] for b, v in base_votes.items()}
    top_map = {t: Counter(v).most_common(1)[0][0] for t, v in top_votes.items()}
    stats['distinct full keys referenced'] = len(full_map)
    stats['keys -> old mod clip'] = sum(1 for v in full_map.values() if v)
    stats['keys muted'] = sum(1 for v in full_map.values() if not v)
    stats['keys with conflicting clips across events (majority used)'] = conflicts
    return full_map, base_map, top_map, stats, covered_events


def align_slots(fsb_names, keys_sorted):
    """The audio table is laid out in plain ASCII order of the full keys; FSB names are the basenames."""
    bases = [split_key(k)[1] for k in keys_sorted]
    sm = difflib.SequenceMatcher(None, fsb_names, bases, autojunk=False)
    slot_key = [None] * len(fsb_names)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for a in range(i2 - i1):
                slot_key[i1 + a] = keys_sorted[j1 + a]
    return slot_key


def load_silence(path_fmod, path_json):
    meta = json.load(open(path_json))
    data = open(path_fmod, 'rb').read()
    return dict(freq=meta['rate'], ch=meta['ch'], nsamp=meta['nsamp'], data=data,
                chunks=[(11, struct.pack('<II', meta['crc'], 0)), (13, struct.pack('<f', 0.001))])


def port_locale(src_path, dst_path, full_map, base_map, top_map, clips, silence, use_halves):
    src = read_assets(src_path)
    names = [s['name'] for s in src['samples']]
    slot_key = align_slots(names, sorted(full_map))
    n = len(names)
    h = n // 2
    halves = use_halves and n % 2 == 0 and all(names[i] == names[i + h] for i in range(h))
    out_samples = []
    counts = Counter()
    per_slot = []
    for i, s in enumerate(src['samples']):
        key = slot_key[i]
        if key is not None:
            clip = full_map[key]
            how = 'key' if clip else 'key-muted'
        else:
            clip = None
            if halves:
                clip = top_map.get(('high' if i < h else 'med', s['name']))
            if clip is None:
                clip = base_map.get(s['name'])
            how = 'fallback' if clip else 'extra-muted'
        counts[how] += 1
        base = clips[clip] if clip else silence
        out_samples.append(dict(base, name=s['name']))
        per_slot.append((i, s['name'], key or '', clip or '', how))
    fsb = write_fsb(out_samples, src['header_tail'], src['fsb'].version, src['fsb'].mode)
    out = rebuild_assets_bank(src, fsb)
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    open(dst_path, 'wb').write(out)
    assigned = set(k for k in slot_key if k)
    missing_keys = [k for k in full_map if k not in assigned]
    return counts, per_slot, missing_keys, len(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', default='C:/Games/WarThunder')
    ap.add_argument('--old', default=None, help='old mod folder (default <game>/bubuki/old)')
    ap.add_argument('--out', default=None, help='output folder (default <game>/bubuki/new)')
    ap.add_argument('--silence', required=True, help='folder with silence_44100_1.fmod/.json')
    ap.add_argument('--report', default=None, help='folder for reports (default <out>/report)')
    a = ap.parse_args()
    game = a.game
    old = a.old or f'{game}/bubuki/old'
    out = a.out or f'{game}/bubuki/new'
    rep = a.report or f'{out}/report'
    os.makedirs(rep, exist_ok=True)
    silence = load_silence(f'{a.silence}/silence_44100_1.fmod', f'{a.silence}/silence_44100_1.json')
    families = [
        dict(kind='ground', new_bank=f'{game}/sound/crew_dialogs_ground.bank', old_bank=f'{old}/crew_dialogs_ground.bank',
             old_assets=f'{old}/crew_dialogs_ground.assets.bank', subdir='', halves=True),
        dict(kind='common', new_bank=f'{game}/sound/crew_dialogs_common.bank', old_bank=f'{old}/Radio Voice/crew_dialogs_common.bank',
             old_assets=f'{old}/Radio Voice/crew_dialogs_common.assets.bank', subdir='Radio Voice', halves=False),
    ]
    summary = {}
    for fam in families:
        kind = fam['kind']
        print(f'===== {kind} =====')
        new_ev = resolve_events(fam['new_bank'])
        old_ev = resolve_events(fam['old_bank'], fam['old_assets'])
        full_map, base_map, top_map, stats, covered = derive_map(new_ev, old_ev)
        for k, v in stats.items():
            print(f'  {v:5d}  {k}')
        clips = {s['name']: s for s in read_assets(fam['old_assets'])['samples']}
        used = Counter(v for v in full_map.values() if v)
        print(f'  old clips available {len(clips)}, used {len(used)}: {sorted(used)}')
        with open(f'{rep}/keys_{kind}.tsv', 'w') as fh:
            fh.write('key\tclip\n')
            for k in sorted(full_map):
                fh.write(f'{k}\t{full_map[k] or "(muted)"}\n')
        with open(f'{rep}/events_{kind}.tsv', 'w') as fh:
            fh.write('event_guid\tstatus\tcurrent_keys\told_mod_clips\n')
            for g, items in sorted(new_ev.items()):
                keys = [x for k, x in items if k == 'key']
                if not keys:
                    continue
                o = old_ev.get(g)
                oc = [x for k, x in o if k == 'wave'] if o else []
                st = 'covered' if oc else ('old-mod-left-stock' if o else 'not-in-old-mod')
                fh.write(f'{g}\t{st}\t{";".join(keys)}\t{";".join(oc)}\n')
        loc_rows = []
        for src_path in sorted(glob.glob(f'{game}/sound/_crew_dialogs_{kind}_*.assets.bank')):
            base = os.path.basename(src_path)
            loc = base[len(f'_crew_dialogs_{kind}_'):-len('.assets.bank')]
            dst_dir = os.path.join(out, fam['subdir']) if fam['subdir'] else out
            counts, per_slot, missing, size = port_locale(src_path, os.path.join(dst_dir, base), full_map, base_map, top_map, clips, silence, fam['halves'])
            meta = src_path[:-len('.assets.bank')] + '.bank'
            shutil.copyfile(meta, os.path.join(dst_dir, os.path.basename(meta)))
            with open(f'{rep}/slots_{kind}_{loc}.tsv', 'w') as fh:
                fh.write('slot\tname\tfull_key\tclip\thow\n')
                for r in per_slot:
                    fh.write('\t'.join(map(str, r)) + '\n')
            row = dict(locale=loc, slots=len(per_slot), via_key=counts['key'], via_fallback=counts['fallback'], muted_key=counts['key-muted'],
                       muted_extra=counts['extra-muted'], keys_not_in_locale=len(missing), bytes=size)
            loc_rows.append(row)
            print(f"  {loc:8s} slots={row['slots']:5d} clip:key={row['via_key']:4d} clip:fallback={row['via_fallback']:4d} "
                  f"muted(key)={row['muted_key']:4d} muted(extra)={row['muted_extra']:4d} keys-missing-in-locale={row['keys_not_in_locale']:3d} -> {size/1e6:.1f} MB")
        summary[kind] = dict(stats=dict(stats), clips_used=dict(used), clips_available=len(clips), locales=loc_rows)
    json.dump(summary, open(f'{rep}/summary.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
