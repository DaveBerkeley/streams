
from amaranth import *

from streams.stream import Stream
from streams.ram import DualPortMemory

#
#

class WS2812(Elaboratable):

    def __init__(self, read_port, N):
        # bit period ~ 1.2us, enable clock 3 * this
        self.port = read_port # 24-bit wide memory
        self.phase_ck = Signal() # input clock at 3* bit period
        self.start = Signal() # begin tx

        self.o = Signal()
        self.idle = Signal()

        self.bit_max = 23
        self.n = N-1
        self.led = Signal(range(N))
        self.changed = Signal()
        self.addr = Signal(range(N*3))
        self.sr = Signal(24)
        self.bit = Signal(range(24*N))

        self.bit_ck = Signal()
        self.phase = Signal(3)

        # reset pulse >= 50us
        self.reset_max = 8 + int(52e-6 / 1.2e-6) # >= 50us
        self.reset_count = Signal(range(self.reset_max+1))

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.port.addr.eq(self.addr)

        m.d.sync += self.bit_ck.eq(0)

        with m.If(self.phase_ck):
            with m.If(self.phase < 2):
                m.d.sync += self.phase.eq(self.phase + 1)
            with m.Else():
                m.d.sync += self.phase.eq(0)
                m.d.sync += self.bit_ck.eq(1)

        with m.If(self.start):
            m.d.sync += self.changed.eq(1)

        with m.FSM(reset="IDLE"):

            with m.State("IDLE"):
                m.d.sync += self.o.eq(0)
                m.d.sync += self.idle.eq(1)
                with m.If(self.changed):
                    m.next = "RESET"
                    m.d.sync += self.reset_count.eq(0)
                    m.d.sync += self.idle.eq(0)

            with m.State("RESET"):
                m.d.sync += self.o.eq(0)
                with m.If(self.bit_ck):
                    m.d.sync += self.reset_count.eq(self.reset_count + 1)
                    with m.If(self.reset_count == self.reset_max):
                        m.next = "TX"
                        m.d.sync += [
                            self.addr.eq(0),
                            self.bit.eq(0),
                            self.sr.eq(0),
                            self.changed.eq(0),
                        ]

            with m.State("TX"):
                with m.If(self.phase_ck):
                    with m.If(self.phase == 0):
                        m.d.sync += [
                            self.o.eq(1),
                            self.sr.eq(self.sr << 1),
                            self.bit.eq(self.bit + 1),
                        ]
                        with m.If(self.bit == 0):
                            m.d.sync += [
                                self.sr.eq(self.port.data),
                                self.addr.eq(self.addr+1),
                            ]
                    with m.If(self.phase == 1):
                        m.d.sync += self.o.eq(self.sr[self.bit_max])
                    with m.If(self.phase == 2):
                        m.d.sync += self.o.eq(0)
                        with m.If(self.bit == (self.bit_max+1)):
                            m.d.sync += [
                                self.bit.eq(0),
                                self.led.eq(self.led + 1)
                            ]
                            with m.If(self.led == self.n):
                                m.next = "IDLE"

        return m

#
#

class LedStream(Elaboratable):

    def __init__(self, N, sys_ck=None, device="ws2812"):
        self.addr = Signal(range(N))
        width = self.addr.shape().width
        
        self.i = Stream(layout=[ ("addr", width), ("r", 8), ("g", 8), ("b", 8), ], name="in");

        self.phase_ck = Signal()
        self.sys_ck = sys_ck

        # ck div is 3* the bit period
        self.device = device
        if device == "ws2812":
            t = 425e-9 + 825e-9
            ck_div = 3 / t
        elif device == "yf923":
            t = 300e-9 + 600e-9
            ck_div = 3 / t
        else:
            assert 0, (device, "Unknown Device")

        if sys_ck:
            # drive phase_ck
            div = int(sys_ck / ck_div) + 1
            self.ck_max = div - 1
            self.clock_counter = Signal(range(div))

        self.o = Signal()
        self.idle = Signal()

        self.mem = DualPortMemory(24, N)
        self.mem.dot_dont_expand = True
        self.ws2812 = WS2812(self.mem.rd, N)
        self.mem.rd.dot_dont_expand = True

    def connect(self, src, dst=None):
        # connect a "data" field to the addr,r,g,b fields
        layout = src.get_layout()
        assert len(layout) == 1, layout
        assert layout[0][0] == "data", layout
        assert layout[0][1] >= 32, layout
        if dst is None:
            dst = self.i
        r = Stream.connect(src, dst, exclude=["data"])
        r += [
            dst.addr.eq(src.data >> 24),
            dst.r.eq(src.data >> 16),
            dst.g.eq(src.data >> 8),
            dst.b.eq(src.data >> 0),
        ]
        return r

    def elaborate(self, platform):
        m = Module()
        m.submodules += [
            self.mem,
            self.ws2812,
        ]

        m.d.comb += [
            self.idle.eq(self.ws2812.idle),
            self.o.eq(self.ws2812.o),
        ]

        if self.sys_ck:
            # generate the phase_ck
            m.d.sync += [
                self.clock_counter.eq(self.clock_counter + 1),
                self.ws2812.phase_ck.eq(0),
            ]
            with m.If(self.clock_counter == self.ck_max):
                m.d.sync += [
                    self.clock_counter.eq(0),
                    self.ws2812.phase_ck.eq(1)
                ]
        else:
            # requires external phase_ck input
            m.d.comb +=  self.ws2812.phase_ck.eq(self.phase_ck)

        m.d.sync += [
            self.mem.wr.en.eq(0),
            self.ws2812.start.eq(0),
        ]

        with m.If(self.i.valid & self.i.ready):
            # read input data
            m.d.sync += [
                self.mem.wr.addr.eq(self.i.addr),
                self.mem.wr.data.eq(Cat(self.i.b, self.i.r, self.i.g)),
                self.mem.wr.en.eq(1),
                self.ws2812.start.eq(1),
                self.i.ready.eq(0),
            ]
            if self.device == "yf923":
                m.d.sync += [
                    # R & G are swapped
                    self.mem.wr.data.eq(Cat(self.i.b, self.i.g, self.i.r)),
                ]

        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        return m

#
#

class LedStreamAdapter(Elaboratable):

    def __init__(self, N, sys_ck=None, device="ws2812"):
        self.i = Stream(layout=[("data", 32)], name="in")
        self.leds = LedStream(N, sys_ck, device=device)
        self.o = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.leds

        m.d.comb += self.o.eq(self.leds.o)

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.leds.i.addr.eq(self.i.data >> 24),
                self.leds.i.r.eq(self.i.data >> 16),
                self.leds.i.g.eq(self.i.data >> 8),
                self.leds.i.b.eq(self.i.data),
            ]

        m.d.comb += Stream.connect(self.i, self.leds.i, exclude=["data"])

        return m

#
#

if __name__ == "__main__":

    from amaranth.sim import Simulator

    dut = LedStreamAdapter(8)

    sim = Simulator(dut)

    # Generate DOT graph of the Amaranth Streams
    from streams import dot
    dot_path = "/tmp/ulx3s.dot"
    png_path = "ulx3s.png"
    dot.graph(dut, dot_path, png_path)

# FIN
