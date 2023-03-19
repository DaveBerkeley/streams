#!/bin/env python3

#   TODO : work in progress

from amaranth import *
from amaranth.sim import *

from streams import Stream
from streams.sim import SinkSim, SourceSim

#
#

class Phy:
    def __init__(self):
        self.ws = Signal()
        self.sck = Signal()
        self.sd = Signal()

#
#

class I2SOutput(Elaboratable):

    def __init__(self, width):
        self.width = width
        layout = [ ("left", width), ("right", width) ]
        self.i = Stream(layout=layout, name="I2S.i")
        self.enable = Signal()

        self.phy = Phy()
        self.bit = Signal(range(width * 2))
        self.sro = Signal(width * 2)
        self.left  = Signal(width)
        self.right = Signal(width)

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.phy.sd.eq(self.sro[self.width-1]),
            self.phy.ws.eq(self.bit[-1]),
        ]

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
                self.left.eq(self.i.left),
                self.right.eq(self.i.right),
            ]

        half = Signal()

        with m.If(self.enable):
            m.d.sync += half.eq(~half)

        with m.If(self.enable & ~half):
            m.d.sync += self.phy.sck.eq(1)

        with m.If(self.enable & half):

            m.d.sync += [
                self.bit.eq(self.bit + 1),
                self.sro.eq(Cat(0, self.sro)),
                self.phy.sck.eq(0),
            ]

            with m.If(self.bit == 0):
                m.d.sync += self.sro.eq(self.left)

            with m.If(self.bit == self.width):
                m.d.sync += self.sro.eq(self.right)
                m.d.sync += self.i.ready.eq(1)

        return m

    def ports(self): return []

#
#

class I2SInput(Elaboratable):

    def __init__(self, width):
        self.width = width
        self.phy = Phy()

        self.bit = Signal(width * 2)
        self.sri = Signal(width * 2)

        layout = [ ("left", width), ("right", width) ]
        self.o = Stream(layout=layout, name="I2S.o", group=self)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.o.ready & self.o.valid):
            m.d.sync += self.o.valid.eq(0)

        sck_0 = Signal()
        sck_1 = Signal()
        m.d.sync += sck_0.eq(self.phy.sck)
        m.d.sync += sck_1.eq(sck_0)

        # Sample on the rising edge of PHY.SCK
        sample = Signal()
        m.d.comb += sample.eq(sck_0 & ~sck_1)

        ws = Signal()
        with m.If(sample):

            m.d.sync += self.bit.eq(self.bit + 1)

            m.d.sync += ws.eq(self.phy.ws)

            with m.If(ws & ~self.phy.ws):
                # falling edge of PHY.WS
                m.d.sync += self.bit.eq(0)

            m.d.sync += self.sri.eq(Cat(self.phy.sd, self.sri))

            with m.If(self.bit == 0):
                m.d.sync += [
                    self.o.left.eq(self.sri >> self.width),
                    self.o.right.eq(self.sri),
                    self.o.valid.eq(1),
                ]

        return m

    def ports(self): return []

#
#

def sim_o(m):
    print("test i2s output")

    sim = Simulator(m)

    src = SourceSim(m.i, verbose=True)

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
            [ 0xaaaa, 0x5555, ],
            [ 0x1111, 0x2222, ],
            [ 0x0000, 0xffff, ],
            [ 0xffff, 0x0000, ],
            [ 0x1234, 0x1234, ],
            [ 0x8000, 0x7fff, ],
        ]

        for left, right in data:
            src.push(10, left=left, right=right)

        yield from tick(5000)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/i2s.vcd", traces=m.ports()):
        sim.run()

#
#

def sim_i(m):
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
        def ports(self): return []

    both = Both(m, m.width)
    sim = Simulator(both)

    m = both
    src = SourceSim(m.tx.i, verbose=True)
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

        yield from tick(5000)

        r = [ [d['left'], d['right']] for d in sink.get_data()[0] ]
        # discard the first two frames 
        r = r[2:]
        assert data == r, r

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/i2s_i.vcd", traces=m.ports()):
        sim.run()

#
#

if __name__ == "__main__":
    dut = I2SOutput(16)
    sim_o(dut)

    dut = I2SInput(16)
    sim_i(dut)

    print("done")

#   FIN
