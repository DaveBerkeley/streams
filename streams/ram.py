
from amaranth import *

from streams.stream import Stream

#
#

class Port(Elaboratable):
    def __init__(self, port, rd):
        self._port = port
        self._rd = rd
        self.addr = Signal(port.addr.shape())
        self.data = Signal(port.data.shape())
        self.en = Signal(reset=1)
    def connect(self, rd=True):
        cmds = [
            self._port.addr.eq(self.addr),
            self._port.en.eq(self.en),
        ]
        if rd:
            cmds += [ self.data.eq(self._port.data), ]
        else:
            cmds += [ self._port.data.eq(self.data), ]
        return cmds
    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.connect(rd=self._rd)
        return m

#
#

class DualPortMemory(Elaboratable):
    
    def __init__(self, width=16, depth=1024):

        self.ram = Memory(width=width, depth=depth)
        port = self.ram.read_port(transparent=False)
        self.rd = Port(port, rd=True)
        port = self.ram.write_port()
        self.wr = Port(port, rd=False)

    def elaborate(self, platform):
        m = Module()
        m.submodules += [ self.ram, self.rd, self.wr ]
        return m

    def __getitem__(self, idx):
        return self.ram._array[idx]

#
#

class StreamToRam(Elaboratable):

    def __init__(self, width=16, depth=1024, mem=None):

        self.subs = []

        if mem:
            self.mem = mem
        else:
            self.mem = DualPortMemory(width=width, depth=depth)
            self.subs.append(self.mem)

        layout = [ ( "data", width ), ]
        self.i = Stream(layout)
        self.offset = Signal(range(depth))
        self.incr = Signal() # add to addr on each read (0 or 1)

        self.addr = Signal(range(depth))
        self.port = self.mem.wr

    def elaborate(self, platform):
        m = Module()

        m.submodules += self.subs

        m.d.sync += self.port.en.eq(0)

        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.port.en.eq(1),
                self.port.data.eq(self.i.data),
                self.i.ready.eq(0),
            ]

            with m.If(self.i.first):
                m.d.sync += [
                    self.port.addr.eq(self.offset),
                    self.addr.eq(self.incr),
                ]
            with m.Else():
                m.d.sync += [
                    self.port.addr.eq(self.offset + self.addr),
                    self.addr.eq(self.addr + self.incr),
                ]

        return m

#
#

class RamToStream(Elaboratable):

    def __init__(self, width=16, depth=1024, mem=None):
        self.subs = []

        if mem:
            self.mem = mem
        else:
            self.mem = DualPortMemory(width=width, depth=depth)
            self.subs.append(self.mem)

        self.offset = Signal(range(depth))
        self.N = Signal(range(depth)) # packet size
        self.incr = Signal(range(depth), reset=1)

        layout = [ ( "data", width ), ]
        self.o = Stream(layout)

        self.idx = Signal(range(depth))
        self.count = Signal(range(depth))
        self.run = Signal()

        self.port = self.mem.rd

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.subs

        m.d.comb += [
            # is this slow?
            self.port.addr.eq(self.idx + self.offset),
        ]

        def tx():
            return [
                # Send data
                self.o.valid.eq(1),
                self.o.data.eq(self.port.data),
                self.o.first.eq(self.count == 0),
                self.o.last.eq(self.count == (self.N-1)),
                # Queue next data
                self.idx.eq(self.idx + self.incr),
                self.count.eq(self.count + 1),
            ]

        def reset():
            return [
                self.idx.eq(0),
                self.count.eq(0),
                self.run.eq(0),
            ]

        with m.If(self.o.ready & ~self.run):
            m.d.sync += self.run.eq(1)
            m.d.sync += tx()

        with m.If(self.run & ~self.o.valid):
            m.d.sync += tx()

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)
            # Packet finished
            with m.If(self.o.last):
                m.d.sync += reset()

        return m

#   FIN
