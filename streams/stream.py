
from amaranth import *
from amaranth.sim import *

#
#

def to_packet(data, field='data'):
    p = []
    for i, x in enumerate(data):
        d = { 'first': i==0, 'last': i == (len(data)-1), }
        d[field] = x
        p.append(d)
    return p

#
#

class Stream:

    connections = []

    def __init__(self, layout, name=None):
        self.layout = layout
        self.name = name
        self.ready = Signal()
        self.valid = Signal()
        self.first = Signal()
        self.last = Signal()
        for name, width in layout:
            setattr(self, name, Signal(width, name=name))

    @staticmethod
    def connect(source, sink, exclude=[], mapping={}):
        # use with eg.
        # m.d.comb += src.connect(sink, exclude=["first","last"], mapping={"x":"data"})
        statements = []

        for name in [ "valid", "first", "last" ]:
            if not name in exclude:
                i = getattr(source, name)
                o = getattr(sink, name)
                statements += [ o.eq(i) ]

        for name in [ "ready" ]:
            if not name in exclude:
                i = getattr(sink, name)
                o = getattr(source, name)
                statements += [ o.eq(i) ]

        for name, _ in source.layout:
            if not name in exclude:
                oname = mapping.get(name, name)
                i = getattr(source, name)
                o = getattr(sink, oname)
                statements += [ o.eq(i) ]

        # Used by the dot graph generation to track connections
        Stream.connections += [ (source, sink, statements), ]

        return statements

    def connect_sink(self, sink, exclude=[], mapping={}):
        return Stream.connect(self, sink, exclude=exclude, mapping=mapping)

    def _get_layout(self, flags=False):
        layout = self.layout[:]
        if flags:
            layout += [ ("first", 1), ("last", 1) ]
        return layout

    def cat_payload(self, flags=False):
        data = []
        for name, _ in self._get_layout(flags):
            data.append(getattr(self, name))
        return Cat(*data)

    def payload_eq(self, data, flags=False):
        statements = []
        idx = 0
        for name, size in self._get_layout(flags):
            s = getattr(self, name)
            statements += [ s.eq(data[idx:idx+size]) ]
            idx += size
        return statements

    def cat_dict(self, d, flags=False):
        data = []
        for name, size in self._get_layout(flags):
            v = d.get(name, 0)
            data.append(Const(v, shape=size))
        return Cat(*data)

#
#   Stream that simply drops all input

class Sink(Elaboratable):

    def __init__(self, layout):
        self.i = Stream(layout, name="Sink")

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += self.i.ready.eq(0)

        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        return m

#
#   Stream with in/out that inserts initial packet(s) of data 

class StreamInit(Elaboratable):

    def __init__(self, data, layout):
        assert len(data)
        self.i = Stream(layout, name="StreamInit_i")
        self.o = Stream(layout, name="StreamInit_o")
        self.clr = Signal()

        # internal stream from Array
        self.data = Array( [ self.i.cat_dict(d, flags=True) for d in data ] )
        self.s = Stream(layout, name="StreamInit_s")

        self.idx = Signal(range(len(data)+1))
        self.done = Signal()
        self.wait = Signal(reset=1)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.clr):
            m.d.sync += [
                self.idx.eq(0),
                self.done.eq(0),
                self.wait.eq(1),
                self.s.valid.eq(0),
            ]
            m.d.sync += self.s.payload_eq(self.data[0], flags=True)

        with m.If(self.done):
            m.d.comb += Stream.connect(self.i, self.o)
            m.d.sync += self.s.valid.eq(0)

        with m.Else():
            m.d.comb += Stream.connect(self.s, self.o)

            m.d.sync += self.s.payload_eq(self.data[self.idx], flags=True)

            with m.If(~self.o.valid):
                m.d.sync += self.s.valid.eq(1)

            with m.If(self.s.valid & self.s.ready):
                m.d.sync += [
                    self.s.valid.eq(0),
                    self.idx.eq(self.idx + 1),
                ]

                with m.If(self.idx == (len(self.data) - 1)):
                    m.d.sync += self.wait.eq(0)

            with m.If(~self.wait):
                m.d.sync += self.done.eq(1)

        return m

    def ports(self):
        return []

