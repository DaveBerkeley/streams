#!/bin/env python

import sys
import random

if not "." in sys.path:
    sys.path.append(".")

from amaranth import *
from amaranth.sim import *

from streams.sim import SinkSim, SourceSim
from streams.i2s import I2SOutput, I2SInput, I2STxClock, I2SRxClock, I2SInputLR

def load_lr_data(s, t, lr):
    for l, r in lr:
        s.push(t, left=l, right=r)

#
#

def sim_o(m, verbose):
    print("test i2s output")

    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)

    info = { "t" : 0 }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()

            info['t'] += 1
            if ((info['t'] % 10) == 0):
                yield m.enable.eq(1)
            else:
                yield m.enable.eq(0)

    def proc():

        data = [
            [ 0xaaaaaaaa, 0x55555555, ],
            [ 0x11111111, 0x22222222, ],
            [ 0x00000000, 0xffffffff, ],
            [ 0xffffffff, 0x00000000, ],
            [ 0x12345678, 0x12345678, ],
            [ 0x80000000, 0x7fffffff, ],
        ]

        for left, right in data:
            src.push(10, left=left, right=right)

        yield from tick(5000)
        print("TODO : add actual tests!")

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/i2s.vcd"):
        sim.run()

#
#

def sim_i(m, verbose):
    print("test i2s input")

    class Both(Elaboratable):
        def __init__(self, m, width):
            self.tx = I2SOutput(width)
            self.rx = m
            self.enable = Signal()
        def elaborate(self, platform):
            m = Module()
            m.submodules += self.tx
            m.submodules += self.rx
            m.d.comb += self.tx.enable.eq(self.enable)

            # Connect the PHYs together
            for name in [ "sd", "sck", "ws" ]:
                o = getattr(self.tx.phy, name)
                i = getattr(self.rx.phy, name)
                m.d.comb += i.eq(o)

            return m

    both = Both(m, m.width)
    sim = Simulator(both)

    m = both
    src = SourceSim(m.tx.i, verbose=verbose)
    sink = SinkSim(m.rx.o)

    info = { "t" : 0 }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()

            info['t'] += 1
            if ((info['t'] % 10) == 0):
                yield m.enable.eq(1)
            else:
                yield m.enable.eq(0)

    def proc():

        data = [
            [ 0xaaaa, 0x5555, ],
            [ 0x1111, 0x2222, ],
            [ 0x0000, 0xffff, ],
            [ 0xffff, 0x0000, ],
            [ 0x1234, 0x1234, ],
            [ 0x8000, 0x7fff, ],
        ]

        for left, right in data:
            src.push(10, left=left, right=right)

        yield from tick(5000*2)

        r = [ [d['left'], d['right']] for d in sink.get_data()[0] ]
        # discard the first two frames 
        r = r[2:]
        for i, lr in enumerate(data):
            assert lr == r[i], (i, r, lr)

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/i2s_i.vcd"):
        sim.run()

#
#

