#!/bin/env python3

from amaranth import *
from amaranth.sim import *

from streams import Stream, to_packet
from streams.sim import SourceSim, SinkSim
from streams.spi import SpiController, SpiIo, SpiClock

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
    
#
#

def sim_dac(m):
    print("test dac")
    sim = Simulator(m)

    src = SourceSim(m.i)
    io = SpiIo(32)

    period = 2
    ck = SpiClock(m.spi.enable, period)

    def tick(n=1):
        assert n
        for i in range(n):
            yield Tick()
            yield from src.poll()
            yield from ck.poll()
            scs = yield m.spi.phy.scs
            sck = yield m.spi.phy.sck
            do = yield m.spi.phy.copi
            io.poll(not scs, sck, do)

    def proc():

        data = [
            0x0,
            0x123,
            0x456,
            0x789,
            0xabc,
            0xdef,
            0xfff,
            0x111,
        ]
        for i, d in enumerate(data):
            src.push(0, data=d, addr=i, cmd=3, first=1, last=1)

        # wait for SCS to be high for a long period
        # indicating the input Stream has been consumed
        scs_hi = 0
        while True:
            yield from tick()
            scs = yield m.spi.phy.scs
            if not scs:
                scs_hi = 0
            else:
                scs_hi += 1
            if scs_hi > (period * 4):
                break

        result = [ x['data'] for x in m.init ]

        for i, d in enumerate(data):
            v = 0xf30000ff + (d << 8) + ((i % 8) << 20)
            result.append(v)

        assert io.rx == result , ([ hex(x) for x in io.rx] , [ hex(x) for x in result])

    sim.add_clock(1 / 100e6)
    sim.add_sync_process(proc)
    with sim.write_vcd("gtk/ulx3s_dac.vcd", traces=m.ports()):
        sim.run()

#
#

if __name__ == "__main__":

    init = to_packet([ 0x12345678 ])
    dut = AD56x8(init=init, chip="AD5628")
    sim_dac(dut)

#   FIN
