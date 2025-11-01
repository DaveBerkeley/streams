#!/bin/env python3

#   TODO : work in progress

from amaranth import *

from streams import Stream

#
#

class Phy:
    def __init__(self):
        self.ws = Signal()
        self.sck = Signal()
        self.sd = Signal()

#
#

class I2STxClock(Elaboratable):

    def __init__(self, width, owidth=None, name="I2STxClock"):
        self.name = name
        self.width = width
        self.owidth = owidth

        # Input clock (pulses at twice the bit rate)
        self.enable = Signal()

        # I2S output signals
        self.ws = Signal()
        self.sck = Signal()

        # Timing signals for Tx
        self.sample_tx = Signal()
        self.ck_left = Signal()
        self.ck_right = Signal()
        # Timing signals for Rx
        self.sample_rx = Signal()
        self.word = Signal()
        if owidth:
            # When used for Rx generation
            self.l_word = Signal()
            self.r_word = Signal()

    def elaborate(self, platform):
        m = Module()

        half = Signal()
        bit = Signal(range(self.width * 2))

        m.d.comb += [
            self.ws.eq(bit[-1]),
            self.sample_tx.eq(self.enable & half),
            self.ck_left.eq(self.sample_tx & (bit == 0)),
            self.ck_right.eq(self.sample_tx & (bit == self.width)),

            # When used as a Generator for I2SInput
            self.sample_rx.eq(self.enable & ~half),
            self.word.eq(self.sample_rx & (bit == 1)),
        ]
        if self.owidth:
            m.d.comb += [
                self.l_word.eq(self.sample_rx & (bit == (1+self.owidth))),
                self.r_word.eq(self.sample_rx & (bit == (1+self.width+self.owidth))),
            ]

        with m.If(self.enable):
            m.d.sync += half.eq(~half)

            with m.If(~half):
                m.d.sync += self.sck.eq(1)
            with m.Else():
                m.d.sync += [
                    bit.eq(bit + 1),
                    self.sck.eq(0),
                ]

        return m

#
#

class I2SOutput(Elaboratable):

    def __init__(self, width, tx_clock=None):
        self.width = width
        self.tx = tx_clock
        layout = [ ("left", width), ("right", width) ]
        self.i = Stream(layout=layout, name=f"i{width}")
        if not tx_clock:
            self.enable = Signal()

        self.phy = Phy()
        self.sro = Signal(width * 2)
        self.left  = Signal(width)
        self.right = Signal(width)

    def elaborate(self, platform):
        m = Module()

        if not self.tx: 
            self.tx = I2STxClock(self.width)
            m.submodules += self.tx
            m.d.comb += self.tx.enable.eq(self.enable),

        m.d.comb += [
            self.phy.ws.eq(self.tx.ws),
            self.phy.sck.eq(self.tx.sck),
        ]

        m.d.comb += self.phy.sd.eq(self.sro[self.width-1]),

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
                self.left.eq(self.i.left),
                self.right.eq(self.i.right),
            ]

        with m.If(self.tx.sample_tx):

            m.d.sync += self.sro.eq(Cat(0, self.sro)),

            with m.If(self.tx.ck_left):
                m.d.sync += self.sro.eq(self.left)

            with m.If(self.tx.ck_right):
                m.d.sync += self.sro.eq(self.right)
                m.d.sync += self.i.ready.eq(1)

        return m

#
#   Read WS/SCK data and generate timing signals

class I2SRxClock(Elaboratable):

    def __init__(self, width, owidth=None):
        self.width = width
        self.owidth = owidth

        # Inputs
        self.ws = Signal()
        self.sck = Signal()

        self.bit = Signal(width * 2)

        # outputs used by I2SRx units
        self.sample_rx = Signal()  # read the data in line
        self.word = Signal()    # word complete, shift_in data is valid

        if owidth:
            self.l_word = Signal()
            self.r_word = Signal()

        # output can be used to derive Tx clock signals
        self.ck2 = Signal()

    def elaborate(self, platform):
        m = Module()
        sck_0 = Signal()
        sck_1 = Signal()
        m.d.sync += sck_0.eq(self.sck)
        m.d.sync += sck_1.eq(sck_0)

        # Sample on the rising edge of SCK
        m.d.comb += self.sample_rx.eq(sck_0 & ~sck_1)
        m.d.comb += self.ck2.eq(sck_0 ^ sck_1)
        m.d.comb += self.word.eq(self.sample_rx & (self.bit == 0))

        if self.owidth:
            m.d.comb += self.l_word.eq(self.sample_rx & (self.bit == (self.width - self.owidth)))
            m.d.comb += self.r_word.eq(self.sample_rx & (self.bit == ((self.width * 2) - self.owidth)))

        ws_0 = Signal()
        with m.If(self.sample_rx):

            m.d.sync += self.bit.eq(self.bit + 1)
            m.d.sync += ws_0.eq(self.ws)

            with m.If(ws_0 & ~self.ws):
                # falling edge of WS
                m.d.sync += self.bit.eq(0)

        return m

#
#

class I2SInput(Elaboratable):

    def __init__(self, width, rx_clock=None):
        self.width = width
        self.phy = Phy()

        self.rx = rx_clock

        self.sri = Signal(width * 2)

        layout = [ ("left", width), ("right", width) ]
        self.o = Stream(layout=layout, name=f"o{width}")

    def elaborate(self, platform):
        m = Module()

        if not self.rx:
            self.rx = I2SRxClock(self.width)
            m.submodules += self.rx

            # connect the rx_clock to the input signals
            m.d.comb += [
                self.rx.ws.eq(self.phy.ws),
                self.rx.sck.eq(self.phy.sck),
            ]
        else:
            # connect the phy to the rx_clock signals
            m.d.comb += [
                self.phy.ws.eq(self.rx.ws),
                self.phy.sck.eq(self.rx.sck),
            ]

        with m.If(self.o.ready & self.o.valid):
            m.d.sync += self.o.valid.eq(0)

        with m.If(self.rx.sample_rx):

            m.d.sync += self.sri.eq(Cat(self.phy.sd, self.sri))

            with m.If(self.rx.word):
                m.d.sync += [
                    self.o.left.eq(self.sri >> self.width),
                    self.o.right.eq(self.sri),
                    self.o.valid.eq(1),
                ]

        return m

#
#

class I2SInputLR(Elaboratable):

    def __init__(self, rx_clock=None, width=None, name="I2SInputLR"):
        self.name = name
        self.rx_clock = rx_clock
        assert rx_clock, "Must have an Rx Clock"

        self.i = Signal()
        layout = [ ("data", width), ]
        self.left = Stream(layout=layout, name="left")
        self.right = Stream(layout=layout, name="right")

        self.sr = Signal(width)

    def elaborate(self, platform):
        m = Module()

        # Tx outputs
        for s in [ self.left, self.right ]:
            with m.If(s.valid & s.ready):
                m.d.sync += s.valid.eq(0)

        with m.If(self.rx_clock.sample_rx):
            m.d.sync += self.sr.eq(Cat(self.i, self.sr))

        with m.If(self.rx_clock.l_word):
            m.d.sync += [
                self.left.valid.eq(1),
                self.left.data.eq(self.sr),
            ]

        with m.If(self.rx_clock.r_word):
            m.d.sync += [
                self.right.valid.eq(1),
                self.right.data.eq(self.sr),
            ]

        return m

#   FIN
