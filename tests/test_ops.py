#!/bin/env python3

from amaranth import *
from amaranth.sim import *

from streams.stream import Stream
from streams.sim import SourceSim, SinkSim

from streams.ops import *

#
#

def sim_ops(m, check, verbose):
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
    with sim.write_vcd("gtk/ops_mul.vcd", traces=m.ports()):
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

def test(verbose):

    dut = Mul(16, 32)
    sim_ops(dut, check_mul, verbose)

    dut = MulSigned(16, 32)
    sim_ops(dut, check_mul_signed, verbose)

    dut = Add(16, 32)
    sim_ops(dut, check_add, verbose)

    dut = AddSigned(16, 32)
    sim_ops(dut, check_add_signed, verbose)

#   FIN
