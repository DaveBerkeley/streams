
from amaranth import *

from streams import Stream

#
#   Simple 8-bit Tx Stream to UART

class UART_Tx(Elaboratable):

    def __init__(self):
        self.i = Stream(layout=[("data", 8)], name="i")
        self.o = Signal(reset=1)
        self.en = Signal() # baud rate enable signal

        self.bit = Signal(range(8+1))
        self.sr = Signal(8)

    def elaborate(self, platform):
        m = Module()

        with m.FSM(reset="IDLE"):

            with m.State("IDLE"):
                with m.If(~self.i.ready):
                    m.d.sync += self.i.ready.eq(1)

                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += [
                        self.i.ready.eq(0),
                        self.sr.eq(self.i.data),
                    ]
                    m.next = "START"

            with m.State("START"):
                with m.If(self.en):
                    m.d.sync += [
                        self.o.eq(0), # Start Bit
                        self.bit.eq(0),
                    ]
                    m.next = "TX"

            with m.State("TX"):
                with m.If(self.en):
                    m.d.sync += [
                        self.o.eq(self.sr), # Data bit
                        self.sr.eq(self.sr >> 1),
                        self.bit.eq(self.bit + 1),
                    ]
                    with m.If(self.bit == 7):
                        m.next = "STOP"

            with m.State("STOP"):
                with m.If(self.en):
                    m.d.sync += [
                        self.o.eq(1), # Stop Bit
                        self.i.ready.eq(1),
                    ]
                    m.next = "IDLE"

        return m

#   FIN
