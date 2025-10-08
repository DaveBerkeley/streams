
from amaranth import *

from streams import Stream, Sink

#
#

def get_field(field, layout):
    for name, size in layout:
        if name == field:
            return size
    assert 0, (field, "not in", layout)

#
#

class Head(Elaboratable):

    """
    Takes an input Stream, strips the first n elements of a packet,
    outputs the remainer. The stripped elements are saved in an Array named
    'head'. It can be used to pass config parameters to a Module via
    a control Stream.
    """

    def __init__(self, layout, data_field, n=1, sink=False, name=None):
        self.name = name or f"Head[{n}]"
        self.field = data_field
        size = get_field(data_field, layout)

        self.i = Stream(layout, name="i")
        self.o = Stream(layout, name="o")

        if type(sink) is list:
            sink.append(self.o)
        elif sink:
            self.sink = Sink(layout, name="sink")

        # set hi when head[x] all loaded
        self.valid = Signal()
        # set hi when Head has more data to output to .o
        self.more = Signal()

        self.head = Array([ Signal(size) for i in range(n) ])
        self.field = getattr(self.i, self.field)

        self.end = Const(n-1)
        self.idx = Signal(range(n+1))
        self.copied = Signal()
        self.first = Signal()

    def elaborate(self, platform):
        m = Module()
        if hasattr(self, "sink"):
            m.submodules += self.sink
            m.d.comb += Stream.connect(self.o, self.sink.i)

        m.d.comb += self.more.eq(self.copied)

        # Tx output
        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        # Ready for more input
        with m.If((~self.i.ready) & ~self.o.valid):
            m.d.sync += self.i.ready.eq(1)
            m.d.sync += self.valid.eq(0)

        def tx(first):
            m.d.sync += [
                self.o.valid.eq(1),
                self.o.first.eq(first),
                self.o.last.eq(self.i.last),
            ]   + self.o.payload_eq(self.i.cat_payload())
            with m.If(self.i.last):
                m.d.sync += self.idx.eq(0)

        with m.If(self.o.valid & self.o.last):
            m.d.sync += self.copied.eq(0)

        # Process input
        with m.If(self.i.ready & self.i.valid):
            m.d.sync += [
                self.i.ready.eq(0),
            ]

            with m.If(self.valid & self.i.first):
                m.d.sync += self.valid.eq(0)

            with m.If(~self.copied):
                m.d.sync += [
                    self.idx.eq(self.idx + 1),
                    self.head[self.idx].eq(self.field),
                ]

                with m.If(self.i.first):
                    m.d.sync += [
                        self.idx.eq(1),
                        self.head[0].eq(self.field),
                    ]

                with m.If(self.i.last):
                    m.d.sync += self.idx.eq(0)
                    m.d.sync += self.valid.eq(1)

                with m.If(self.idx == self.end):
                    with m.If(~self.i.last):
                        m.d.sync += [
                            self.copied.eq(1),
                            self.first.eq(1),
                            self.valid.eq(1)
                        ]

            with m.Else():
                tx(self.first)
                m.d.sync += self.first.eq(0)

        return m

#
#   Route packets, taking the first word as an address