#
#   Eat the first N words in a Stream

class StreamNull(Elaboratable):
    
    def __init__(self, n, layout):
        self.n = n
        self.i = Stream(layout)
        self.o = Stream(layout)
        self.s = Stream(layout)
        self.null = Stream(layout)

        self.done = Signal()
        self.count = Signal(range(n+1))

    def elaborate(self, platform):
        m = Module()

        with m.If(self.done):
            m.d.comb += Stream.connect(self.i, self.o)

        with m.Else():
            m.d.comb += Stream.connect(self.s, self.o)
            m.d.comb += Stream.connect(self.i, self.null)

            with m.If(~self.null.ready):
                with m.If(self.count == self.n):
                    m.d.sync += self.done.eq(1)
                with m.Else():
                    m.d.sync += self.null.ready.eq(1)

            with m.If(self.null.valid & self.null.ready):
                m.d.sync += [
                    self.null.ready.eq(0),
                    self.count.eq(self.count + 1),
                ]

        return m

    def ports(self):
        return []

#
#   Copy input to multiple outputs

class StreamTee(Elaboratable):

    def __init__(self, n, layout, wait_all=False):
        self.wait_all = wait_all
        self.i = Stream(layout, name="StreamTee_i")
        self.o = []
        for i in range(n):
            s = Stream(layout, name=f"StreamTee_o[{i}]")
            self.o += [ s ]
            setattr(self, f"_o_{i}", s) # so that dot graph can find it!

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += self.i.ready.eq(0)
            for s in self.o:
                exclude = [ "valid", "ready", ]
                m.d.sync += Stream.connect(self.i, s, exclude=exclude)
                m.d.sync += [
                    s.valid.eq(1),
                ]

        for s in self.o:
            with m.If(s.ready & s.valid):
                m.d.sync += s.valid.eq(0)

        with m.If(~self.i.ready):
            if self.wait_all:
                m.d.sync += self.i.ready.eq(1)
                # but clear it if any of the outputs are still waiting?
                for s in self.o:
                    with m.If(s.valid):
                        m.d.sync += self.i.ready.eq(0)
            else:
                # set i.ready if any of the outputs has no data to send
                for s in self.o:
                    with m.If(~s.valid):
                        m.d.sync += self.i.ready.eq(1)

        return m

    def ports(self):
        return []

#
#    Join 2 Streams.
#
#    Wait until both inputs ready, read both and merge to output
    
class Join(Elaboratable):

    def __init__(self, width):
        l1 = ("a", width)
        l2 = ("b", width)
        self.i = [
            Stream(layout=[ l1 ], name="in1"),
            Stream(layout=[ l2 ], name="in2"),
        ]
        # make sure they get graphed ...
        self._1 = self.i[0]
        self._2 = self.i[1]

        self.o = Stream(layout=[ l1, l2 ], name="output")

    def elaborate(self, platform):
        m = Module()

        # wait for all inputs valid before giving ready on both

        valid = Cat( [ s.valid for s in self.i ] )
        ready = Cat( [ s.ready for s in self.i ] )
        on    = Cat( [ Const(1,1) for _ in self.i ] )

        with m.If((valid == on) & ~self.o.valid):
            m.d.sync += [
                self.i[0].ready.eq(1),
                self.i[1].ready.eq(1),
            ]

        with m.If((valid == on) & (ready == on)):
            m.d.sync += self.o.valid.eq(1)
            c = [
                [   0, [ "valid", "ready" ] ],
                [   1, [ "valid", "ready", "first", "last" ] ],
            ]
            for idx, exclude in c:
                m.d.sync += self.i[idx].ready.eq(0)
                m.d.sync += Stream.connect(self.i[idx], self.o, exclude=exclude)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        return m

#   FIN
