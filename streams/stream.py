#!/bin/env python3

from amaranth import *
from amaranth.sim import *

from estream_sim import SinkSim, SourceSim

#
#

def print_dot(connections, path):
    nodes = {}
    groups = {}

    for source, sink, s in connections:
        nodes[source] = True
        nodes[sink] = True
        for s in [ source, sink ]:
            if s.group:
                if s.group in groups:
                    groups[s.group][s] = True
                else:
                    groups[s.group] = { s: True }

    s = nodes.keys()
    for i, node in enumerate(s):
        if not node.name:
            node.name = f"node_{i}"

    def node_repr(node):
        return id(node)
    def print_node(node):
        n = node_repr(node)
        print(f'\t\t{n} [shape=box,style=filled,label="{node.name}"]', file=f)

    f = open(path, "w")

    print("digraph D {", file=f)

    for node in nodes.keys():
        if not node.group in groups:
            print_node(node)

    for i, (group, parts) in enumerate(groups.items()):
        print(f"\tSubgraph cluster_x_{i}", "{", file=f)
        print(f"\t\tcolor=blue;", file=f)
        print(f"\t\tstyle=rounded;", file=f)
        name = group.__class__.__name__
        print(f'\t\tlabel = "{name}";', file=f)
        for node in parts.keys():
            print_node(node)
        print("\t}", file=f)

    def get_payload(s):
        names = [ name for name, _ in s.layout ]
        return ",".join(names)

    print("\t", file=f)
    for source, sink, s in connections:
        p_in = get_payload(source)
        p_out = get_payload(sink)
        if p_in == p_out:
            if p_in == "data":
                payload = ""
            else:
                payload = p_in
        else:
            payload = p_in + " -> " + p_out
        ni, no = node_repr(source), node_repr(sink)
        print(f'\t{ni} -> {no} [label="{payload}"]', file=f)

    print("}", file=f)

#
#

class Stream:

    connections = []

    def __init__(self, layout, name=None, group=None):
        self.layout = layout
        self.name = name
        self.group = group
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
#

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
        self.i = Stream(layout, name="StreamInit_i", group=self)
        self.o = Stream(layout, name="StreamInit_o", group=self)
        self.clr = Signal()

        # internal stream from Array
        self.data = Array( [ self.i.cat_dict(d, flags=True) for d in data ] )
        self.s = Stream(layout, name="StreamInit_s", group=self)

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
#

def get_field(name, data):
    return [ d[name] for _, d in data ]

def get_data(data):
    return [ d for _, d in data ]

#
#

def sim_init(m, init_data):
    print("test init")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=True)
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
            last = i == (len(data) - 1)
            src.push(t, data=d, first=first, last=last)

        yield from tick(50)
        yield m.clr.eq(1)
        yield from tick()
        yield m.clr.eq(0)
        yield from tick(20)

        def get_field(d, field='data'):
            return [ d[field] for d in data ]

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

def sim_null(m, n):
    print("test null")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=True)
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
            last = i == (len(data) - 1)
            src.push(t, data=d, first=first, last=last)

        yield from tick(50)
        assert tx_data[n:], get_field("data", sink.data[0])

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/stream_null.vcd", traces=m.ports()):
        sim.run()

#
#

def to_packet(data, field='data'):
    p = []
    for i, x in enumerate(data):
        d = { 'first': i==0, 'last': i == (len(data)-1), }
        d[field] = x
        p.append(d)
    return p

if __name__ == "__main__":
    layout = [ ( "data", 16 ), ]
    data = to_packet([ 0xabcd, 0xffff, 0xaaaa, 0x0000, 0x5555 ])
    dut = StreamInit(data, layout)
    sim_init(dut, data)

    dut = StreamNull(3, layout)
    sim_null(dut, 3)



#   FIN
