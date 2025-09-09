
from amaranth import *
from amaranth.lib.memory import Memory

from streams import Sink, Stream, Tee
from .dot import draw
from .uart import UART_Tx


#
#

class Tap(Elaboratable):

    def __init__(self, layout):
        self.i = Stream(layout=layout, name="i")
        self.o = Stream(layout=layout, name="o")

    def connects(self, s):
        return (s, self.i, {}, ["ready"])

    def elaborate(self, _):
        m = Module()

        m.d.comb += self.i.ready.eq(1) # But it shouldn't be connected

        # Tx
        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        # parasitically tap into the input stream
        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.o.valid.eq(1),
            ]   + self.o.payload_eq(self.i.cat_payload(flags=True), flags=True)    

        return m

#
#

class MonitorText(Elaboratable):

    def __init__(self, layout):
        self.mods = []

        self.i = Stream(layout=layout, name="i")

        labels, sizes = [ list(x) for x in zip(*layout) ]
        self.max_size = max(sizes)

        nibbles = (self.max_size + 3) // 4
        self.nibble = Signal(range(nibbles+1))
        self.sr = Signal(nibbles * 4)
        print(labels, sizes, self.max_size, nibbles)

        text = " ".join(labels) + " \0"
        text = bytes(text, encoding="UTF-8")
        self.mem = Memory(shape=signed(8), depth=len(text), init=text)
        self.mods += [ self.mem ]
        self.addr = Signal(range(len(text)))

        self.h = Stream(layout=layout, name="h")
        self.o = Stream(layout=[("data", 8),], name="o")

        # Hex lookup table
        def _hex(n):
            if n < 10: return n + ord(b'0')
            return n + ord(b'a') - 10
        self.hex = Array( [ _hex(x) for x in range(16) ] )

        def nibbles(n):
            return (n + 3) // 4

        self.idx = Signal(range(len(sizes)))
        self.sizes = sizes
        self.nibbles = Array([ nibbles(x) for x in sizes ])
        fields = []
        for name,_ in layout:
            f = getattr(self.i, name)
            fields.append(f)
        self.fields = Array(fields)

        shifts = []
        max_nibbles = nibbles(self.max_size)
        for size in sizes:
            n = nibbles(size)
            shifts.append(4 * (max_nibbles - n))
        self.shift = Array(shifts)

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.mods

        m.d.comb += draw(self.i, self.h)
        m.d.comb += draw(self.h, self.o)

        rd = self.mem.read_port()
        m.d.comb += rd.addr.eq(self.addr)

        end_field = Signal()
        end_msg = Signal()
        m.d.comb += end_field.eq(rd.data == ord(b' '))
        m.d.comb += end_msg.eq(rd.data == 0)

        # always ready for input (but we drop stuff)
        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        # Tx output
        with m.If(self.o.ready & self.o.valid):
            m.d.sync += self.o.valid.eq(0)

        def tx(c):
            m.d.sync += [
                self.o.valid.eq(1),
                self.o.data.eq(c),
            ]

        with m.FSM(reset="INIT"):

            with m.State("INIT"):
                m.d.sync += [
                    self.addr.eq(0),
                    self.h.ready.eq(1),
                    self.idx.eq(0),
                ]
                m.next = "WAIT"

            with m.State("WAIT"):
                with m.If(self.i.ready & self.i.valid & self.h.ready):
                    m.d.sync += [
                        self.i.ready.eq(0),
                        self.h.ready.eq(0),
                        self.h.valid.eq(1),
                        self.addr.eq(0),
                    ] + self.h.payload_eq(self.i.cat_payload())
                    m.next = "WRITE_LABEL"

            with m.State("WRITE_LABEL"):
                # transmit the next char
                with m.If(~self.o.valid):

                    with m.If(end_msg):
                        tx(ord(b"\r"))
                        m.next = "CR"
                    with m.Elif(end_field):
                        tx(rd.data)
                        m.d.sync += [
                            self.addr.eq(self.addr + 1),
                            # copy the next data field into the sr
                            self.sr.eq(self.fields[self.idx] << self.shift[self.idx]),
                            # set number of nibbles
                            self.nibble.eq(self.nibbles[self.idx]),
                            self.idx.eq(self.idx + 1),
                        ]
                        m.next = "WRITE_DATA"
                    with m.Else():
                        tx(rd.data)
                        m.d.sync += self.addr.eq(self.addr + 1)

            with m.State("WRITE_DATA"):
                with m.If(self.nibble == 0):
                    # get the next field
                    with m.If(end_msg):
                        m.next = "WRITE_LABEL"
                    with m.Else():
                        m.next = "SPACE"
                with m.Elif(~self.o.valid):
                    # transmit the next nibble
                    tx(self.hex[(self.sr >> (self.max_size - 4)) & 0x0f])
                    m.d.sync += self.sr.eq(self.sr << 4)
                    m.d.sync += self.nibble.eq(self.nibble - 1)

            with m.State("CR"):
                with m.If(~self.o.valid):
                    tx(ord(b"\n"))
                    m.next = "INIT"

            with m.State("SPACE"):
                with m.If(~self.o.valid):
                    tx(ord(b" "))
                    m.next = "WRITE_LABEL"

        return m

