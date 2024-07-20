
from enum import IntEnum

from amaranth import *

#
#

def to_packet(data, field='data'):
    p = []
    for i, x in enumerate(data):
        d = { 'first': i==0, 'last': i == (len(data)-1), }
        d[field] = x
        p.append(d)
    return p

def add_name(name, label):
    if not name:
        return label
    return name + "_" + label

#
#

class Stream:

    connections = []

    @staticmethod
    def add_dot(source, sink, statements, exclude=None, fn=None):
        Stream.connections += [ (source, sink, statements, exclude, fn), ]

    def __init__(self, layout, name=None):
        self._layout = layout
        self.name = name
        self.ready = Signal(name=add_name(name, "ready"))
        self.valid = Signal(name=add_name(name, "valid"))
        self.first = Signal(name=add_name(name, "first"))
        self.last = Signal(name=add_name(name, "last"))
        for payload, width in layout:
            setattr(self, payload, Signal(width, name=add_name(name, payload)))

    @staticmethod
    def connect(source, sink, exclude=[], mapping={}, fn={}, silent=False):
        # use with eg.
        # m.d.comb += src.connect(sink, exclude=["first","last"], mapping={"x":"data"}, fn={"x":shift_x})
        statements = []

        used = {}

        def op(name, i, o):
            f = fn.get(name)
            if f is None:
                return [ o.eq(i) ]
            used[name] = True
            return [ f(name, i, o) ]

        for name in [ "valid", "first", "last" ]:
            if not name in exclude:
                i = getattr(source, name)
                o = getattr(sink, name)
                statements += op(name, i, o)

        for name in [ "ready" ]:
            if not name in exclude:
                i = getattr(sink, name)
                o = getattr(source, name)
                statements += op(name, i, o)

        for name, _ in source.get_layout():
            if not name in exclude:
                oname = mapping.get(name, name)
                i = getattr(source, name)
                o = getattr(sink, oname)
                statements += op(name, i, o)

        # Used by the dot graph generation to track connections
        if not silent:
            Stream.add_dot(source, sink, statements, exclude=exclude, fn=fn)

        for key in fn.keys():
            assert used.get(key), f"function for '{key}' not used"

        return statements

    def connect_sink(self, sink, exclude=[], mapping={}, fn={}, silent=False):
        return Stream.connect(self, sink, exclude=exclude, mapping=mapping, fn=fn, silent=silent)

    def get_layout(self, flags=False):
        layout = self._layout[:]
        if flags:
            layout += [ ("first", 1), ("last", 1) ]
        return layout

    def cat_payload(self, flags=False):
        data = []
        for name, _ in self.get_layout(flags):
            data.append(getattr(self, name))
        return Cat(*data)

    def payload_eq(self, data, flags=False):
        statements = []
        idx = 0
        for name, size in self.get_layout(flags):
            s = getattr(self, name)
            statements += [ s.eq(data[idx:idx+size]) ]
            idx += size
        return statements

    def cat_dict(self, d, flags=False):
        data = []
        for name, size in self.get_layout(flags):
            v = d.get(name, 0)
            data.append(Const(v, shape=size))
        return Cat(*data)

    def __repr__(self):
        return f'Stream("{self.name}", {self._layout})'

#
#

class Copy(Elaboratable):

    def __init__(self, layout, name=None):
        self.i = Stream(layout, name=add_name(name, "in"))
        self.o = Stream(layout, name=add_name(name, "out"))

    def elaborate(self, platform):
        m = Module()

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
                self.o.valid.eq(1),
            ]
            m.d.sync += self.o.payload_eq(self.i.cat_payload(flags=True), flags=True)

        with m.If((~self.i.ready) & ~self.o.valid):
            m.d.sync += self.i.ready.eq(1)

        return m

#
#   Stream that simply drops all input

class Sink(Elaboratable):

    def __init__(self, layout, name=None):
        self.i = Stream(layout, name=add_name(name, "sink"))

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

    def __init__(self, data, layout, name=None):
        assert len(data)
        self.i = Stream(layout, name=add_name(name, "in"))
        self.o = Stream(layout, name=add_name(name, "out"))
        self.clr = Signal()

        # internal stream from Array
        self.data = Array( [ self.i.cat_dict(d, flags=True) for d in data ] )
        self.s = Stream(layout, name=add_name(name, "rom"))

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

class Tee(Elaboratable):

    def __init__(self, n, layout, wait_all=False, name=None):
        self.wait_all = wait_all
        self.i = Stream(layout, name=add_name(name, "in"))
        self.o = []
        for i in range(n):
            s = Stream(layout, name=add_name(name, f"out[{i}]"))
            self.o += [ s ]
            setattr(self, f"_o{i}", s) # so that dot graph can find it!

    def elaborate(self, platform):
        m = Module()

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += self.i.ready.eq(0)
            for s in self.o:
                exclude = [ "valid", "ready", ]
                m.d.sync += Stream.connect(self.i, s, exclude=exclude)
                m.d.sync += s.valid.eq(1)

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
#    Join N Streams.
#
#    Wait until all inputs ready, read all and merge to output
    