class Router(Elaboratable):

    """
    Route a Stream to one of n outputs. Takes the first elements in a packet,
    strips it from the packet, uses the data as an output address and 
    routes the remainer of the packet to that output. 
    Any unknown addresses are routed to the error output 'e'. This will
    typically require a Sink on it.
    """

    def __init__(self, layout, addr_field, addrs=[], name="Router", sink=None):
        self.name = name
        assert len(addrs)
        get_field(addr_field, layout) # assert
        self.field = addr_field
        self.addrs = addrs[:]
        self.mods = []

        self.i = Stream(layout=layout, name="i") # input
        self.e = Stream(layout=layout, name="e") # error stream
        self.null = Stream(layout=layout, name="null") # null stream
        self.route_mask = Signal(len(addrs))
        self.ready = Signal(1 + len(self.addrs)) # outputs + error
        self.error = Signal()

        self.head = Head(layout, data_field=addr_field)
        self.mods += [ self.head ]

        if sink is True:
            self.sink = Sink(layout=layout)
            self.mods += [ self.sink ]
        elif isinstance(sink, list):
            sink.append(self.e)

        self.o = {}

        for addr in addrs:
            s = Stream(layout=layout, name=f"o_{addr}")
            assert not addr in self.o
            self.o[addr] = s
            # .. so the dot code can find the Stream
            name = f"_o_{addr}"
            setattr(self, name, s)

    def elaborate(self, platform):
        m = Module()

        m.submodules += self.mods

        m.d.comb += Stream.connect(self.i, self.head.i)

        o = self.head.o

        def connect(s, enable):
            with m.If(enable):
                m.d.comb += Stream.connect(self.head.o, s, exclude=["ready"])
            with m.Else():
                m.d.comb += Stream.connect(self.null, s, exclude=["ready"])

        for idx, addr in enumerate(self.addrs):
            connect(self.o[addr], self.route_mask[idx] & self.head.more)

        connect(self.e, self.error & self.head.more)

        # the 'ready' signal back is the OR of each gated output+error

        for idx, addr in enumerate(self.addrs):
            s = self.o[addr]
            m.d.comb += self.ready[idx].eq(self.route_mask[idx] & s.ready)
        m.d.comb += self.ready[-1].eq(self.error & self.e.ready & self.head.more)

        m.d.comb += o.ready.eq(self.ready.any())

        if hasattr(self, "sink"):
            m.d.comb += Stream.connect(self.e, self.sink.i)

        with m.FSM():
            with m.State("IDLE"):
                m.d.sync += self.route_mask.eq(0)
                m.d.sync += self.error.eq(0)
                with m.If(self.head.more):
                    m.d.sync += self.error.eq(1)
                    for idx, addr in enumerate(self.addrs):
                        with m.If(addr == self.head.head[0]):
                            m.d.sync += self.route_mask.eq(1 << idx)
                            m.d.sync += self.error.eq(0)
                    m.next = "COPY"

            with m.State("COPY"):
                with m.If(o.valid & o.ready & o.last):
                    m.d.sync += self.route_mask.eq(0)
                    m.d.sync += self.error.eq(0)
                    m.next = "IDLE"

        return m

#
#

class StreamSync(Elaboratable):

    def __init__(self, layout):
        self.i = Stream(layout=layout, name="i")
        self.o = Stream(layout=layout, name="o")

    def elaborate(self, platform):
        m = Module()

        with m.FSM():

            with m.State("IDLE"):

                m.d.sync += self.o.valid.eq(0)
                with m.If(self.i.valid & self.o.ready):
                    m.d.sync += self.i.ready.eq(1)
                    m.next = "COPY"

            with m.State("COPY"):

                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += self.i.ready.eq(0)
                    m.d.sync += self.o.valid.eq(1)
                    m.d.sync += Stream.connect(self.i, self.o, exclude=[ "valid", "ready", ])

                with m.If(self.o.valid & self.o.ready):
                    m.d.sync += self.o.valid.eq(0)
                    with m.If(self.i.last):
                        m.next = "IDLE"
                    with m.Else():
                        with m.If(self.o.ready & ~self.i.ready):
                            m.d.sync += self.i.ready.eq(1)

        return m

#
#   Packetiser : add first/last flags to an input stream

class Packetiser(Elaboratable):

    def __init__(self, layout, max_psize):
        self.i = Stream(layout=layout, name="i")
        self.o = Stream(layout=layout, name="o")

        self.max_idx = Signal(range(max_psize+1))
        self.count = Signal(range(max_psize+1))

    def elaborate(self, platform):
        m = Module()

        with m.FSM():

            with m.State("IDLE"):

                m.d.sync += self.o.valid.eq(0)
                with m.If(self.i.valid & self.o.ready):
                    m.d.sync += self.i.ready.eq(1)
                    m.d.sync += self.count.eq(0)
                    m.next = "COPY"

            with m.State("COPY"):

                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += self.i.ready.eq(0)
                    m.d.sync += self.o.valid.eq(1)
                    m.d.sync += Stream.connect(self.i, self.o, exclude=[ "valid", "ready", "first", "last" ])
                    m.d.sync += self.o.first.eq(self.count == 0)
                    m.d.sync += self.o.last.eq(self.count == self.max_idx)
                    m.d.sync += self.count.eq(self.count + 1)

                with m.If(self.o.valid & self.o.ready):
                    m.d.sync += self.o.valid.eq(0)
                    with m.If(self.o.last):
                        m.next = "IDLE"
                    with m.Else():
                        with m.If(self.o.ready & ~self.i.ready):
                            m.d.sync += self.i.ready.eq(1)

        return m

