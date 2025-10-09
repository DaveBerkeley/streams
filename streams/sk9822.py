#!/usr/bin/env python3

from amaranth import *
from amaranth.utils import bits_for

from streams import Stream

#
#   Implement the SK9822 control protocol
#
#   30MHz maximum clock rate
#
#   See notes: 
#
#   https://cpldcpu.wordpress.com/2016/12/13/sk9822-a-clone-of-the-apa102/
#

class Tx(Elaboratable):

    """
    Send a 32-bit word to the LED hardware
    """

    def __init__(self, divider):

        self.divider = divider
        self.counter = Signal(range(divider))
        self.en = Signal()
        self.phase = Signal()

        self.tx_data = Signal(32)
        self.shift = Signal(32)
        self.rdy = Signal(reset=1)
        self.ack = Signal()
        self.busy = Signal()

        self.bit = Signal(range(32))

        self.co = Signal()
        self.do = Signal()

    def elaborate(self, platform):

        m = Module()

        # Divide sys clock down for the output clock
        m.d.sync += self.counter.eq(self.counter + 1)

        with m.If(self.counter == self.divider):
            m.d.sync += self.counter.eq(0)

        # divide the clock out period into two phases
        m.d.sync += self.en.eq(self.counter == 0)
        m.d.sync += self.phase.eq(self.counter == (self.divider // 2))

        # Generate clock output
        with m.If(self.phase & ~self.rdy & self.busy):
            m.d.sync += self.co.eq(1)
        with m.If(self.en & ~self.rdy):
            m.d.sync += self.co.eq(0)

        # reset the Tx engine
        with m.If(self.ack & self.rdy):
            m.d.sync += [
                self.rdy.eq(0),
                self.bit.eq(0),
                self.shift.eq(self.tx_data),
            ]

        # Clock the data out
        with m.If(self.en & ~self.rdy):

            m.d.sync += [
                self.do.eq(self.shift[-1]),
                self.shift.eq(self.shift << 1),
                self.bit.eq(self.bit + 1),
                self.busy.eq(1),
            ]

        # End the clocking sequence
        with m.If(self.en & ~self.rdy & (self.bit == 0) & self.busy):

            m.d.sync += [
                self.rdy.eq(1),
                self.busy.eq(0),
            ]

        return m

#
#   Implement a Stream Device to control a set of sk9822 leds
#

class SK9822(Elaboratable):

    def __init__(self, sys_ck_freq, nleds, ck_freq=30e6):

        layout = [ ("addr", 8), ("r", 8), ("g", 8), ("b", 8), ]
        self.i = Stream(layout=layout, name="i")

        self.do = Signal()
        self.co = Signal()
        self.busy = Signal()

        divider = int(sys_ck_freq / ck_freq)
        assert divider > 1, (ck_freq, sys_ck_freq)
        assert int(sys_ck_freq / divider) <= 30e6

        self.tx = Tx(divider)

        self.idx = Signal(bits_for(nleds+3))

        self.leds = Array( [  Signal((8 * 3) + 5) for i in range(nleds) ] )
        self.changed = Signal(reset=1)

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
        m.submodules += self.tx

        m.d.comb += [
            self.co.eq(self.tx.co),
            self.do.eq(self.tx.do),
        ]

        self.brightness = Signal(5, reset=0x3)
        led = Cat(self.brightness, self.i.b, self.i.g, self.i.r)

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
                self.leds[self.i.addr].eq((self.brightness << 24) | (self.i.b << 16) | (self.i.g << 8) | self.i.r),
                self.changed.eq(1)
            ]

        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        m.d.sync += [
            self.tx.ack.eq(0),
            self.busy.eq(1),
        ]

        def send(data):
            with m.If(self.tx.rdy):
                m.d.sync += [
                    self.tx.tx_data.eq(data),
                    self.tx.ack.eq(1),
                ]

        with m.FSM():

            with m.State('Idle'):

                m.d.sync += self.busy.eq(self.changed)

                with m.If(self.changed):
                    m.d.sync += self.idx.eq(0)
                    # update the LED hardware
                    send(0x00000000) # Start SYNC
                    m.next = 'Tx-Start'

            with m.State('Tx-Start'):

                with m.If(self.tx.rdy & ~self.tx.ack):

                    for i in range(len(self.leds)):

                        # Clear the changed flag after the first sync word
                        with m.If(self.idx == 0):
                            m.d.sync += self.changed.eq(0)

                        with m.If(self.idx == i):
                            # Send each LED in turn
                            send(Cat(self.leds[i], Const(0x07)))
                            m.next = 'Txing'

                    with m.If(self.idx == len(self.leds)):
                        # We are done
                        m.next = 'Tx-End'

            with m.State('Txing'):

                with m.If(self.tx.rdy):
                    m.d.sync += self.idx.eq(self.idx + 1)
                    m.next = 'Tx-Start'

            with m.State('Tx-End'):

                with m.If(self.tx.rdy & ~self.tx.ack):
                    # Send the final SYNC word
                    send(0x00000000)
                    m.next = 'Ending'

            with m.State('Ending'):

                # Wait for the final word to finish
                with m.If(self.tx.rdy & ~self.tx.ack):
                    m.next = 'Idle'

        return m

# FIN