#
#

class UartMonitor(Elaboratable):

    def __init__(self, s, sys_ck_freq, baud=115200):
        self.mods = []
        self.connects = []
        # UART Stream Monitor
        mon_s = s
        mon_layout = mon_s.get_layout()

        self.i = Stream(layout=mon_layout, name="i")
        self.o = Signal()

        self.tap = Tap(mon_layout)
        self.mods += [ self.tap, ]
        self.connects += [ self.tap.connects(mon_s) ]

        self.mon_uart = MonitorText(layout=mon_layout)
        self.connects += [ ( self.tap.o, self.mon_uart.i ), ]
        self.mods += [ self.mon_uart, ]

        self.uart = UART_Tx()
        self.mods += [ self.uart, ]
        self.connects += [ ( self.mon_uart.o, self.uart.i ), ]

        # Generate baud rate for UART
        self.div = int(sys_ck_freq / baud)
        self.baud = Signal(range(self.div+1))

    def elaborate(self, _):
        m = Module()
        m.submodules += self.mods

        for x in self.connects:
            a, b, e, mm = x[0], x[1], [], {}
            if len(x) > 2:
                mm = x[2]
            if len(x) > 3:
                e = x[3]
            m.d.comb += Stream.connect(a, b, exclude=e, mapping=mm)

        m.d.comb += self.o.eq(self.uart.o)

        m.d.sync += self.baud.eq(self.baud + 1)
        m.d.sync += self.uart.en.eq(0)
        with m.If(self.baud == (self.div -1)):
            m.d.sync += self.baud.eq(0)
            m.d.sync += self.uart.en.eq(1)

        return m

#
#

class Monitor(Elaboratable):

    def __init__(self, layout, n):
        self.i = []
        for i in range(n):
            name = f"i{i}"
            s = Stream(layout=layout, name=name)
            setattr(self, name, s)
            self.i.append(s)
        self.o0 = Stream(layout=layout, name="o0")
        self.o1 = Stream(layout=layout, name="o1")
        self.ci = Stream(layout=[("data", 32),], name="ci")

        self.sel0 = Signal(range(n))
        self.sel1 = Signal(range(n))

    def tap(self, s, text, n, mapping={}):
        print("monitor", text)
        self.i[n].name = text
        fields = self.i[0].get_layout(flags=True) + [ ("valid", 1), ("ready", 1) ]
        connect = []
        for field,_ in fields:
            src = getattr(s, mapping.get(field, field))
            dst = getattr(self.i[n], field)
            connect.append( ( dst.eq(src) ) )
        connect += draw(s, self.i[n])
        return connect

    def elaborate(self, platform):
        m = Module()

        with m.If(~self.ci.ready):
            m.d.sync += [ self.ci.ready.eq(1), ]

        with m.If(self.ci.valid & self.ci.ready):
            m.d.sync += [
                self.ci.ready.eq(0),
                self.sel1.eq(self.ci.data),
                self.sel0.eq(self.sel1),
            ]

        fields = self.i[0].get_layout(flags=True) + [ ("valid", 1), ("ready", 1) ]
        for idx, s in enumerate(self.i):
            with m.If(self.sel0 == idx):
                for field,_ in fields:
                    src = getattr(s, field)
                    dst = getattr(self.o0, field)
                    m.d.sync += dst.eq(src)
            with m.If(self.sel1 == idx):
                for field,_ in fields:
                    src = getattr(s, field)
                    dst = getattr(self.o1, field)
                    m.d.sync += dst.eq(src)

        return m

#   FIN
