#!/bin/env python3

from amaranth import *
from amaranth.sim import *

import sys
spath = "../streams"
if not spath in sys.path:
    sys.path.append(spath)

from streams.stream import to_packet, StreamInit, StreamNull, Tee, Join, Split, GatePacket, Arbiter
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

def sim_split(m, verbose):
    print("test split")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)
    sink_a = SinkSim(m.a)
    sink_b = SinkSim(m.b)
    sink_c = SinkSim(m.c)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from sink_a.poll()
            yield from sink_b.poll()
            yield from sink_c.poll()

    def proc():

        data = [
            [   1, 2, 3, ],
            [   4, 5, 6, ],
            [   7, 8, 9, ],
        ]

        for i, (a, b, c) in enumerate(data):
            first = i == 0
            last = i == (len(data) - 1)
            src.push(10, a=a, b=b, c=c, first=first, last=last)

        # simulate intermittant reading on sinks[1]
        yield from tick(200)
        a = sink_a.get_data("a")
        b = sink_b.get_data("b")
        c = sink_c.get_data("c")
        #for i, p in enumerate(zip(aa, bb)):
        #    assert p == (a_data[i][1], b_data[i][1])
        print(a)
        print(c)
        print(b)
        x = zip(a, b, c)
        print([ x for x in zip(*data) ])
        print("TODO")

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd(f"gtk/stream_join.vcd", traces=[]):
        sim.run()

#
#

def sim_gate(m, verbose):
    print("test gate")
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

        data = [
            [ 10, [ 1, 2, 3, ], ],
            [ 10, [ 4, 5, 6, ], ],
            [ 50, [ 7, 8, 9, ], ],
            [ 70, [ 10, ], ],
            [ 90, [ 7, 8, 90, ], ],
            [ 130, [ 11, 12, 13, ], ],
            [ 150, [ 10, ], ],
        ]

        for i, (t, d) in enumerate(data):
            p = to_packet(d)
            for x in p:
                src.push(t, **x)

        # generate a set of long & short enables
        enables = [ 20, 40, 60, 80, 100, 120, 140, 160 ]
        long = [ 40, 60 ]
        hi = 0

        while True:
            t = sink.t
            if t > max(enables):
                break
            if t in enables:
                yield m.en.eq(1)
                if t in long:
                    hi = 18
                else:
                    hi = 1
            yield from tick()
            if hi:
                hi -= 1
            if hi == 0:
                yield m.en.eq(0)

        yield from tick(20)

        def check(idx, t, d):
            #print(idx, t, d, data[idx], enables)
            margin = 3 # takes 3 clocks to travel src->sink
            if idx in [ 0, 1, 4 ]:
                assert t == (enables[idx] + margin)
                assert d == data[idx][1]
            elif idx in [ 2, 3 ]:
                assert t == (data[idx][0] + margin)
                assert d == data[idx][1]
            elif idx in [ 5, 6 ]:
                assert t == (enables[idx+1] + margin)
                assert d == data[idx][1]
            else:
                assert 0, ("bad idx", idx)

        for i, p in enumerate(sink.get_data()):
            t, d = p[0]["_t"], [ x["data"] for x in p ]
            check(i, t, d)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd(f"gtk/stream_gate.vcd", traces=[]):
        sim.run()

#
#

def sim_arbiter(m, verbose):
    print("test arbiter")
    sim = Simulator(m)

    src_a = SourceSim(m.i[0], verbose=verbose, name="a")
    src_b = SourceSim(m.i[1], verbose=verbose, name="b")
    src_c = SourceSim(m.i[2], verbose=verbose, name="c")
    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src_a.poll()
            yield from src_b.poll()
            yield from src_c.poll()
            yield from sink.poll()

    def proc():

        data = [
            [ 10, src_a, [ 1, 6, 3, ], ],
            [ 20, src_b, [ 2, 5, 6, ], ],
            [ 35, src_a, [ 1, 8, 9, ], ],
            [ 35, src_b, [ 2, 8, 9, ], ],
            [ 60, src_a, [ 1, ], ],
            [ 61, src_b, [ 2, ], ],
            [ 70, src_a, [ 1, ], ],
            [ 70, src_b, [ 2, ], ],
            [ 70, src_c, [ 3, ], ],
            [ 80, src_c, [ 3, 8, 9, ], ],
            [ 80, src_b, [ 2, 8, 9, ], ],
            [ 81, src_a, [ 1, 6, 10, ], ],
            [ 82, src_b, [ 2, 11, 12, ], ],
        ]

        for i, (t, s, d) in enumerate(data):
            p = to_packet(d)
            for x in p:
                s.push(t, **x)

        while len(sink.get_data()) < len(data):
            yield from tick()

        yield from tick(5)

        d = sink.get_data("data")

        # packets from each source should be in order in the output
        a = []
        b = []
        c = []
        for _, s, p in data:
            if s == src_a:
                a.append(p)
            elif s == src_b:
                b.append(p)
            elif s == src_c:
                c.append(p)
            else:
                assert 0, ("bad packet", p)

        for s in [ a, b, c ]:
            for p in s:
                found = False
                for i, pp in enumerate(d):
                    if p[0] == pp[0]:
                        # this source, so remove the packet
                        found = True
                        del d[i]
                        break
                assert found, (s, p)

        assert len(d) == 0

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd(f"gtk/stream_arb.vcd", traces=[]):
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

    dut = Tee(3, layout, wait_all=False)
    sim_tee(dut, verbose)
    dut = Tee(3, layout, wait_all=True)
    sim_tee(dut, verbose)

    dut = Join(a=[("a", 8)], b=[("b", 8)])
    sim_join(dut, verbose)

    dut = Split(layout=[("a", 12), ("b", 8), ("c", 8)])
    sim_split(dut, verbose)

    dut = GatePacket(layout=[("data", 16)])
    sim_gate(dut, verbose)

    dut = Arbiter(layout=[("data", 16)], n=3)
    sim_arbiter(dut, verbose)

#
#

if __name__ == "__main__":
    test()

#   FIN
