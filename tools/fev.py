import struct, sys, os, json

FREQS = {1:8000,2:11000,3:11025,4:16000,5:22050,6:24000,7:32000,8:44100,9:48000,10:96000}
CODECS = {1:'PCM8',2:'PCM16',3:'PCM24',4:'PCM32',5:'PCMFLOAT',6:'GCADPCM',7:'IMAADPCM',8:'VAG',9:'HEVAG',10:'XMA',11:'MPEG',12:'CELT',13:'AT9',14:'XWMA',15:'VORBIS',16:'FADPCM',17:'OPUS'}

def parse_riff(data):
    """Return list of (fourcc, offset_of_payload, size, [children]) for a RIFF FEV file."""
    assert data[:4] == b'RIFF', data[:4]
    total = struct.unpack_from('<I', data, 4)[0]
    form = data[8:12]
    def walk(start, end):
        out = []
        p = start
        while p + 8 <= end:
            cc = data[p:p+4]
            sz = struct.unpack_from('<I', data, p+4)[0]
            payload = p + 8
            children = None
            if cc == b'LIST':
                listtype = data[payload:payload+4]
                children = walk(payload+4, payload+sz)
                out.append((cc + b':' + listtype, payload, sz, children))
            else:
                out.append((cc, payload, sz, None))
            p = payload + sz + (sz & 1)
        return out
    return form, total, walk(12, 8 + total)

def print_tree(tree, indent=0):
    for cc, off, sz, ch in tree:
        print(' ' * indent + f'{cc.decode(errors="replace"):12s} off={off:<10d} size={sz}')
        if ch:
            print_tree(ch, indent + 2)

def find_chunks(tree, cc):
    res = []
    for c, off, sz, ch in tree:
        if c == cc:
            res.append((off, sz))
        if ch:
            res.extend(find_chunks(ch, cc))
    return res

class FSB5:
    def __init__(self, data, base=0):
        self.data = data; self.base = base
        magic, self.version, self.num, self.shdr_size, self.name_size, self.data_size, self.mode = struct.unpack_from('<4sIIIIII', data, base)
        assert magic == b'FSB5', magic
        self.zero = data[base+28:base+36]
        self.hash = data[base+36:base+52]
        self.dummy = data[base+52:base+60]
        hdr = 60
        if self.version == 0:
            self.extra = data[base+60:base+64]; hdr = 64
        self.hdr_len = hdr
        self.shdr_off = base + hdr
        self.name_off = self.shdr_off + self.shdr_size
        self.data_off = self.name_off + self.name_size
        self.samples = []
        p = self.shdr_off
        for i in range(self.num):
            raw = struct.unpack_from('<Q', data, p)[0]
            p += 8
            nxt = raw & 1
            freq = (raw >> 1) & 0xF
            chbit = (raw >> 5) & 1
            off16 = ((raw >> 6) & 0x0FFFFFFF) * 16
            nsamp = (raw >> 34) & 0x3FFFFFFF
            chunks = []
            while nxt:
                c = struct.unpack_from('<I', data, p)[0]; p += 4
                nxt = c & 1
                csz = (c >> 1) & 0x00FFFFFF
                ctype = (c >> 25) & 0x7F
                chunks.append((ctype, data[p:p+csz]))
                p += csz
            self.samples.append(dict(raw=raw, freq=FREQS.get(freq, freq), channels=chbit+1, off=off16, nsamp=nsamp, chunks=chunks))
        assert p == self.name_off, (p, self.name_off)
        # names
        if self.name_size:
            offs = struct.unpack_from('<%dI' % self.num, data, self.name_off)
            for i, s in enumerate(self.samples):
                o = self.name_off + offs[i]
                e = data.index(b'\0', o)
                s['name'] = data[o:e].decode('latin1')
        for i, s in enumerate(self.samples):
            nxt_off = self.samples[i+1]['off'] if i+1 < self.num else self.data_size
            s['size'] = nxt_off - s['off']
            for ct, cd in s['chunks']:
                if ct == 1: s['channels'] = cd[0]
                if ct == 2: s['freq'] = struct.unpack('<I', cd)[0]
                if ct == 11: s['vorbis_crc'] = struct.unpack_from('<I', cd)[0]; s['vorbis_extra'] = len(cd) - 4
        self.total_len = hdr + self.shdr_size + self.name_size + self.data_size

    def sample_data(self, i):
        s = self.samples[i]
        return self.data[self.data_off + s['off']: self.data_off + s['off'] + s['size']]

    def summary(self):
        return dict(version=self.version, num=self.num, codec=CODECS.get(self.mode, self.mode), shdr_size=self.shdr_size, name_size=self.name_size, data_size=self.data_size, hash=self.hash.hex(), zero=self.zero.hex(), dummy=self.dummy.hex(), total_len=self.total_len)

def load_bank(path):
    data = open(path, 'rb').read()
    form, total, tree = parse_riff(data)
    return data, form, total, tree

if __name__ == '__main__':
    path = sys.argv[1]
    data, form, total, tree = load_bank(path)
    print(f'{path}: form={form} riff_total={total} filesize={len(data)}')
    print_tree(tree)
    for off, sz in find_chunks(tree, b'FMT '):
        print('FMT bytes:', data[off:off+sz].hex())
    for off, sz in find_chunks(tree, b'SND '):
        # FSB5 may be aligned inside the chunk
        p = data.find(b'FSB5', off, off+64)
        if p < 0:
            print('SND chunk without FSB5 at start', data[off:off+32].hex()); continue
        f = FSB5(data, p)
        print('FSB5 @', p, 'pad', p-off, json.dumps(f.summary()))
        crcs = {}
        for s in f.samples:
            crcs[s.get('vorbis_crc')] = crcs.get(s.get('vorbis_crc'), 0) + 1
        print(' vorbis crcs:', crcs)
        freqs = {}
        for s in f.samples:
            k = (s['freq'], s['channels']); freqs[k] = freqs.get(k, 0) + 1
        print(' (freq,ch):', freqs)
        if '--names' in sys.argv:
            for i, s in enumerate(f.samples):
                print(f"  [{i}] {s.get('name','?'):40s} off={s['off']:<9d} size={s['size']:<8d} nsamp={s['nsamp']:<8d} {s['freq']}Hz ch={s['channels']} chunks={[c[0] for c in s['chunks']]}")
