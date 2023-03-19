
from amaranth.sim import *

from streams import to_packet
from streams.sim import SourceSim, SinkSim
from streams.dac import AD56x8
from streams.spi import SpiIo, SpiClock

#
#

def sim_dac(m, verbose):
    print("test dac")
    sim = Simulator(m)

    src = SourceSim(m.i, verbose=verbose)
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

def test(verbose):
    init = to_packet([ 0x12345678 ])
    dut = AD56x8(init=init, chip="AD5628")
    sim_dac(dut, verbose)

#   FIN