class Join(Elaboratable):

    @staticmethod
    def is_layout(layout):
        for name, width in layout:
            if not isinstance(name, str):
                return False;
            if not isinstance(width, int):
                return False;
        return True

    @staticmethod
    def has_field(layout, check):
        names = [ x[0] for x in layout ]
        for name, _ in check:
            if name in names:
                return True
        return False

    def __init__(self, first_field=None, name=None, **kwargs):
        self.first_field = first_field
        # eg Join(a=[("x", 12)], b=[("y", 12)])
        self.i = []
        layouts = []
        self.fields = []
        for i, (payload, layout) in enumerate(kwargs.items()):
            # check we aren't overwriting anything
            assert not hasattr(self, payload)
            # check it is a valid layout
            assert self.is_layout(layout)
            # check for duplicate fields
            assert not self.has_field(layouts, layout)
            s = Stream(layout=layout, name=add_name(name, payload))
            setattr(self, payload, s)
            #print("join", s, payload, layout)
            self.i.append(s)
            layouts += layout
            self.fields.append(payload)

        self.o = Stream(layout=layouts, name=add_name(name, ','.join(self.fields)))

    def elaborate(self, platform):
        m = Module()

        # wait for all inputs valid before giving ready on both

        valid = Cat( [ s.valid for s in self.i ] )
        ready = Cat( [ s.ready for s in self.i ] )
        on    = Cat( [ Const(1,1) for _ in self.i ] )

        with m.If((valid == on) & ~self.o.valid):
            for s in self.i:
                m.d.sync += s.ready.eq(1)

        with m.If((valid == on) & (ready == on)):
            m.d.sync += self.o.valid.eq(1)
            for idx in range(len(self.i)):
                if self.fields[idx] == self.first_field:
                    exclude = [ "valid", "ready" ] # get first/last from this stream
                else:
                    exclude = [ "valid", "ready", "first", "last" ]
                m.d.sync += self.i[idx].ready.eq(0)
                m.d.sync += Stream.connect(self.i[idx], self.o, exclude=exclude)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        return m

#
#   Split : takes input stream with multiple payloads, splits into N output streams,
#   one for each payload.

class Split(Elaboratable):

    def __init__(self, layout, name=None):
        self.i = Stream(layout=layout, name=add_name(name, "in"))

        for payload, width in layout:
            s = Stream(layout=[ (payload, width), ], name=add_name(name, payload))
            setattr(self, payload, s)

    def elaborate(self, platform):
        m = Module()

        # Tx outputs
        for name, _ in self.i.get_layout():
            s = getattr(self, name)
            with m.If(s.valid & s.ready):
                m.d.sync += s.valid.eq(0)

        # If all outputs are ready, accept input
        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)
            for name, _ in self.i.get_layout():
                s = getattr(self, name)
                with m.If(s.valid):
                    m.d.sync += self.i.ready.eq(0)

        # read input
        with m.If(self.i.valid & self.i.ready):
            m.d.sync += self.i.ready.eq(0)
            # copy each payload to its output
            for name, _ in self.i.get_layout():
                s = getattr(self, name)
                f = getattr(s, name)
                v = getattr(self.i, name)
                m.d.sync += [
                    f.eq(v),
                    s.valid.eq(1),
                ]

        return m

#
#   Only enable i.ready when 'en'able is set.