#
#   Detects a word/last/first event from input tap,
#   This causes a message to be sent on the output.

class Event(Elaboratable):

    def __init__(self, events=[]):
        self.i = Stream(layout=[], name="i")
        assert events, "No events defined"
        for ev in events:
            assert ev in ["first", "last", "data" ], ("Bad event type", ev)
            name, ev_name = f"o_{ev}", f"ev_{ev}"
            s = Stream(layout=[], name=name)
            setattr(self, name, s)
            setattr(self, ev_name, Signal(name=ev_name))

    def connect(self, s):
        payload = [ name for name,_ in s.get_layout() ]
        exclude = payload + [ "ready" ]
        return [ 
            self.i.ready.eq(s.ready),
        ] + Stream.connect(s, self.i, exclude=exclude)

    def elaborate(self, platform):
        m = Module()

        ev = Signal()
        m.d.comb += ev.eq(self.i.ready & self.i.valid)

        events = []

        if hasattr(self, "ev_data"):
            m.d.comb += self.ev_data.eq(ev)
            events.append((self.ev_data, self.o_data))
        if hasattr(self, "ev_first"):
            m.d.comb += self.ev_first.eq(ev & self.i.first)
            events.append((self.ev_first, self.o_first))
        if hasattr(self, "ev_last"):
            m.d.comb += self.ev_last.eq(ev & self.i.last)
            events.append((self.ev_last, self.o_last))

        for ev, s in events:
            with m.If(s.valid & s.ready):
                m.d.sync += s.valid.eq(0)

            with m.If(ev):
                m.d.sync += s.valid.eq(1)

        return m

#
#

class Sequencer(Elaboratable):

    def __init__(self, width=32):
        
        self.base = Signal(width)
        self.count = Signal(width)
        self.incr = Signal(width)
        self.data = Signal(width)

        self.offset = Signal(width)

        self.enable = Signal()
        self.o = Stream(layout=[("data", width)], name="o")
        self.busy = Signal()

    def elaborate(self, platform):
        m = Module()

        def tx():
            m.d.sync += [
                self.o.valid.eq(1),
                self.o.data.eq(self.data),
                self.o.first.eq(self.offset == 0),
                self.o.last.eq((self.offset + 1) == self.count),

                self.data.eq(self.data + self.incr),
                self.offset.eq(self.offset + 1),
            ]

        with m.FSM(reset="IDLE"):

            with m.State("IDLE"):
                m.d.comb += self.busy.eq(0)
                with m.If(self.enable):
                    m.next = "RUN"
                    m.d.sync += self.data.eq(self.base)
                    m.d.sync += self.offset.eq(0)

            with m.State("RUN"):
                m.d.comb += self.busy.eq(1)
                with m.If(self.o.valid & self.o.ready):
                    m.d.sync += self.o.valid.eq(0)

                with m.If(~self.o.valid):
                    tx()

                with m.If(self.count == self.offset):
                    m.next = "STOP"

            with m.State("STOP"):
                m.d.comb += self.busy.eq(1)
                with m.If(~self.o.valid):
                    m.next = "IDLE"
                with m.If(self.o.valid & self.o.ready):
                    m.d.sync += self.o.valid.eq(0)
                    m.next = "IDLE"

        return m

#
#

#
#   Select input N, route to output
#   waits for last data in packet to xfer before switching inputs

