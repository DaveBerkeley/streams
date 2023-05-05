#!/bin/env python3

from amaranth import *

from streams.stream import Stream, add_name

__all__ = [ "BinaryOp", "Mul", "MulSigned", "Add", "AddSigned", "Sum", "SumSigned" ]

#
#

class BinaryOp(Elaboratable):

    def __init__(self, iwidth, owidth, name=None):
        self.i = Stream(layout=[ ("a", iwidth), ("b", iwidth), ], name=add_name(name, "in"))
        self.o = Stream(layout=[ ("data", owidth), ], name=add_name(name, "out"))

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i.valid & self.i.ready):
            exclude = [ "valid", "ready", "a", "b" ]
            m.d.sync += Stream.connect(self.i, self.o, exclude=exclude)
            m.d.sync += self.op(m, self.i.a, self.i.b)
            m.d.sync += [
                self.i.ready.eq(0),
                self.o.valid.eq(1),
            ]

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        with m.If((~self.i.ready) & ~self.o.valid):
            m.d.sync += self.i.ready.eq(1)

        return m

    def ports(self): return []

#
#

class Mul(BinaryOp):

    def op(self, m, a, b):
        return [ self.o.data.eq(a * b), ]

class Add(BinaryOp):

    def op(self, m, a, b):
        return [ self.o.data.eq(a + b), ]

class MulSigned(Mul):

    def op(self, m, a, b):
        sa = Signal(signed(a.shape().width))
        sb = Signal(signed(b.shape().width))
        m.d.comb += [ sa.eq(a), sb.eq(b), ]
        return Mul.op(self, m, sa, sb)

class AddSigned(Add):

    def op(self, m, a, b):
        sa = Signal(signed(a.shape().width))
        sb = Signal(signed(b.shape().width))
        m.d.comb += [ sa.eq(a), sb.eq(b), ]
        return Add.op(self, m, sa, sb)

#
#   Sum the data in a packet

class Sum(Elaboratable):

    def __init__(self, iwidth, owidth):
        self.i = Stream(layout=[("data", iwidth),], name="in")
        self.o = Stream(layout=[("data", owidth),], name="out")
        self.zero = Const(0, owidth)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += self.i.ready.eq(0)

            with m.If(self.i.first):
                # reset the sum on 'first' data
                m.d.sync += self.op(m, self.zero, self.i.data)
            with m.Else():
                # accumulate
                m.d.sync += self.op(m, self.o.data, self.i.data)

            with m.If(self.i.last):
                # 'last' data in packet, output the sum
                m.d.sync += self.o.valid.eq(1)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        with m.If((~self.i.ready) & ~self.o.valid):
            m.d.sync += self.i.ready.eq(1)

        return m

    def op(self, m, a, b):
        return [ self.o.data.eq(a + b), ]

    def ports(self): return []

class SumSigned(Sum):

    def op(self, m, a, b):
        sa = Signal(signed(a.shape().width))
        # need to sign extend b
        sb = Signal(signed(b.shape().width))
        m.d.comb += [ sa.eq(a), sb.eq(b), ]
        return Sum.op(self, m, sa, sb)

#   FIN
