"""Generate silent Vorbis clips in FMOD FSB5 packet framing (u16 size + packet), with setup CRCs FMOD knows."""
import subprocess, zlib, struct, json, sys, os, tempfile

def ogg_pages(data):
    p = 0
    while p + 27 <= len(data):
        assert data[p:p+4] == b'OggS'
        granule = struct.unpack_from('<q', data, p+6)[0]
        nseg = data[p+26]; segs = data[p+27:p+27+nseg]; q = p+27+nseg
        body = data[q:q+sum(segs)]
        yield granule, segs, body
        p = q + sum(segs)

def ogg_packets(data):
    packets = []; cur = b''; last_granule = 0
    for granule, segs, body in ogg_pages(data):
        q = 0
        for s in segs:
            cur += body[q:q+s]; q += s
            if s < 255: packets.append(cur); cur = b''
        last_granule = granule
    return packets, last_granule

def make_silence(rate, ch, seconds=0.1):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'anullsrc=r={rate}:cl={"stereo" if ch == 2 else "mono"}', '-t', str(seconds), '-c:a', 'libvorbis', '-q:a', '-1', '-f', 'ogg', '-'], capture_output=True, check=True)
    pk, granule = ogg_packets(r.stdout)
    ident, comment, setup = pk[:3]
    crc = zlib.crc32(setup) & 0xffffffff
    audio = pk[3:]
    fmod = b''.join(struct.pack('<H', len(a)) + a for a in audio)
    return dict(rate=rate, ch=ch, crc=crc, nsamp=granule, packets=len(audio), fmod=fmod, headers=[ident, comment, setup])

def fmod_to_ogg(fmod_data, headers, nsamp):
    """Wrap FMOD-framed packets back into an Ogg stream (for verification with ffmpeg)."""
    packets = []
    q = 0
    while q + 2 <= len(fmod_data):
        n = struct.unpack_from('<H', fmod_data, q)[0]
        if n == 0 and q + 2 + n >= len(fmod_data) - 32: break
        packets.append(fmod_data[q+2:q+2+n]); q += 2 + n
    def page(packets_in_page, granule, seq, flags=0):
        segs = b''
        body = b''
        for pkt in packets_in_page:
            n = len(pkt)
            while n >= 255: segs += b'\xff'; n -= 255
            segs += bytes([n]); body += pkt
        hdr = b'OggS' + bytes([0, flags]) + struct.pack('<q', granule) + struct.pack('<I', 1) + struct.pack('<I', seq) + b'\0\0\0\0' + bytes([len(segs)]) + segs
        pg = bytearray(hdr + body)
        crc = 0
        for byte in pg:
            crc ^= byte << 24
            for _ in range(8):
                crc = ((crc << 1) ^ 0x04c11db7) if crc & 0x80000000 else (crc << 1)
                crc &= 0xffffffff
        pg[22:26] = struct.pack('<I', crc)
        return bytes(pg)
    out = page([headers[0]], 0, 0, 2) + page(headers[1:3], 0, 1)
    seq = 2
    # paginate: at most ~200 segments (lacing values) per page
    groups = []; cur = []; segs = 0
    for pkt in packets:
        need = len(pkt) // 255 + 1
        if segs + need > 200 and cur:
            groups.append(cur); cur = []; segs = 0
        cur.append(pkt); segs += need
    if cur: groups.append(cur)
    for gi, g in enumerate(groups):
        last = gi == len(groups) - 1
        out += page(g, nsamp if last else -1, seq, 4 if last else 0); seq += 1
    return out

if __name__ == '__main__':
    outdir = sys.argv[1]; os.makedirs(outdir, exist_ok=True)
    known = {1005931288: (44100, 2), 2016338926: (44100, 1), 894604746: (48000, 1)}
    for rate, ch in [(44100, 1), (44100, 2), (48000, 1)]:
        s = make_silence(rate, ch)
        ok = s['crc'] in known and known[s['crc']] == (rate, ch)
        print(f"{rate}Hz ch={ch}: crc={s['crc']} known={ok} nsamp={s['nsamp']} packets={s['packets']} fmod_bytes={len(s['fmod'])}")
        base = f'{outdir}/silence_{rate}_{ch}'
        open(base + '.fmod', 'wb').write(s['fmod'])
        json.dump({'rate': rate, 'ch': ch, 'crc': s['crc'], 'nsamp': s['nsamp']}, open(base + '.json', 'w'))
        ogg = fmod_to_ogg(s['fmod'], s['headers'], s['nsamp'])
        open(base + '.ogg', 'wb').write(ogg)
        r = subprocess.run(['ffmpeg', '-v', 'error', '-i', base + '.ogg', '-af', 'astats=metadata=1:reset=0', '-f', 'null', '-'], capture_output=True, text=True)
        r2 = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=duration,sample_rate,channels', '-of', 'csv=p=0', base + '.ogg'], capture_output=True, text=True)
        print('   decode:', r.returncode, r.stderr.strip()[:200] or 'ok', '| probe:', r2.stdout.strip())
        r3 = subprocess.run(['ffmpeg', '-v', 'error', '-i', base + '.ogg', '-f', 's16le', '-'], capture_output=True)
        pcm = r3.stdout
        print('   decoded pcm bytes', len(pcm), '-> frames', len(pcm)//(2*ch), 'max abs', max(abs(x) for x in struct.unpack(f'<{len(pcm)//2}h', pcm)) if pcm else None)