def sim_tx_ck(m, verbose):
    print(f"test i2s tx clock w={m.width} ow={m.owidth}")

    sim = Simulator(m)

    info = { 
        "t" : 0, # clock enable
        "bits" : 0,
        "prev_sck" : 0,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            info['t'] += 1
            if ((info['t'] % 10) == 0):
                yield m.enable.eq(1)
            else:
                yield m.enable.eq(0)

            # count sck hi to lo transitions
            sck = yield m.sck
            if info['prev_sck'] and not sck:
                info['bits'] += 1
            info['prev_sck'] = sck

            ws = yield m.ws
            if (ws != info.get('prev_ws', ws)):
                # check we have the correct number of sck bits in each channel
                assert info['bits'] == m.width, (info['bits'], m.width)
                info['bits'] = 0
            info['prev_ws'] = ws

            d = yield m.l_word
            r = (m.owidth+1) % m.width
            if d:
                assert info['bits'] == r, (r, info)
            d = yield m.r_word
            if d:
                assert info['bits'] == r, (r, info)

    def proc():
        yield from tick(5000)

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/i2s_ck.vcd"):
        sim.run()

#
#

def sim_rx_ck(m, verbose):
    print("test i2s 32-bit rx clock")

    sim = Simulator(m)

    info = {
        "t" : 0,
        "bit" : 0,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            info['t'] += 1
            if (info['t'] % 8) == 0:
                # half clock cycle
                sck = yield m.sck
                yield m.sck.eq(~m.sck)
                if sck: # 1 to 0 ck transition
                    info['bit'] += 1
                    if info['bit'] == 32:
                        yield m.ws.eq(1)
                    if info['bit'] == 64:
                        info['bit'] = 0
                        yield m.ws.eq(0)

    def proc():
        # simulate ws and sck input signals
        yield from tick(5000)
        print("TODO : add actual tests!")

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/i2s_rx_ck.vcd", traces=[]):
        sim.run()

#
#

class I2SInputLRTx(Elaboratable):

    def __init__(self):
        self.ck = I2STxClock(width=32, owidth=16)
        self.tx = I2SOutput(tx_clock=self.ck, width=32)
        self.rx = I2SInputLR(rx_clock=self.ck, width=16)
        self.mods = [
            self.ck, self.tx, self.rx,
        ]

        self.en = Signal()
        self.left = self.rx.left
        self.right = self.rx.right
        self.i = self.tx.i

    def elaborate(self, _):
        m = Module()
        m.submodules += self.mods

        m.d.comb += [
            self.ck.enable.eq(self.en),
            self.rx.i.eq(self.tx.phy.sd),
        ]

        return m

class I2SInputLRRx(Elaboratable):

    def __init__(self):
        self.tck = I2STxClock(width=32, owidth=16)
        self.rck = I2SRxClock(width=32, owidth=16)
        self.tx = I2SOutput(tx_clock=self.tck, width=32)
        self.rx = I2SInputLR(rx_clock=self.rck, width=16)
        self.mods = [
            self.tck, self.rck, self.tx, self.rx,
        ]

        self.en = Signal()
        self.left = self.rx.left
        self.right = self.rx.right
        self.i = self.tx.i

    def elaborate(self, _):
        m = Module()
        m.submodules += self.mods

        m.d.comb += [
            self.tck.enable.eq(self.en),
            self.rx.i.eq(self.tx.phy.sd),
            self.rck.ws.eq(self.tck.ws),
            self.rck.sck.eq(self.tck.sck),
        ]

        return m

def sim_lr_tx(m, verbose):
    print("test input_lr", m)

    sim = Simulator(m)

    src = SourceSim(m.i)
    left = SinkSim(m.left)
    right = SinkSim(m.right)

    polls = [ src, left, right ]

    info = {
        "t" : 0,
    }

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            for s in polls:
                yield from s.poll()
            info['t'] += 1
            if (info['t'] % 8) == 0:
                yield m.en.eq(1)
            else:
                yield m.en.eq(0)

    def proc():
        def wait_source():
            while True:
                if src.done():
                    break
                yield from tick(1)

        def sample():
            return random.randint(1, (1<<32)-1)

        audio = []

        for i in range(100):
            audio.append(( sample(), sample() ))

        for s in audio:
            load_lr_data(src, 10, [ s ] )

        yield from tick(20)
        yield from wait_source()
        yield from tick(320*2)

        l = left.get_data("data")[0][1:]
        r = right.get_data("data")[0][1:]
        #print([ hex(x) for x in l ])
        #print([ hex(x) for x in r ])
        #print([ (hex(a>>16), hex(b>>16)) for a,b in audio ])
        for i in range(0, len(l)):
            lr = [ l[i], r[i] ]
            a = [ (x>>16) for x in audio[i] ]
            assert a == lr, (i, a, lr)

    sim.add_clock(1 / 100e6)
    sim.add_process(proc)
    with sim.write_vcd("gtk/i2s_lr_tx.vcd", traces=[]):
        sim.run()

#
#

def test(verbose):
    test_all, name = True, None
    if len(sys.argv) > 1:
        name = sys.argv[1]
        test_all = False

    if (name == "I2SOutput") or test_all:
        dut = I2SOutput(32)
        sim_o(dut, verbose)

    if (name == "I2SInput") or test_all:
        dut = I2SInput(32)
        sim_i(dut, verbose)

    if (name == "I2STxClock") or test_all:
        for w, ow in [ (24, 12), (24, 24), (32, 16), (32, 32) ]:
            dut = I2STxClock(w, owidth=ow)
            sim_tx_ck(dut, verbose)

    if (name == "I2SRxClock") or test_all:
        dut = I2SRxClock(32, owidth=16)
        sim_rx_ck(dut, verbose)

    if (name == "I2SInputLR") or test_all:
        for dut in [ I2SInputLRTx(), I2SInputLRRx() ]:
            sim_lr_tx(dut, verbose)

    print("done")

if __name__ == "__main__":
    test(True)

#   FIN
