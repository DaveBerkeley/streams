#!/bin/env python3

from amaranth import *

from streams import Stream
from streams.spi import SpiController

#
#   AD56x8 SPI DAC
#
#   TODO : optionally use first/last flags to control LDAC pin?
#
#   http://www.analog.com/media/en/technical-documentation/data-sheets/ad5628_5648_5668.pdf

class AD56x8(Elaboratable):

    CMD_WRITE = 0
    CMD_UPDATE = 1
    CMD_WRITE_ALL = 2
    CMD_WRITE_UPDATE = 3
    CMD_POWER = 4
    CMD_CLEAR = 5
    CMD_LCAD = 6
    CMD_RESET = 7
    CMD_REF = 8

    def __init__(self, init=None, cmd=CMD_WRITE_UPDATE, chip=None):
        self.init = init
        self.cmd = cmd
        # AD56x8 samples data on the -ve edge of clock, so CPHA=1.
        # force each word transfer to assert/deassert SCS, so last_cs=1.
        self.spi = SpiController(32, init=init, cpha=1, last_cs=True)
        self.phy = self.spi.phy

        dev = {
            # data widths of each device type
            "AD5668" : 16,
            "AD5648" : 14,
            "AD5628" : 12,
        }
        if not chip in dev:
            raise Exception("chip must be one of %s" % repr(dev.keys()))

        width = dev[chip]
        layout = [ ("hi", 4), ("cmd", 4), ("addr", 4), ("data", width), ("lo", 20-width), ]
        self.i = Stream(layout, name="AD56x8_DAC")
        # optional synchronous DAC update (see datasheet)
        self.ldac = Signal()
        self.spi.phy.ldac = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules += self.spi

        m.d.comb += self.spi.phy.ldac.eq(self.ldac)

        # don't connect any of the payloads automatically, just the handshakes
        # as the input stream is ("data",x),("addr",4),("cmd",4), SPI input is ("data",32)
        # we need to Cat the input payloads into a single 32-bit "data" payload.
        exclude = [ name for name, _ in self.i.layout ]
        # We want every word Tx to assert/deassert SCS, so force first/last=1
        exclude += [ "first", "last" ]
        m.d.comb += Stream.connect(self.i, self.spi.i, exclude=exclude)
        m.d.comb += [
            self.spi.i.first.eq(1),
            self.spi.i.last.eq(1),
        ]

        # build 32-bit SPI data from data,addr,cmd inputs
        data = Cat(self.i.lo, self.i.data, self.i.addr, self.i.cmd, self.i.hi)
        m.d.comb += self.spi.i.data.eq(data)

        if self.cmd:
            # We can either hard-wire "cmd" to a single value
            # or provide "cmd" data on the input Stream
            m.d.comb += self.i.cmd.eq(Const(self.cmd))

        # Pad the unused bits
        m.d.comb += self.i.lo.eq(Const(0xff))
        m.d.comb += self.i.hi.eq(Const(0xf))

        return m

    def ports(self):
        return []
    
#   FIN
