
#   Driver for the 12-bit 1M s/s ADC found on the ulx3s
#

from amaranth import *

from streams import Stream
from streams.sim import SinkSim, SourceSim 
from streams.spi import SpiController

#
#

class MAX11125(Elaboratable):

    ADC_CONFIG  = 0x10 << 11
    UNIPOLAR    = 0x11 << 11
    BIPOLAR     = 0x12 << 11
    RANGE       = 0x13 << 11
    SCAN_0      = 0x14 << 11
    SCAN_1      = 0x15 << 11
    SAMPLE      = 0x16 << 11

    def __init__(self, init=[], divider=1):
        self.spi = SpiController(width=16, init=init, cpol=1, cpha=1)
        self.phy = self.spi.phy
        layout_o = [ ("data", 12 ), ("chan", 4), ]
        layout_i = [ ("chan", 4 ), ]
        self.i = Stream(layout=layout_i, name="MAX11125.i")
        self.o = Stream(layout=layout_o, name="MAX11125.o")

        self.divider = divider
        self.clock = Signal(range(divider))

    def elaborate(self, platform):
        m = Module()

        m.submodules += self.spi

        m.d.sync += [
            self.clock.eq(self.clock + 1),
            self.spi.enable.eq(0),
        ]

        with m.If(self.clock == (self.divider-1)):
            m.d.sync += [
                self.clock.eq(0),
                self.spi.enable.eq(1),
            ]

        m.d.comb += Stream.connect(self.i, self.spi.i, exclude=["chan"])
        m.d.comb += Stream.connect(self.spi.o, self.o, exclude=["chan", "data"])

        # Send convert requests for chan
        data = 0x0806 + (self.i.chan << 7)
        m.d.comb += self.spi.i.data.eq(data)

        # split rx data into chan/data
        m.d.comb += self.o.data.eq(self.spi.o.data)
        m.d.comb += self.o.chan.eq(self.spi.o.data >> 12)

        return m

    def ports(self): return []

#   FIN
