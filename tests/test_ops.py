#!/bin/env python3

from amaranth import *
from amaranth.sim import *

import sys
spath = "../streams"
if not spath in sys.path:
    sys.path.append(spath)

from streams.stream import Stream
from streams.sim import SourceSim, SinkSim

from streams.ops import *

#
#

def sim_ops(m, check, vcd, verbose):
    print("test binaryop")
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
            [   (0, 0), (0, 1), (1, 0,), (1, 1), ],
            [   (1, -1,), (-1, 1), (-1, -1), ],
            [   (10, 1,), (16, 3), (200, 10), (13, 7), ],
        ]

        for p in data:
            for i, (a, b) in enumerate(p):
                first = i == 0
                last = i == (len(p) - 1)
                src.push(10, a=a, b=b, first=first, last=last)

        yield from tick(50)

        check(data, sink.get_data("data"))

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/" + vcd, traces=m.ports()):
        sim.run()

#
#

def check_op(data, result, op=None):
    for i, p in enumerate(data):
        for j, (a, b) in enumerate(p):
            r = result[i][j]
            v = op(a, b)
            assert v == r, (i, j, a, b, r, v)

def clip(x, width):
    return x & ((1 << width) - 1)

def check_mul(data, result):
    def mul_unsigned(a, b):
        return clip(clip(a, 16) * clip(b, 16), 32)
    check_op(data, result, op=mul_unsigned)

def check_mul_signed(data, result):
    def mul_signed(a, b):
        return clip(a * b, 32)
    check_op(data, result, op=mul_signed)

def check_add(data, result):
    def add_unsigned(a, b):
        return clip(clip(a, 16) + clip(b, 16), 32)
    check_op(data, result, op=add_unsigned)

def check_add_signed(data, result):
    def add_signed(a, b):
        return clip(a + b, 32)
    check_op(data, result, op=add_signed)

#
#

def sim_sum(m, check, vcd, verbose):
    print("test sum")
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
            [ 1, 2, 3, 4, ],
            [ 100, ],
            [ 0, ],
            [ -1, ],
            [ -1, 1, ],
            [ 1, 2, 4, 8, 16, 32, 64, ],
            [ -1, -2, -4, -8, -16, -32, -64, ],
        ]

        for p in data:
            for i, d in enumerate(p):
                first = i == 0
                last = i == (len(p) - 1)
                src.push(10, data=d, first=first, last=last)

        yield from tick(100)

        check(data, sink.get_data("data"))

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/" + vcd, traces=m.ports()):
        sim.run()

def check_sum(data, result):
    for i, p in enumerate(data):
        s = [ clip(x, 16) for x in p ]
        ss = clip(sum(s), 32)
        assert result[0][i] == ss, (i, p, result)

def check_sum_signed(data, result):
    for i, p in enumerate(data):
        ss = sum(p)
        ss = clip(ss, 32)
        assert result[0][i] == ss, (i, p, result, ss)

#
#

def sim_unary(m, fn, verbose, title, vcd, data):
    print("test", title)
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

        for p in data:
            for i, d in enumerate(p):
                first = i == 0
                last = i == (len(p) - 1)
                src.push(10, data=d, first=first, last=last)

        yield from tick(100)

        p = sink.get_data("data")
        fn(p)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/" + vcd):
        sim.run()

#
#

def sim_abs(m, verbose):
    data = [
        [ 1, 2, 3, 4, ],
        [ 100, ],
        [ 0, ],
        [ -1, ],
        [ -1, 1, ],
        [ 1, 2, 4, 8, 16, 32, 64, ],
        [ -1, -2, -4, -8, -16, -32, -64, ],
    ]

    def fn(p):
        for i,pp in enumerate(data):
            rr = p[i]
            assert len(pp) == len(rr), (pp, rr)
            for j in range(len(pp)):
                assert rr[j] == abs(pp[j]), (rr, pp)
    sim_unary(m, fn, verbose, "abs", "abs.cvd", data)

def flatten(packets, filt=None):
    if filt is None:
        def filt(a): return a
    r = []
    for packet in packets:
        for d in packet:
            r.append(filt(d))
    return r

def sim_delta(m, verbose):
    data = [
        [ 0, 0, 1, 100, 100, 100, 100, 10, 10, ],
        [ 0, 0, 1, 100, 100, 100, 100, 10, ],
        [ -1, -2, -1, 0, 0, 0, 0, 0, 10, ],
    ]
    expect = [ 1, 100, 10, 0, 1, 100, 10, -1, -2, -1, 0, 10 ]
    # delta breaks the packet structure : 
    # it can't know a particular change is the last in a packet
    def mask(a): return a & 0xFFFF
    def fn(p):
        p = flatten(p, filt=mask)
        ex = [ mask(x) for x in expect ]
        assert p == ex, (p, ex)

    sim_unary(m, fn, verbose, "delta", "delta.vcd", data)

#
#

def sim_bit_to_n(m, verbose):
    data = [
        [ 0, 1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 0, 32, 33, ],
        [ 15, 0, 27, ],
    ]
    expect = [
        [ 0, 1, 1, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5  ],
        [ 3, 4 ],
    ]
    def fn(p):
        assert p == expect, (p, expect)

    sim_unary(m, fn, verbose, "bit2n", "bit2n.vcd", data)

#
#

def sim_const(m, verbose):
    print("test const")
    sim = Simulator(m)

    sink = SinkSim(m.o)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()

    def proc():

        yield from tick(100)

        p = sink.get_data("data")
        assert p
        for packet in p:
            assert packet == [ 123 ]

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/const.vcd"):
        sim.run()