class Gate(Elaboratable):

    def __init__(self, layout=None, name=None):
        self.i = Stream(layout=layout, name=add_name(name, "in"))
        self.o = Stream(layout=layout, name=add_name(name, "out"))
        self.en = Signal(name=add_name(name, "en"))

    def elaborate(self, platform):
        m = Module()

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += self.i.ready.eq(0)
            m.d.sync += self.o.valid.eq(1)
            m.d.sync += self.o.payload_eq(self.i.cat_payload())

        with m.If(self.en & ~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        return m

#
#   Allow a Packet through only when en is hi.
#   Once the packet has started, allow it to complete.

class GatePacket(Elaboratable):

    def __init__(self, layout=None, name=None):
        self.i = Stream(layout=layout, name=add_name(name, "in"))
        self.o = Stream(layout=layout, name=add_name(name, "out"))
        self.en = Signal()

        self.allow = Signal()
        self.iready = Signal()

    def elaborate(self, platform):
        m = Module()

        start = self.en & self.o.ready & self.i.first & self.i.valid & (~self.allow)

        m.d.comb += self.i.ready.eq(self.iready & self.allow)

        with m.If(self.o.valid & self.o.ready):
            # Tx output
            m.d.sync += self.o.valid.eq(0)
            with m.If(self.allow):
                with m.If(self.o.last):
                    m.d.sync += self.allow.eq(0)
                    m.d.sync += self.iready.eq(0)

        with m.If(self.i.valid & self.iready):
            # Rx input
            m.d.sync += self.iready.eq(0)
            with m.If(start | self.allow):
                m.d.sync += Stream.connect(self.i, self.o, exclude=["ready"], silent=True)

        m.d.sync += self.iready.eq(0)

        with m.If(start):
            m.d.sync += self.allow.eq(1)
            m.d.sync += self.iready.eq(1)

        with m.If(self.allow):
            m.d.sync += Stream.connect(self.i, self.o, exclude=["ready"], silent=True)
            with m.If(self.o.ready & ~self.iready):
                m.d.sync += self.iready.eq(1)

        return m

#
#   n-bit Arbiter : Round-Robin arbiter with n inputs

class ArbState(IntEnum):

    IDLE, START, COPY, STOP = range(4)

class Arbiter(Elaboratable):

    def __init__(self, layout, n=None, name=None):
        self.i = []
        for i in range(n):
            s = Stream(layout=layout, name=add_name(name, f"i[{i}]"))
            self.i.append(s)
            setattr(self, f"_i{i}", s)

        self.o = Stream(layout=layout, name=add_name(name, "out"))

        self.idx = Signal(range(len(self.i)))
        self.state = Signal(ArbState)

        self.valids = Signal(len(self.i))
        self.readies = Signal(len(self.i))
        self.arb_idx = Signal(len(self.i))

        # Generate a arbitration table
        def num_bits(x):
            # http://graphics.stanford.edu/~seander/bithacks.html#CountBitsSetKernighan
            bits = 0
            while x:
                bits += 1
                x &= x-1
            return bits

        def nth(mask, idx):
            # get the index of each set bit
            m = mask
            bits = []
            while m:
                lowest = m & -m
                bits.append(lowest)
                m &= 1 << lowest
            return bits[idx % len(bits)]

        def to_idx(mask):
            assert mask
            for i in range(len(self.i)):
                if mask == (1 << i):
                    return i
            assert 0, ("mask not found", mask)

        arbs = []
        for i in range(1 << len(self.i)):
            for v in range(1 << len(self.i)):
                # all possible 'valids' combinations
                bits = num_bits(v)
                if bits == 0:
                    arb = 0
                elif bits == 1:
                    arb = to_idx(v)
                else:
                    # need to arbitrate
                    arb = to_idx(nth(v, i))
                arbs.append(Const(arb))

        self.arb = Array(arbs)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.o.valid & self.o.ready):
            # Tx output
            m.d.sync += self.o.valid.eq(0)

        for s in self.i:
            with m.If(s.valid & s.ready):
                m.d.sync += s.ready.eq(0)

        m.d.comb += self.valids.eq(Cat(* [ (s.valid & s.first) for s in self.i ] ))
        m.d.comb += self.readies.eq(Cat(* [ s.ready for s in self.i ] ))

        idx = Cat(self.valids, self.arb_idx)

        with m.If(self.state == ArbState.IDLE):
            # waiting for an input packet

            with m.If(self.o.ready):
                with m.If(self.valids):

                    def start(s, idx):
                        return [ 
                            s.ready.eq(1),
                            self.state.eq(ArbState.START),
                            self.idx.eq(idx),
                        ]

                    for i, s in enumerate(self.i):
                        with m.If(i == self.arb[idx]):
                            m.d.sync += start(s, i)
                            m.d.sync += self.arb_idx.eq(self.arb_idx+1)

        def copy(s):
            with m.If(s.ready & s.valid):
                m.d.sync += Stream.connect(s, self.o, exclude=["ready","valid"], silent=True)
                m.d.sync += s.ready.eq(0)
                m.d.sync += self.o.valid.eq(1)
                m.d.sync += self.state.eq(ArbState.COPY)

                with m.If(s.last):
                    m.d.sync += self.state.eq(ArbState.STOP)

            with m.If(self.o.ready & ~s.ready):
                m.d.sync += s.ready.eq(1)

        with m.If(self.state == ArbState.START):
            for i, s in enumerate(self.i):
                with m.If(i == self.idx):
                    with m.If(~s.valid):
                        # input has disapeared! Start again
                        # But we've already read data from one of the inputs!
                        # What to do!
                        m.d.sync += s.ready.eq(0)
                        m.d.sync += self.state.eq(ArbState.IDLE)
                    with m.Else():
                        copy(s)
                with m.Else():
                    m.d.sync += s.ready.eq(0)

        with m.If(self.state == ArbState.COPY):
            for i, s in enumerate(self.i):
                with m.If(i == self.idx):
                    copy(s)

        with m.If(self.state == ArbState.STOP):
            for i, s in enumerate(self.i):
                m.d.sync += s.ready.eq(0)
            m.d.sync += self.state.eq(ArbState.IDLE)

        return m

#   FIN
