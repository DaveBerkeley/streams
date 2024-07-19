#!/bin/env python3

from amaranth import *

from streams.stream import Stream, add_name

__all__ = [ 
    "BinaryOp", "Mul", "MulSigned", "Add", "AddSigned", "Sum", "SumSigned",
    "UnaryOp", "Abs", "Delta", "BitToN",
    "ConstSource",
]

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

    def __init__(self, iwidth, owidth, name=None):
        self.i = Stream(layout=[("data", iwidth),], name=add_name(name, "in"))
        self.o = Stream(layout=[("data", owidth),], name=add_name(name, "out"))
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

#
#

class UnaryOp(Elaboratable):

    def __init__(self, layout, name=None, fields=[]):
        self.i = Stream(layout=layout, name="i")
        self.o = Stream(layout=layout, name="o")
        if (len(layout) == 1) and not fields:
            fields = [ layout[0][0] ]
        assert fields, (fields, "no fields specified")
        for field in fields:
            assert field in [ n for n,_ in layout ], (field, "not in payload")
        self.fields = fields
        self.enable = Signal(reset=1)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i.valid & self.i.ready):
            exclude = [ "valid", "ready", ]
            m.d.sync += Stream.connect(self.i, self.o, exclude=exclude)
            m.d.sync += [
                self.i.ready.eq(0),
                self.o.valid.eq(self.enable),
            ]
            for name, _ in self.i.get_layout():
                si = getattr(self.i, name)
                so = getattr(self.o, name)
                if not name in self.fields:
                    m.d.sync += [ so.eq(si) ]
                else:
                    self.op(m, name, si, so)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        with m.If((~self.i.ready) & ~self.o.valid):
            m.d.sync += self.i.ready.eq(1)

        return m

#
#

class Abs(UnaryOp):

    def __init__(self, layout, name="Abs", fields=[]):
        UnaryOp.__init__(self, layout, name, fields)

    def elaborate(self, platform):
        m = UnaryOp.elaborate(self, platform)
        return m

    def op(self, m, name, si, so):
        w = si.shape().width
        s = Signal(signed(w))
        m.d.comb += [ s.eq(si) ]
        with m.If(s < 0):
            m.d.sync +=  [ so.eq(-s) ]
        with m.Else():
            m.d.sync += [ so.eq(s) ]

#
#

class Delta(UnaryOp):

    def __init__(self, layout, name="Delta", fields=[]):
        UnaryOp.__init__(self, layout, name, fields)

    def elaborate(self, platform):
        m = UnaryOp.elaborate(self, platform)
        m.d.comb += self.enable.eq(0)
        for field in self.fields:
            si = getattr(self.i, field)
            so = getattr(self.o, field)
            with m.If(si != so):
                m.d.comb += self.enable.eq(1)
        return m

    def op(self, m, name, si, so):
        m.d.sync += [ so.eq(si) ]

#
#

class BitToN(UnaryOp):

    def __init__(self, layout, name="BitToN", fields=[]):
        UnaryOp.__init__(self, layout, name, fields)
        assert len(self.fields) == 1, "only one field allowed"

    def elaborate(self, platform):
        m = UnaryOp.elaborate(self, platform)
        # don't enable tx if input is 00000
        s = getattr(self.i, self.fields[0])
        m.d.comb += self.enable.eq(s.any())
        return m

    def op(self, m, name, si, so):
        for i,s in enumerate(si[:]):
            with m.If(s):
                m.d.sync += [ so.eq(i) ]

#
#   Sources

class ConstSource(Elaboratable):

    def __init__(self, layout, fields={}):
        self.o = Stream(layout=layout, name="o")
        assert fields, "no const fields specified"
        self.fields = fields 
        outs = [ n for n,_ in layout ]
        for name, k in fields.items():
            assert name in outs, ("unknown field", name)

    def elaborate(self, platform):
        m = Module()

        for name, k in self.fields.items():
            s = getattr(self.o, name)
            m.d.comb += s.eq(k)

        m.d.comb += [
            self.o.first.eq(1),
            self.o.last.eq(1),
        ]

        with m.If(~self.o.valid):
            m.d.sync += self.o.valid.eq(1)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        return m

#   FIN
