#!/bin/env python3

from amaranth import *
from amaranth.sim import *

from streams.stream import to_packet, StreamInit, StreamNull
from streams.sim import SourceSim, SinkSim

#
#

def get_field(name, data):
    return [ d[name] for _, d in data ]

def get_data(data):
    return [ d for _, d in data ]

#
#

def sim_init(m, init_data, verbose):
    print("test init")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()

    def proc():
        tx_data = [
            [   0, 0x1234 ],
            [   0, 0x2222 ],
            [   20, 0xffff ],
            [   20, 0xaaaa ],
            [   40, 0x2345 ],
        ]
        for i, (t, d) in enumerate(tx_data):
            first = i == 0
            last = i == (len(tx_data) - 1)
            src.push(t, data=d, first=first, last=last)

        yield from tick(50)
        yield m.clr.eq(1)
        yield from tick()
        yield m.clr.eq(0)
        yield from tick(20)

        def get_field(d, field='data'):
            return [ x[field] for x in d ]

        assert len(sink.get_data()) == 3
        d = sink.get_data("data")
        assert d[0] == get_field(init_data), (d[0], init_data)
        assert d[1] == get_data(tx_data), (d[1], tx_data)
        assert d[2] == get_field(init_data), (d[2], init_data)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/stream_init.vcd", traces=m.ports()):
        sim.run()

#
#

def sim_null(m, n, verbose):
    print("test null")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink.poll()

    def proc():
        tx_data = [
            [   0, 0x1234 ],
            [   0, 0x2222 ],
            [   20, 0xffff ],
            [   20, 0xaaaa ],
            [   40, 0x2345 ],
            [   40, 0xabcd ],
        ]
        for i, (t, d) in enumerate(tx_data):
            first = i == 0
            last = i == (len(tx_data) - 1)
            src.push(t, data=d, first=first, last=last)

        yield from tick(50)
        assert tx_data[n:], get_field("data", sink.data[0])

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/stream_null.vcd", traces=m.ports()):
        sim.run()

#
#

def test(verbose=False):
    from streams.sim import SinkSim, SourceSim

    layout = [ ( "data", 16 ), ]
    data = to_packet([ 0xabcd, 0xffff, 0xaaaa, 0x0000, 0x5555 ])
    dut = StreamInit(data, layout)
    sim_init(dut, data, verbose)

    dut = StreamNull(3, layout)
    sim_null(dut, 3, verbose)

#   FIN