class Select(Elaboratable):

    def __init__(self, layout, n, sink=False, wait_last=True):
        self.sink = sink
        self.wait_last = wait_last
        
        self.i = []
        for i in range(n):
            label = f"i{i}"
            s = Stream(layout=layout, name=label)
            setattr(self, label, s)
            self.i.append(s)

        self.o = Stream(layout=layout, name="o")

        self.select = Signal(range(n))
        self._select = Signal(range(n))

        self.copying = Signal(n)
        self.drop = Signal()

    def elaborate(self, _):
        m = Module()

        # Tx output
        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        change = Signal()
        m.d.comb += change.eq(self.select != self._select)

        m.d.sync += self.drop.eq(0)

        for i, s in enumerate(self.i):

            with m.If(self._select == i):
                with m.If((~self.o.valid) & ~s.ready):
                    m.d.sync += [
                        s.ready.eq(1),
                    ]
                # Read from the active input
                with m.If(s.valid & s.ready):
                    m.d.sync += [
                        s.ready.eq(0),
                        self.o.valid.eq(1),
                        self.copying[i].eq(self.wait_last & ~s.last),
                    ]   + self.o.payload_eq(s.cat_payload(flags=True), flags=True)
            with m.Else():
                m.d.sync += s.ready.eq(0)
                if self.sink:
                    # drop the input
                    m.d.sync += s.ready.eq(self.copying[i] | ~change)
                with m.If(s.valid & s.ready):
                    m.d.sync += self.copying[i].eq(self.wait_last & ~s.last)
                    m.d.sync += s.ready.eq(0)
                    m.d.sync += self.drop.eq(1)

            with m.If(change & (~self.copying.any() & ~(s.valid & s.ready))):
                m.d.sync += [
                    self._select.eq(self.select),
                    s.ready.eq(0),
                ]

        return m

#
#   Collator

class Collator(Elaboratable):

    """
    Takes n inputs, reads data from each in turn and assambles the items
    into a single packet that it sends from output 'o'
    """

    def __init__(self, n=None, layout=None, name="Collator"):
        self.name = name
        self.N = n
        self.end = Const(n-1)
        self.o = Stream(layout=layout, name="o")
        self.s = Stream(layout=layout, name="s")

        ins = []
        for i in range(n):
            label = f"i{i}"
            s = Stream(layout=layout, name=label)
            setattr(self, label, s)
            ins.append(s)

        self.i = Array(ins)
        self.idx = Signal(range(n+1))
        self.last = Signal()

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.last.eq(self.idx == self.end)

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        for i in range(self.N):
            m.d.comb += self.i[i].ready.eq(0)
            with m.If(self.idx == i):
                m.d.comb += Stream.connect(self.i[i], self.s)

        with m.If(~self.s.ready):
            with m.If(~self.o.valid):
                m.d.sync += self.s.ready.eq(1)

        with m.If(self.s.valid & self.s.ready):
            m.d.sync += [
                self.s.ready.eq(0),
                self.o.valid.eq(1),
                self.o.payload_eq(self.s.cat_payload()),
                self.o.first.eq(self.idx == 0),
                self.o.last.eq(self.last),
                self.idx.eq(self.idx + 1),
            ]
            with m.If(self.last):
                m.d.sync += self.idx.eq(0)

        return m

#
#   Read in a Packet, Send the nth item to output o[n]

class PacketSplit(Elaboratable):

    def __init__(self, layout, n=None, name="PacketSplit"):
        self.i = Stream(layout=layout, name="i")

        self.o = []
        for i in range(n):
            label = f"o{i}"
            s = Stream(layout=layout, name=label)
            setattr(self, label, s)
            self.o.append(s)

        bits = sum([ x[1] for x in layout ])

        head_layout = [("data", bits)]
        self.head = Head(layout=[("data", bits)], data_field="data", n=n, sink=True) 

    def elaborate(self, _):
        m = Module()
        m.submodules += self.head

        fields = [ x[0] for x in self.i.get_layout() ] + [ "ready" ]
        m.d.comb += Stream.connect(self.i, self.head.i, exclude=fields)
        m.d.comb += self.head.i.data.eq(self.i.cat_payload())

        # Tx all outputs
        for i, s in enumerate(self.o):
            with m.If(s.ready & s.valid):
                m.d.sync += s.valid.eq(0)

        valid = Cat([ s.valid for s in self.o ])

        m.d.comb += self.i.ready.eq(self.head.i.ready & (~valid.any()) & ~self.head.valid)

        with m.If(self.head.valid):
            for i, s in enumerate(self.o):
                m.d.sync += s.valid.eq(1)
                m.d.sync += s.payload_eq(self.head.head[i])

        return m

