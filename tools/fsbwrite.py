"""FSB5 (Vorbis) writer + FMOD .assets.bank container rebuild."""
import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fev import *

FREQ_IDX = {8000: 1, 11000: 2, 11025: 3, 16000: 4, 22050: 5, 24000: 6, 32000: 7, 44100: 8, 48000: 9, 96000: 10}

def read_assets(path):
    data, form, total, tree = load_bank(path)
    (soff, ssz), = find_chunks(tree, b'SND ')
    p = data.find(b'FSB5', soff, soff + 64)
    f = FSB5(data, p)
    samples = []
    for i, s in enumerate(f.samples):
        samples.append(dict(name=s['name'], freq=s['freq'], ch=s['channels'], nsamp=s['nsamp'], chunks=list(s['chunks']), data=f.sample_data(i)))
    return dict(data=data, tree=tree, snd_off=soff, snd_size=ssz, fsb_off=p, fsb=f, samples=samples, header_tail=data[p+28:p+60])

def write_fsb(samples, header_tail, version=1, mode=15):
    assert len(header_tail) == 32
    shdr = bytearray(); blobs = []; off = 0
    for s in samples:
        d = s['data']; d = d + b'\0' * ((-len(d)) % 32)
        assert off % 16 == 0
        raw = (1 if s['chunks'] else 0) | (FREQ_IDX[s['freq']] << 1) | ((s['ch'] - 1) << 5) | ((off // 16) << 6) | (s['nsamp'] << 34)
        shdr += struct.pack('<Q', raw)
        for i, (ct, cd) in enumerate(s['chunks']):
            nxt = 1 if i + 1 < len(s['chunks']) else 0
            shdr += struct.pack('<I', nxt | (len(cd) << 1) | (ct << 25)) + cd
        blobs.append(d); off += len(d)
    names = bytearray(); strs = bytearray(); base = 4 * len(samples)
    for s in samples:
        names += struct.pack('<I', base + len(strs)); strs += s['name'].encode('latin1') + b'\0'
    names += strs
    hdr_len = 60 if version == 1 else 64
    pad = (-(hdr_len + len(shdr) + len(names))) % 32
    names += b'\0' * pad
    header = b'FSB5' + struct.pack('<IIIIII', version, len(samples), len(shdr), len(names), off, mode) + header_tail
    return header + bytes(shdr) + bytes(names) + b''.join(blobs)

def rebuild_assets_bank(src, new_fsb):
    """src: dict from read_assets. Returns new file bytes with the SND payload replaced and sizes fixed."""
    data = src['data']; soff = src['snd_off']; ssz = src['snd_size']; p = src['fsb_off']
    gap = data[soff:p]
    old_fsb_len = src['fsb'].total_len
    assert soff + ssz == p + old_fsb_len, 'unexpected trailing bytes in SND chunk'
    payload = gap + new_fsb
    out = bytearray(data[:soff - 8])
    out += b'SND ' + struct.pack('<I', len(payload)) + payload
    if len(payload) & 1: out += b'\0'
    out += data[soff + ssz + (ssz & 1):]
    struct.pack_into('<I', out, 4, len(out) - 8)
    # SNDH: u16 3, u16 8, u32 fsb_offset, u32 fsb_len
    (hoff, hsz), = find_chunks(src['tree'], b'SNDH')
    assert hsz == 12 and struct.unpack_from('<I', data, hoff + 4)[0] == p and struct.unpack_from('<I', data, hoff + 8)[0] == old_fsb_len, 'SNDH mismatch'
    struct.pack_into('<I', out, hoff + 8, len(new_fsb))
    return bytes(out)

if __name__ == '__main__':
    # identity test
    for path in sys.argv[1:]:
        src = read_assets(path)
        fsb = write_fsb(src['samples'], src['header_tail'], src['fsb'].version, src['fsb'].mode)
        orig = src['data'][src['fsb_off']: src['fsb_off'] + src['fsb'].total_len]
        same_fsb = fsb == orig
        out = rebuild_assets_bank(src, fsb)
        print(f'{path}: fsb identical={same_fsb} len {len(fsb)} vs {len(orig)}; file identical={out == src["data"]} len {len(out)} vs {len(src["data"])}')
        if not same_fsb:
            for i in range(min(len(fsb), len(orig))):
                if fsb[i] != orig[i]: print('  first diff at', i, 'hdr/shdr/names/data boundaries', 60, 60 + src['fsb'].shdr_size, 60 + src['fsb'].shdr_size + src['fsb'].name_size); break
