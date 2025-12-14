#!/bin/env python3

import sys
import struct

from amaranth import *

from amaranth.sim import *

sys.path.append(".")
sys.path.append("streams/streams")

from streams.stream import Stream
from streams.sim import SinkSim, SourceSim

from streams.spdif import PREAMBLE, SPDIF_Rx, SPDIF_Tx,  SubframeReader, BlockReader, BitsReader, SubframeWriter

#
#

import random

def sim_subframe(m):
    print("test subframe")
    sim = Simulator(m)

    sink = SinkSim(m.o)

    state = {
        'drive' : False,
        'jitter' : 2,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()

    def proc():

        half = 35

        def period():
            return random.randint(half - state['jitter'], half + state['jitter'])

        def toggle():
            state['drive'] = not state['drive']
            yield m.i.eq(state['drive'])

        def bit(value):
            yield from tick(period())
            if value:
                yield from toggle()
            yield from tick(period())
            yield from toggle()

        B = [ 3, 1, 1, 3 ]
        M = [ 3, 3, 1, 1 ]
        W = [ 3, 2, 1, 2 ]

        def tx(seq):
            for p in seq:
                yield from tick(period() * p)
                yield from toggle()

        def tx_subframe(preamble, data):
            #print(preamble, data)
            yield from tx(preamble)
            for i in range(28):
                yield from bit(data & 0x01)
                data >>= 1

        def gen(s1, s2):
            for i in range(16):
                if (i % 4) == 0:
                    yield [ B, s1, s2 ]
                else:
                    yield [ M, s1, s2 ]

        def subframe(aux, audio, v, u, c):
            data = aux + (audio << 4) + (v << 24) + (u << 25) + (c << 26)
            parity = 0
            d = data
            while d:
                parity ^= (d & 0x01)
                d >>= 1
            data += (parity << 27) 
            #print(hex(data))
            return data

        yield from tick(10)

        #data = gen(subframe(0x0, 0x0, 1, 0, 0), subframe(0x0, 0x0, 1, 0, 0))
        data = gen(subframe(0x4, 0x0aaaaa, 1, 0, 1), subframe(0x1, 0x12345, 1, 1, 0))

        for preamble, s1, s2 in data:
            yield from tx_subframe(preamble, s1)
            yield from tx_subframe(W, s2)

        yield from tick(10)

        d = sink.get_data()
        #for p in d:
        #    print("packet")
        #    for x in p:
        #        print(x)

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/spdif.vcd", traces=[]):
        sim.run()

#
#

def sim_block(m):
    print("test block")
    sim = Simulator(m)

    source = SourceSim(m.i)
    sink_a = SinkSim(m.audio)
    sink_s = SinkSim(m.status)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink_a.poll()
            yield from sink_s.poll()
            yield from source.poll()

    def proc():

        left = 0x00001
        right = 0x10000

        data = []

        for i in range(20):
            data.append([ 1, 0x00, left, 1, 0, 0, ])
            data.append([ 2, 0x00, right, 1, 0, 0, ])
            left += 1
            right += 1

        def nbits(n):
            bits = 0
            while n:
                if n & 0x01:
                    bits += 1
                n >>= 1
            return bits

        def parity(aux, audio, v, u, c):
            return sum([ nbits(x) for x in [ aux, audio, v, u, c ] ]) & 0x01

        t = 10
        for preamble, aux, audio, v, u, c in data:
            p = parity(aux, audio, v, u, c)
            source.push(t=t, preamble=preamble, aux=aux, audio=audio, V=v, U=u, C=c, P=p)
            t += 10

        while not source.done():
            yield from tick(1)

        yield from tick(10)

        d = sink_a.get_data()
        #for p in d:
        #    print("packet")
        #    for x in p:
        #        print(x)

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/spdif_block.vcd", traces=[]):
        sim.run()

#
#

def sim_bits(m):
    print("test bits")
    sim = Simulator(m)

    source = SourceSim(m.i)
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()
            yield from source.poll()

    def proc():

        t = 10

        data = [
            [
                0x12, 0x34, 0x12, 0x34, 0x11, 0x11, 0x11, 0x11, 0x22, 0x22, 0x22, 0x22, 
            ],
            [
                0x44, 0x44, 0x44, 0x44,
                0x88, 0x88, 0x88, 0x88, 
                0x01, 0x01, 0x01, 0x01, 
                0x12, 0x34, 0x12, 0x34, 
                0xff, 0xff, 0xff, 0xff,
            ],
            [
                0xca, 0xfe, 0xba, 0xbe, 0xdb, 0xdb, 0xdb, 0xdb,
            ],
        ]

        for p in data:
            mask = 1 << 7
            for i, d in enumerate(p):
                for j in range(8):
                    if d & mask:
                        b = 1
                    else:
                        b = 0
                    d <<= 1
                    first = (i == 0) and (j == 0)
                    last = (i == (len(p)-1)) and (j == 7)
                    source.push(t=t, first=first, last=last, data=b)
                    t += 10

        while not source.done():
            yield from tick(1)
        yield from tick(100)

        d = sink.get_data("data")
        for p in d:
            print("packet")
            for x in p:
                print(hex(x), end=' ')
            print()

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/spdif_bits.vcd", traces=[]):
        sim.run()

#
#

def sim_spdif(m):
    print("test spdif")
    sim = Simulator(m)

    sink = SinkSim(m.audio)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()

    def proc():

        # TODO
        yield from tick(1000)

        d = sink.get_data("data")
        for p in d:
            print("packet")
            for x in p:
                print(hex(x), end=' ')
            print()

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/spdif_rx.vcd", traces=[]):
        sim.run()

#
#

def read_raw_spdif(path, size):
    r = []
    for line in open(path):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        parts = line[5:].split()
        for part in parts:
            for bit in part:
                r.append(int(bit))
        if len(r) >= size:
            break
    return r

def sim_decode(m, mout, gtk):
    print("test decode")
    sim = Simulator(m)

    sink = SinkSim(mout)

    # read bits from test file
    path = "tests/raw_spdif.csv"
    data = read_raw_spdif(path, size=500000)
    print("reading", len(data), "bits")
    info = {
        'idx' : 0,
        'done' : False,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()
            yield m.i.eq(data[info['idx']])
            info['idx'] += 1

    def proc():

        while info['idx'] < len(data):
            yield from tick(1)
            if (info['idx'] % 1000) == 0:
                print('.', end='')
        print()

        path = "/tmp/decode.csv"
        ofile = open(path, "w")
        block = None

        d = sink.get_data()
        if 'left' in [ x[0] for x in sink._layout ]:
            block_reader = True
        else:
            block_reader = False

        def to_32(audio):
            # 20-bit to signed 32-bit conversion
            if audio & (1 << 19):
                # sign extend to 32-bit
                audio |= 0xfff0_0000
            r = struct.pack("I", audio)
            audio = struct.unpack("i", r)[0]
            return audio

        if block_reader:
            for p in d:
                for item in p:
                    left, right = [ to_32(x) for x in [ item['left'], item['right' ] ] ]
                    print("0", left, right, file=ofile)

        # SubframeReader decode
        if not block_reader:
            for p in d:
                for item in p:
                    preamble, audio, c = item['preamble'], item['audio'], item['C']
                    if block is None:
                        # wait for the first preamble
                        if preamble != 2:
                            continue
                        block = True
                    audio = to_32(audio)
                    if preamble == 1:
                        print(audio, file=ofile)
                    else:
                        print(preamble, audio, end=' ', file=ofile)

        # launch gnuplot graph to eyeball the data : 2 sinewaves
        ofile.close()
        cmd = "plot '/tmp/decode.csv' u 2 w l, '' u 3 w l"
        import subprocess
        subprocess.call(f"gnuplot -e \"{cmd}\" -persist", shell=True)

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd(gtk, traces=[]):
        sim.run()

#
#

def sim_writer(m):
    print("test writer")
    sim = Simulator(m)

    src = SourceSim(m.i)

    state = {
        'clock' : 0,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()

            ck = state['clock']
            ck += 1
            if ((ck % 10) == 0):
                yield m.en.eq(1)
            else:
                yield m.en.eq(0)
            state['clock'] = ck

    def proc():

        data = [
            [ PREAMBLE.B, 0xf, 0xaaaaa, 0, 0, 1, ],
            [ PREAMBLE.W, 0xf, 0x12345, 0, 0, 0, ],
            [ PREAMBLE.M, 0xf, 0xfffff, 0, 0, 1, ],
            [ PREAMBLE.W, 0xf, 0x00000, 0, 0, 0, ],
            [ PREAMBLE.M, 0xf, 0xaaaaa, 0, 1, 1, ],
        ]

        for preamble, aux, audio, v, u, c, in data:
            src.push(0, preamble=preamble, aux=aux, audio=audio, V=v, U=u, C=c)

        while not src.done():
            yield from tick(1)
            
        while True:
            yield from tick(1)
            r = yield m.i.ready
            v = yield m.i.valid
            if r and not v:
                break;

        yield from tick(20)

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/spdif_wr.vcd", traces=[]):
        sim.run()

#
#

def sim_sf(m):
    print("test subframe rd/wr")
    sim = Simulator(m)

    src = SourceSim(m.wr.i)
    sink = SinkSim(m.rd.o)

    state = {
        'clock' : 0,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()

            ck = state['clock']
            ck += 1
            if ((ck % 10) == 0):
                yield m.wr.en.eq(1)
            else:
                yield m.wr.en.eq(0)
            state['clock'] = ck

    def proc():

        data = [
            [ PREAMBLE.B, 0xf, 0xaaaaa, 0, 0, 1, ],
            [ PREAMBLE.W, 0x1, 0x12345, 0, 0, 0, ],
            [ PREAMBLE.M, 0x2, 0xfffff, 0, 0, 1, ],
            [ PREAMBLE.W, 0x4, 0x00000, 0, 0, 0, ],
            [ PREAMBLE.M, 0x8, 0xaaaaa, 1, 1, 1, ],
            [ PREAMBLE.W, 0x0, 0x12345, 0, 0, 0, ],
            [ PREAMBLE.M, 0x1, 0xfffff, 1, 0, 1, ],
            [ PREAMBLE.W, 0x2, 0x00000, 1, 0, 0, ],
            [ PREAMBLE.M, 0x4, 0xaaaaa, 1, 1, 1, ],
            [ PREAMBLE.B, 0x8, 0xaaaaa, 0, 0, 1, ],
            [ PREAMBLE.W, 0x0, 0x12345, 0, 0, 0, ],
            [ PREAMBLE.M, 0xf, 0xfffff, 0, 0, 1, ],
            [ PREAMBLE.W, 0xf, 0x00000, 0, 0, 0, ],
        ]

        for preamble, aux, audio, v, u, c, in data:
            src.push(0, preamble=preamble, aux=aux, audio=audio, V=v, U=u, C=c)

        while not src.done():
            yield from tick(1)

        while True:
            yield from tick(1)
            r = yield m.wr.i.ready
            v = yield m.wr.i.valid
            if r and not v:
                break;
            
        yield from tick(200)

        # the final sent word doesn't arrive. the first few will be corrupted
        # while the discriminator syncs to the input

        idx = len(data) - 2

        def match(p, d):
            preamble, aux, audio, v, u, c = d
            if preamble != p['preamble']:
                return False
            if aux != p['aux']:
                return False
            if audio != p['audio']:
                return False
            if v != p['V']:
                return False
            if u != p['U']:
                return False
            if c != p['C']:
                return False
            if p['check'] != p['P']:
                return False

            return True

        r = sink.get_data()[0]
        r.reverse()
        for i, d in enumerate(r):
            #print(i, d)
            #print(data[idx])
            if not match(d, data[idx]):
                break
            idx -= 1

        assert i > 8

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/spdif_sf.vcd", traces=[]):
        sim.run()

class SubframeTest(Elaboratable):

    def __init__(self):
        self.rd = SubframeReader()
        self.wr = SubframeWriter()
        self.mods = [
            self.rd,
            self.wr,
        ]

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.mods

        m.d.comb += self.rd.i.eq(self.wr.o)
        return m

#
#

def sim_tx(m):
    print("test tx")
    sim = Simulator(m)

    src = SourceSim(m.i)

    state = {
        'clock' : 0,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()

            ck = state['clock']
            ck += 1
            if ((ck % 10) == 0):
                yield m.en.eq(1)
            else:
                yield m.en.eq(0)
            state['clock'] = ck

    def proc():

        data = []

        for i in range(200):
            data.append((10, 0x1234 + i, i))

        for t, left, right in data:
            src.push(t, left=left, right=right)

        while not src.done():
            yield from tick(1)

        yield from tick(1000)

    sim.add_clock(1 / 50e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/spdif_tx.vcd", traces=[]):
        sim.run()

#
#

def draw(dut):
    from streams import dot
    dot_path = "/tmp/wifi.dot"
    png_path = "test.png"
    dot.graph(dut, dot_path, png_path)
 
#
#

def test(verbose):
    do_all = True
    name = None

    if len(sys.argv) > 1:
        name = sys.argv[1]
        do_all = False

    if (name == "SubframeReader") or do_all:
        dut = SubframeReader()
        sim_subframe(dut)

    if (name == "BitsReader") or do_all:
        dut = BitsReader()
        sim_bits(dut)

    if (name == "BlockReader") or do_all:
        dut = BlockReader()
        sim_block(dut)

    if (name == "SPDIF_Rx") or do_all:
        dut = SPDIF_Rx()
        sim_spdif(dut)

    if (name == "SPDIF_decode_sf") or do_all:
        dut = SubframeReader()
        sim_decode(dut, dut.o, "gtk/spdif_decode.vcd")

    if (name == "SPDIF_decode") or do_all:
        dut = SPDIF_Rx()
        sim_decode(dut, dut.audio, "gtk/spdif_decode_rx.vcd")

    if (name == "SubframeWriter") or do_all:
        dut = SubframeWriter()
        sim_writer(dut)

    if (name == "SubframeTest") or do_all:
        dut = SubframeTest()
        sim_sf(dut)

    if (name == "SPDIF_Tx") or do_all:
        dut = SPDIF_Tx() # block_size=10)
        sim_tx(dut)

    draw(dut)

if __name__ == "__main__":
    test(False)

#   FIN