#
#

class MuxDown(Elaboratable):

    """
    Takes wide input data and outputs mutiple output data.
    Used to eg convert a 32-bit input into an 8-bit Stream.
    """

    def __init__(self, iwidth, owidth):
        self.i = Stream(layout=[("data", iwidth)], name="i")
        self.o = Stream(layout=[("data", owidth)], name="o")
        self.shift = owidth

        self.sr = Signal(iwidth)
        nibbles = (iwidth + (owidth - 1)) // owidth
        self.end = nibbles - 1
        self.nibble = Signal(range(nibbles + 1))
        self.first = Signal()
        self.last = Signal()
        self.wr = Signal()

    def elaborate(self, platform):
        m = Module()

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        with m.If(~(self.i.ready) & ~self.wr):
            m.d.sync += self.i.ready.eq(1)

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
                self.first.eq(self.i.first),
                self.last.eq(self.i.last),
                self.sr.eq(self.i.data),
                self.nibble.eq(0),
                self.wr.eq(1),
            ]

        with m.If(self.wr & ~self.o.valid):
            m.d.sync += [
                self.o.valid.eq(1),
                self.o.first.eq(self.first),
                self.o.last.eq(0),
                self.o.data.eq(self.sr),
                self.sr.eq(self.sr >> self.shift),
                self.nibble.eq(self.nibble + 1),
                self.first.eq(0),
            ]
            with m.If(self.nibble == self.end):
                m.d.sync += [
                    self.o.last.eq(self.last),
                    self.wr.eq(0),
                ]

        return m

#
#

class MuxUp(Elaboratable):

    """
    Takes a narrow input Stream and collates into a wide output Stream.
    """

    def __init__(self, iwidth, owidth):
        self.name = f"MuxUp({iwidth}->{owidth})"
        self.i = Stream(layout=[("data", iwidth)], name="i")
        self.o = Stream(layout=[("data", owidth)], name="o")
        self.last = Signal()
        self.first = Signal()

        nibbles = owidth // (iwidth + (iwidth - 1))
        print(nibbles)
        self.end = nibbles
        self.nibble = Signal(range(nibbles + 1))

        self.sr = Signal(owidth)

    def elaborate(self, platform):
        m = Module()

        with m.FSM(reset="READ"):

            with m.State("READ"):

                m.d.sync += self.i.ready.eq(1)

                with m.If(self.i.ready & self.i.valid):
                    # get the next nibble
                    m.d.sync += [
                        self.sr.eq(Cat(self.i.data, self.sr)),
                        self.i.ready.eq(0),
                        self.last.eq(self.i.last),
                    ]
                    with m.If(self.i.first):
                        m.d.sync += [
                            self.sr.eq(self.i.data),
                            self.nibble.eq(0),
                            self.first.eq(1),
                        ]
                    m.next = "ACC"

            with m.State("ACC"):
                m.d.sync += self.nibble.eq(self.nibble + 1)
                with m.If(self.last | (self.nibble == self.end)):
                    # send the sr contents
                    m.d.sync += [
                        self.o.data.eq(self.sr),
                        self.o.valid.eq(1),
                        self.o.first.eq(self.first),
                        self.o.last.eq(self.i.last),
                    ]
                    m.next = "WRITE"
                with m.Else():
                    m.next = "READ"

            with m.State("WRITE"):
                with m.If(self.o.valid & self.o.ready):
                    m.d.sync += [
                        self.o.valid.eq(0),
                        self.i.ready.eq(1),
                        self.nibble.eq(0),
                        self.first.eq(0),
                        self.sr.eq(0),
                    ]
                    m.next = "READ"

        return m

#   FIN
