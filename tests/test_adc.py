#! bin/env python3

from amaranth.sim import *

from streams.sim import SourceSim, SinkSim
from streams.adc import MAX11125

#
#

def sim(verbose):
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

    src = SourceSim(m.i, verbose=verbose)
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

def test(verbose):
    sim(verbose)

#   FIN
