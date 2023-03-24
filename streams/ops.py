#!/bin/env python3

from amaranth import *

from streams.stream import Stream

__all__ = [ "BinaryOp", "Mul", "MulSigned", "Add", "AddSigned"  ]

#
#

class BinaryOp(Elaboratable):

    def __init__(self, iwidth, owidth):
        self.i = Stream(layout=[ ("a", iwidth), ("b", iwidth), ], name="in")
        self.o = Stream(layout=[ ("data", owidth), ], name="out")

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

#   FIN
