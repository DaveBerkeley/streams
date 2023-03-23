#!/bin/env python3

from amaranth import *
from amaranth.sim import *

from streams.stream import to_packet, StreamInit, StreamNull, StreamTee, Join
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

def sim_tee(m, verbose):
    print("test null")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)
    sinks = []
    for i in range(len(m.o)):
        sink = SinkSim(m.o[i])
        sinks.append(sink)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            for sink in sinks:
                yield from sink.poll()

    def proc():
        tx_data = [
            [   0,  [ 0x1234, 0x2222, 1, 2, 3, 4, ], ],
            [   20, [ 0xffff, ], ],
            [   40, [ 0x2345, 0xabcd, 4, 5, 6, 7, ], ],
            [   70, [ 0x1234, 0x2222, 0xffff, 0 ], ],
        ]
        for t, p in tx_data:
            for i, d in enumerate(p):
                first = i == 0
                last = i == (len(p) - 1)
                src.push(t, data=d, first=first, last=last)

        # simulate intermittant reading on sinks[1]
        yield from tick(10)
        sinks[1].read_data = False
        yield from tick(50)
        sinks[1].read_data = True
        yield from tick(5)
        sinks[1].read_data = False
        yield from tick(20)
        sinks[1].read_data = True
        yield from tick(50)

        tx_p = []
        for _, p in tx_data:
            tx_p.append(p)

        for i, sink in enumerate(sinks):
            p = sink.get_data("data")
            if m.wait_all or (i != 1):
                assert p == tx_p, (i, p, tx_p)
            else:
                assert p != tx_p, (i, p, tx_p)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    wait = m.wait_all
    with sim.write_vcd(f"gtk/stream_tee_{wait}.vcd", traces=m.ports()):
        sim.run()

#
#

def sim_join(m, verbose):
    print("test join")
    sim = Simulator(m)

    a = SourceSim(m.i[0], verbose=verbose)
    b = SourceSim(m.i[1], verbose=verbose)
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from a.poll()
            yield from b.poll()
            yield from sink.poll()

    def proc():
        a_data = [
            [   0,  [ 0x34, 0x22, 1, 2, 3, 4, ], ],
            [   20, [ 0xff, ], ],
            [   40, [ 0x45, 0xcd, 4, 5, 6, 7, ], ],
            [   70, [ 0x34, 0x22, 0xff, 0 ], ],
        ]
        b_data = [
            [   30,  [ 0x66, 0x44, 1, 2, 3, 4, ], ],
            [   30,  [ 0xab, ], ],
            [   80,  [ 0x66, 0x44, 1, 2, 3, 4, ], ],
            [   65,  [ 1, 2, 3, 4, ], ],
        ]

        def push(s, data, field):
            for t, p in data:
                for i, d in enumerate(p):
                    first = i == 0
                    last = i == (len(p) - 1)
                    dd = {
                        'first' : i == 0,
                        'last' : i == (len(p) - 1),
                    }
                    dd[field] = d
                    s.push(t, **dd)

        push(a, a_data, "a")
        push(b, b_data, "b")

        # simulate intermittant reading on sinks[1]
        yield from tick(200)
        aa = sink.get_data("a")
        bb = sink.get_data("b")
        for i, p in enumerate(zip(aa, bb)):
            assert p == (a_data[i][1], b_data[i][1])

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd(f"gtk/stream_join.vcd", traces=[]):
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

    dut = StreamTee(3, layout, wait_all=False)
    sim_tee(dut, verbose)
    dut = StreamTee(3, layout, wait_all=True)
    sim_tee(dut, verbose)

    dut = Join(a=[("a", 8)], b=[("b", 8)])
    sim_join(dut, verbose)

#   FIN