#
#

def sim_bit_change(m, verbose):
    print("test bit_change")
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
            [ 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 ],
            [ 0, 0, 1, 3, 7, 15, 0, 15,  ],
        ]

        for p in data:
            for i, d in enumerate(p):
                first = i == 0
                last = i == (len(p) - 1)
                src.push(10, data=d, r=1, g=2, b=3, first=first, last=last)

        while not src.done():
            yield from tick(1)

        yield from tick(30)

        def make_packet(n):
            p = []
            for i in range(4):
                if (1 << i) & n:
                    state = 1
                else:
                    state = 0
                p.append((i, state, 1, 2, 3))
            return p

        p = sink.get_data()
        f = flatten(data)
        for i, packet in enumerate(p):
            t = [ (d['data'], d['state'], d['r'], d['g'], d['b'], ) for d in packet ]
            pp = make_packet(f[i])
            assert t == pp, (t, pp)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/bit_change.vcd"):
        sim.run()

#
#

def sim_decimate(m, verbose):
    print("test decimate")
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

        a = list(range(100))
        b = list([ (i+2) for i in range(100) ])

        for i in range(len(a)):
            src.push(0, a=a[i], b=b[i])

        while not src.done():
            yield from tick(1)

        yield from tick(30)

        ra = sink.get_data("a")[0]
        rb = sink.get_data("b")[0]
        xa = [ a[i] for i in range(0, len(a), 4) ]
        xb = [ b[i] for i in range(0, len(a), 4) ]
        assert ra == xa, (ra, xa)
        assert rb == xb, (rb, xb)

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/decimate.vcd"):
        sim.run()

#
#

def sim_max(m, verbose):
    print("test max")
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

        a = [ 0, 1, 10, 100, 1000 ]
        b = [ 1, 3, 5, 50, 2000 ]

        for i in range(len(a)):
            src.push(10, a=a[i], b=b[i])

        while not src.done():
            yield from tick(1)

        yield from tick(30)

        r = sink.get_data("data")
        assert r == [ [ 1, 3, 10, 100, 2000 ] ], r

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/max.vcd"):
        sim.run()

#
#

def sim_enum(m, verbose):
    print("test enum")
    sim = Simulator(m)

    sink = SinkSim(m.o)
    src = SourceSim(m.i, verbose=verbose)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from sink.poll()
            yield from src.poll()

    def proc():

        data = [
            [ 10, [ 1, 2, 3, 4 ] ],
            [ 10, [ 100 ] ],
            [ 10, [ 0, 1, 2, 3, 10 ] ],
        ]

        for t, packet in data:
            for i, d in enumerate(packet):
                src.push(t, data=d, first=(i==0), last=(i == (len(packet)-1)))

        yield from tick(10)

        while not src.done():
            yield from tick(1)

        yield from tick(10)

        d = sink.get_data("data")
        a = sink.get_data("addr")
        x = sink.get_data("aux")

        assert d[0] == [ 1, 2, 3, 4 ], d[0]
        assert x[0] == [ 0, 0, 0, 0 ], x[0]
        assert a[0] == [ 3, 4, 5, 6 ], a[0]

        assert d[1] == [ 100 ], d[1]
        assert x[1] == [ 0 ], x[1]
        assert a[1] == [ 3, ], a[1]

        assert d[2] == [ 0, 1, 2, 3, 10 ], d[2]
        assert x[2] == [ 0, 0, 0, 0, 0 ], x[2]
        assert a[2] == [ 3, 4, 5, 6, 7 ], a[2]

    sim.add_clock(1 / 50e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/enum.vcd", traces=[]):
        sim.run()

#
#

def test(verbose):

    if 1:
        dut = Mul(16, 32)
        sim_ops(dut, check_mul, "ops_mul.vcd", verbose)

        dut = MulSigned(16, 32)
        sim_ops(dut, check_mul_signed, "ops_muls.vcd", verbose)

        dut = Add(16, 32)
        sim_ops(dut, check_add, "ops_add.vcd", verbose)

        dut = AddSigned(16, 32)
        sim_ops(dut, check_add_signed, "ops_adds.vcd", verbose)

        dut = Sum(16, 32)
        sim_sum(dut, check_sum, "ops_sum.vcd", verbose)

        dut = SumSigned(16, 32)
        sim_sum(dut, check_sum_signed, "ops_sums.vcd", verbose)

        dut = Abs(layout=[("data", 16)]) 
        sim_abs(dut, verbose)

        dut = Delta(layout=[("data", 16)], fields=["data"]) 
        sim_delta(dut, verbose)

        dut = BitToN(layout=[("data", 16)]) 
        sim_bit_to_n(dut, verbose)

        dut = ConstSource(layout=[("data", 16)], fields={"data": 123})
        sim_const(dut, verbose)

        dut = BitState(layout=[("data", 16), ("r", 8), ("g", 8), ("b", 8)], field="data")
        sim_bit_change(dut, verbose)

    dut = Decimate(4, layout=[("a", 16), ("b", 8)])
    sim_decimate(dut, verbose)

    dut = Max(16, 16);
    sim_max(dut, verbose)

    layout = [("data", 16), ("aux", 4) ]
    dut = Enumerate(layout=layout, idx=[("addr", 8)], offset=3)
    sim_enum(dut, verbose)

#
#

if __name__ == "__main__":
    test(False)

#   FIN
