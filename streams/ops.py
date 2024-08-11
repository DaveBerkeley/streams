#!/bin/env python3

from amaranth import *

from streams.stream import Stream, add_name

__all__ = [ 
    "BinaryOp", "Mul", "MulSigned", "Add", "AddSigned", "Sum", "SumSigned", "Max",
    "UnaryOp", "Abs", "Delta", "BitToN", "Decimate", "Enumerate",
    "ConstSource", "BitState",
]

#
#

def get_field(layout, field):
    for name, width in layout:
        if field == name:
            return name, width
    return None

def field_in_layout(layout, field):
    return not (get_field(layout, field) is None)

def num_bits(n):
    if n == 0:
        raise Exception("zero bits")
    if n == 1:
        return 1
    bits = 0
    if n:
        n -= 1
    while n:
        bits += 1
        n >>= 1
    return bits

assert num_bits(1) == 1
assert num_bits(6) == 3
assert num_bits(7) == 3
assert num_bits(8) == 3
assert num_bits(9) == 4

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

class Max(BinaryOp):

    def op(self, m, a, b):
        sa = Signal(signed(a.shape().width))
        sb = Signal(signed(b.shape().width))
        m.d.comb += [
            sa.eq(a),
            sb.eq(b),
        ]
        with m.If(sa > sb):
            m.d.sync += self.o.data.eq(sa)
        with m.Else():
            m.d.sync += self.o.data.eq(sb)
        return []

#
#

class UnaryOp(Elaboratable):

    def __init__(self, layout, name=None, fields=[]):
        if name:
            self.name = name
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
#

class Decimate(UnaryOp):

    def __init__(self, n, layout, name=None):
        fields = layout[0][0]
        UnaryOp.__init__(self, layout, name or f"Decimate({n})", fields=[fields])
        assert n > 1
        self.n = n - 1
        self.count = Signal(range(n+1))

    def elaborate(self, platform):
        m = UnaryOp.elaborate(self, platform)

        # only pass every Nth signal
        m.d.comb += self.enable.eq(self.count == 0)
        return m

    def op(self, m, name, si, so):
        m.d.sync += self.count.eq(self.count + 1)

        with m.If(self.count == self.n):
            m.d.sync += self.count.eq(0)

        m.d.sync += [ so.eq(si) ]

#
#   Add an index field to a packet, starting with 'offset', 
#   incrementing with each data element.

class Enumerate(UnaryOp):

    def __init__(self, idx=[("idx", 8)], offset=0, **kwargs):
        if not "fields" in kwargs:
            # default to first field in layout (it doesn't matter which)
            fields = list([ p[0] for p in kwargs["layout"] ])
            kwargs["fields"] = [ fields[0] ]
        if not "name" in kwargs:
            if offset:
                name = f"Enumerate(offset={offset})"
            else:
                name = f"Enumerate()"
            kwargs["name"] = name
        super().__init__(**kwargs)
        assert len(idx) == 1, idx
        self.idx_name, w = idx[0]
        self.offset = Const(offset)
        layout = self.i.get_layout()
        # overwrite the default output stream, adding the idx
        self.o = Stream(layout=layout + idx, name="o")

        self.idx = Signal(w)

    def op(self, m, name, si, so):
        s = getattr(self.o, self.idx_name)
        m.d.sync += [
            so.eq(si),
            s.eq(self.idx + self.offset),
            self.idx.eq(self.idx + 1),
        ]

        with m.If(self.i.last):
            m.d.sync += self.idx.eq(0)

#
#

class BitState(Elaboratable):

    def __init__(self, layout, field="data", state_field="state"):
        assert field_in_layout(layout, field), (field, "not in layout")
        self.field = field
        self.state_field = state_field
        self.i = Stream(layout=layout, name="i")
        name, width = get_field(layout, field)

        # save the input i.field 
        self.idata = Signal(width)

        olayout = []
        for name,w in layout:
            if name == field:
                owidth = num_bits(w)
                olayout.append((name, owidth))
            else:
                olayout.append((name, w))
        olayout.append((state_field, 1))

        self.o = Stream(layout=olayout, name="o")
        self.bit = Signal(range(owidth+1))
        self.end = Const(owidth)

        class Others:

            # save 'other' fields of the payload
            def __init__(self, bc):
                self.fields = []
                for name,w in bc.i.get_layout():
                    if not name in  [ bc.field, bc.state_field ]: 
                        s = Signal(w)
                        setattr(self, name, s)
                        self.fields.append(name)
            def eq(self, s, swap=False):
                r = []
                for name in self.fields:
                    dst = getattr(self, name)
                    src = getattr(s, name)
                    if swap:
                        dst, src = src, dst
                    r += [ dst.eq(src) ]
                return r

        self.others = Others(self)

    def tx(self, m):
        m.d.sync += [
            self.o.valid.eq(1),
            self.o.first.eq(self.bit == 0),
            self.o.last.eq(self.bit == (self.end-1)),
        ]
        m.d.sync += self.others.eq(self.o, swap=True)

        so = getattr(self.o, self.field)
        m.d.sync += so.eq(self.bit)

        state = getattr(self.o, self.state_field)
        m.d.sync += state.eq(self.idata.bit_select(self.bit, width=1))

    def elaborate(self, platform):
        m = Module()

        with m.FSM(reset="INIT"):

            with m.State("INIT"):
                m.d.sync += self.i.ready.eq(1)
                m.next = "RX"

            with m.State("RX"):
                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += self.others.eq(self.i)
                    s = getattr(self.i, self.field)
                    m.d.sync += self.idata.eq(s)
                    m.d.sync += self.i.ready.eq(0)
                    m.d.sync += self.bit.eq(0)
                    m.next = "TX"

            with m.State("TX"):
                with m.If(self.o.ready & self.o.valid):
                    m.d.sync += self.o.valid.eq(0)
                    m.d.sync += self.bit.eq(self.bit + 1)

                with m.If(~self.o.valid):
                    with m.If(self.bit == self.end):
                        m.d.sync += self.i.ready.eq(1)
                        m.next = "RX"
                    with m.Else():
                        self.tx(m)

        return m

#
#   Sources

class ConstSource(Elaboratable):

    def __init__(self, layout, name=None, fields={}):
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
