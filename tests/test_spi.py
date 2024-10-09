#!/usr/bin/env python3

from amaranth import *
from amaranth.sim import *

import sys
spath = "../streams"
if not spath in sys.path:
    sys.path.append(spath)

from streams import to_packet
from streams.spi import SpiController, SpiPeripheral, SpiClock
from streams.sim import SinkSim, SourceSim

#
#

def sim_controller(m, verbose):
    print("test controller")
    sim = Simulator(m)

    period = 7

    rd = SinkSim(m.o)
    wr = SourceSim(m.i, verbose=verbose)
    ck = SpiClock(m.enable, period)

    def tick(n=1):
        assert n
        for i in range(n):
            yield m.phy.cipo.eq(m.phy.copi) # loopback
            yield Tick()
            yield from rd.poll()
            yield from wr.poll()
            yield from ck.poll()

    def proc():
        yield m.cpha.eq(0)

        d1 = [ 0xaa, 0xff, 0x55, 0x00, ]
        d2 = [ 0xaa, 0x34, 0x56, 0x78, ]

        for d in to_packet(d1):
            wr.push(10, **d)
        for d in to_packet(d2):
            wr.push(80, **d)

        # wait for Tx
        while True:
            yield from tick()
            if wr.done():
                break

        # wait for input ready and not valid
        while True:
            yield from tick()
            r = yield m.i.ready
            v = yield m.i.valid
            if r and not v:
                break

        yield from tick(20)

        rx = rd.get_data("data")
        assert rx == [ d1, d2 ]

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/spix.vcd", traces=m.ports()):
        sim.run()

#
#

def sim_flags(m, verbose):
    print("test first/last")
    sim = Simulator(m)

    period = 7

    rd = SinkSim(m.o)
    wr = SourceSim(m.i, verbose=verbose)
    ck = SpiClock(m.enable, period)

    def tick(n=1):
        assert n
        for i in range(n):
            yield m.phy.cipo.eq(m.phy.copi) # loopback
            yield Tick()
            yield from rd.poll()
            yield from wr.poll()
            yield from ck.poll()

    def proc():
        yield m.cpha.eq(0)
        yield from tick(7)

        d1 = [ 0xaa, 0xff, 0x55, 0x00, ]
        d2 = [ 0xaa, 0x34, 0x56, 0x78, ]

        for p in to_packet(d1):
            wr.push(10, **p)
        for p in to_packet(d2):
            wr.push(50, **p)

        while True:
            yield from tick()
            if len(rd.get_data("data")[0]) == len(d1):
                break

        yield m.cpha.eq(1)

        while True:
            yield from tick()
            d = rd.get_data("data")
            if len(d) == 2:
                if len(d[1]) == len(d2):
                    break

        yield from tick(9 * period * 2)

        # check data / packet grouping
        assert rd.get_data("data") == [ d1, d2 ], (rd.get_data("data"), d1, d2)
        for p in rd.get_data("first"):
            assert p[0], p
            assert sum(p[1:]) == 0
        for p in rd.get_data("last"):
            assert p[-1], p
            assert sum(p[:-1]) == 0

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/spi_flags.vcd", traces=m.ports()):
        sim.run()

#
#

def sim_peripheral(m, verbose):
    print("test peripheral")

    class Test(Elaboratable):

        def __init__(self, spi):
            self.spi = spi
            self.controller = SpiController(width=spi.width, last_cs=True)
        def elaborate(self, platform):
            m = Module()
            m.submodules += self.spi
            m.submodules += self.controller

            # cross-connect the PHYs
            c = self.controller.phy
            p = self.spi.phy
            m.d.comb += [
                p.scs.eq(c.scs),
                p.sck.eq(c.sck),
                p.copi.eq(c.copi),
                c.cipo.eq(p.cipo),
            ]

            return m
        def ports(self):
            return self.spi.ports()

    test = Test(m)
    m = test
    sim = Simulator(m)

    c_src = SourceSim(m.controller.i, verbose=verbose, name="C")
    p_src = SourceSim(m.spi.i, verbose=verbose, name="P")
    p_sink = SinkSim(m.spi.o)
    c_sink = SinkSim(m.controller.o)

    period = 8
    ck = SpiClock(m.controller.enable, period)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from c_src.poll()
            yield from p_src.poll()
            yield from c_sink.poll()
            yield from p_sink.poll()
            yield from ck.poll()

    def proc():
        yield m.spi.cpha.eq(0)

        yield from c_src.reset()
        yield from p_src.reset()

        d1 = [ 0x12, 0x23, 0x34, 0x45 ]
        d2 = [ 0xaa, 0xff, 0x00, 0x55 ]
        d3 = [ 1, 2, 4 ]

        for t, p in [ (5, d1), (350, d2), (400, d3), ]:
            for d in to_packet(p):
                c_src.push(t, **d)

        p1 = [ 0xff, 0x00, 0xaa, 0x55, 0xf0, 0x11, 0x0f, 0x88 ]
        for d in p1:
            p_src.push(0, data=d)

        yield from tick(4000)

        rx = p_sink.get_data("data") 
        assert d1 == rx[0], p_sink.get_data()
        assert d2 == rx[1], p_sink.get_data()
        assert d3 == rx[2], p_sink.get_data()

        # check that p1 was sent from p to c and rxd by c
        def flatten(ps):
            d = []
            for p in ps:
                d += p
            return d
        rx = c_sink.get_data("data")
        rx = flatten(rx)
        rx = rx[:len(p1)] # trailing data is not defined
        assert p1 == rx, (rx, p1)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/spi_perihperal.vcd", traces=m.ports()):
        sim.run()

#
#

def test(verbose):
    dut = SpiController(width=8)
    sim_controller(dut, verbose)

    dut = SpiController(width=8, last_cs=True)
    sim_flags(dut, verbose)

    dut = SpiPeripheral(width=8, last_cs=True)
    sim_peripheral(dut, verbose)

#
#

if __name__ == "__main__":
    test(True)

#   FIN
