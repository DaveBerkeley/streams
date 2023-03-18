#!/bin/env python3

#   Driver for the 12-bit 1M s/s ADC found on the ulx3s
#

from amaranth import *
from amaranth.sim import *

from streams import Stream
from streams.sim import SinkSim, SourceSim 
from streams.spi import SpiController

#
#

class MAX11125(Elaboratable):

    ADC_CONFIG  = 0x10 << 11
    UNIPOLAR    = 0x11 << 11
    BIPOLAR     = 0x12 << 11
    RANGE       = 0x13 << 11
    SCAN_0      = 0x14 << 11
    SCAN_1      = 0x15 << 11
    SAMPLE      = 0x16 << 11

    def __init__(self, init=[], divider=1):
        self.spi = SpiController(width=16, init=init, cpol=1, cpha=1)
        self.phy = self.spi.phy
        layout_o = [ ("data", 12 ), ("chan", 4), ]
        layout_i = [ ("chan", 4 ), ]
        self.i = Stream(layout=layout_i, name="MAX11125.i")
        self.o = Stream(layout=layout_o, name="MAX11125.o")

        self.divider = divider
        self.clock = Signal(range(divider))

    def elaborate(self, platform):
        m = Module()

        m.submodules += self.spi

        m.d.sync += [
            self.clock.eq(self.clock + 1),
            self.spi.enable.eq(0),
        ]

        with m.If(self.clock == (self.divider-1)):
            m.d.sync += [
                self.clock.eq(0),
                self.spi.enable.eq(1),
            ]

        m.d.comb += Stream.connect(self.i, self.spi.i, exclude=["chan"])
        m.d.comb += Stream.connect(self.spi.o, self.o, exclude=["chan", "data"])

        # Send convert requests for chan
        data = 0x0806 + (self.i.chan << 7)
        m.d.comb += self.spi.i.data.eq(data)

        # split rx data into chan/data
        m.d.comb += self.o.data.eq(self.spi.o.data)
        m.d.comb += self.o.chan.eq(self.spi.o.data >> 12)

        return m

    def ports(self): return []

#
#

def sim():
    init_data = [
        0x0806,
        0x1000,
        0x9800,
        0x8800,
        0x9000,
    ]
    init = []
    for d in init_data:
        init += [ { "data" : d } ]
    divider = 4
    m = MAX11125(init=init, divider=divider)
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=True)
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()
            # loopback the copi/cipo
            yield m.spi.phy.cipo.eq(m.spi.phy.copi)

    def proc():

        chan = [ 15, 0, 10, 5, 3, 1, 0 ]

        for d in chan:
            src.push(40, chan=d, first=1, last=1)

        n = (len(init_data) + len(chan) + 1) * divider * 2 * (16 + 1)
        yield from tick(n)

        # flatten the packets (each rd data will be in a packet)
        def flatten(ps):
            d = []
            for p in ps:
                assert len(p) == 1
                d += [ p[0] ]
            return d
            
        #assert d1 == init_data, ([ hex(x) for x in d1 ], [ hex(x) for x in init_data ])

        d = flatten(sink.get_data("data"))
        c = flatten(sink.get_data("chan"))
        # reconstruct 32-bit binary from chan,data output stream
        b = [ ((a<<12) + b) for (a,b) in zip(c, d) ]
        assert b[:len(init_data)] == init_data, [ hex(x) for x in b ]

        # check that the chan part of the command is correct
        for i, r in enumerate(b[len(init_data):]):
            c = (r >> 7) & 0xf
            assert chan[i] == c
            assert (r & ~0x0780) == 0x0806

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/max11125.vcd", traces=m.ports()):
        sim.run()

#
#

if __name__ == "__main__":
    sim()

#   FIN
