

from enum import IntEnum
from amaranth import *

from streams import Stream

#
#

class LPF(Elaboratable):

    def __init__(self, width=16, points=8):
        self.POINTS = points
        self.i = Signal(width)
        self.en = Signal()
        self.o = Signal(width)

        self.sum = Signal(width + points)
        self.a = Signal(width + points)
        self.ready = Signal()

    def elaborate(self, platform):
        m = Module()

        with m.If(self.ready):
            m.d.sync += self.o.eq(self.sum >> self.POINTS)

            with m.If(self.en):
                m.d.sync += [
                    self.a.eq(self.i),
                    self.sum.eq(self.sum - (self.sum >> self.POINTS)),
                    self.ready.eq(0),
                ]

        with m.Else():
            m.d.sync += [
                self.sum.eq(self.sum + self.a),
                self.ready.eq(1),
            ]

        return m

#
#

class PREAMBLE(IntEnum):
    M, W, B, E = 0, 1, 2, 3

audio_layout = [ ("left", 20), ("right", 20), ("good", 1) ]
status_layout = [ ("data", 16) ]
bit_layout = [ ("data", 1) ]
aux_layout = [ ("data", 4) ]

_subframe_layout = [ 
    ("preamble", 2), 
    ("aux", 4), ("audio", 20), 
    ("V", 1), ("U", 1), ("C", 1),
]

subframe_layout = _subframe_layout + [ 
    ("P", 1), 
    ("check", 1), # parity check
]

#
#   Input periods of each gap between input transitions. 
#   Looks for pairs where (t_prev ~= 2 t_now) or (t_prev * 2 ~= t_now)
#   Output is matching t, where t is the bit duration.

class Discriminator(Elaboratable):

    def __init__(self, bits):
        self.i = Signal(bits)
        self.en = Signal()

        self.o = Signal(bits)
        self.valid = Signal()

        self.SHIFT = 3

        self.prev = Signal(bits)

        self.s = Signal(bits)
        self.s_hi = Signal(bits)
        self.s_lo = Signal(bits)

        self.half = Signal(bits)
        self.twice = Signal(bits)

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [
            self.half.eq(self.prev >> 1),
            self.twice.eq(self.prev << 1),
        ]

        m.d.sync += self.valid.eq(0)

        with m.FSM(reset="IDLE"):

            with m.State("IDLE"):

                with m.If(self.en):
                    m.d.sync += [
                        self.s.eq(self.i),
                    ]
                    m.next = "RANGE"

            with m.State("RANGE"):

                m.d.sync += [
                    self.s_hi.eq(self.s + (self.s >> self.SHIFT)),
                    self.s_lo.eq(self.s - (self.s >> self.SHIFT)),
                ]
                m.next = "CMP"

            with m.State("CMP"):

                with m.If((self.half >= self.s_lo) & (self.half <= self.s_hi)):
                    # t, 2*t
                    m.d.sync += [
                        self.o.eq(self.prev),
                        self.valid.eq(1),
                    ]
                with m.Elif((self.twice >= self.s_lo) & (self.twice <= self.s_hi)):
                    # 2*t, t
                    m.d.sync += [
                        self.o.eq(self.s),
                        self.valid.eq(1),
                    ]

                # If it isn't a { t, 2*t } or { 2*t, t } transition, we don't know t

                m.d.sync += self.prev.eq(self.s)
                m.next = "IDLE"

        return m

#
#
class _SubframeReader(Elaboratable):

    def __init__(self, counter_bits=10, data_bits=28):
        self.i = Signal()

        # detect transitions in the input signal
        self.edge = Signal(3)
        self.delta = Signal()

        # counter to measure period between delta
        self.delta_period = Signal(counter_bits)

        # filtered estimate of running bit period
        self.bit_period = Signal(counter_bits)

        # fractions of bit period used to detect 1/2, 1 and 3/2 bit period transitions
        self.ck_1_4 = Signal(counter_bits)
        self.ck_3_4 = Signal(counter_bits)
        self.ck_5_4 = Signal(counter_bits)
        self.ck_7_4 = Signal(counter_bits)
        # gap between delta transitions in 1/2 bits minus 1 : { 0,1,2 } 
        self.gap = Signal(2)

        # set during PREAMBLE detection : debug flag
        self.preamble = Signal()
        # last 3 gaps in preamble : used to detect B,M,W codes
        self.preamble_code = Signal(6)
        # preamble has 4 deltas, count the last 3
        self.preamble_section = Signal(range(3))

        self.lpf = LPF(counter_bits, 5)
        self.discriminator = Discriminator(counter_bits)

        # second half bit of a '1' data bit
        self.pair = Signal()
        # shift the decoded biphase mark data
        self.sr = Signal(data_bits)
        # count the data bits
        self.bit = Signal(range(data_bits+4))
        # maintain parity for validation of the signal
        self.parity = Signal()

        # test flag to show reading if each bit
        self.rd = Signal()

        self.mods = [
            self.lpf,
            self.discriminator,
        ]

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.mods

        m.d.sync += [
            # buffer the input to remove any slow edges
            self.edge.eq(Cat(self.i, self.edge)),
            # detect input transitions
            self.delta.eq(self.edge[-1] != self.edge[-2]),
        ]

        m.d.sync += [
            self.lpf.en.eq(0),
            self.delta_period.eq(self.delta_period + 1),
            self.discriminator.en.eq(0),
            self.rd.eq(0),
        ]

        with m.If(self.delta):

            m.d.sync += [
                # send periods between input transitions to discriminator
                self.discriminator.i.eq(self.delta_period),
                self.discriminator.en.eq(1),

                # (previous) output of discriminator is the bit period.
                # Low Pass Filter this.
                self.lpf.en.eq(1),
                self.lpf.i.eq(self.discriminator.o),

                # bit_period is the LP Filtered discriminated delta_period
                self.bit_period.eq(self.lpf.o),

                # restart the period count
                self.delta_period.eq(0),

                # define periods of 1/4 3/4 5/4 7/4 bit periods
                # these are used to detect a transition in 1/2, 1, 3/2 bit periods
                self.ck_1_4.eq(self.bit_period >> 2),
                self.ck_3_4.eq(self.bit_period - self.ck_1_4),
                self.ck_5_4.eq(self.bit_period + self.ck_1_4),
                self.ck_7_4.eq((self.bit_period << 1) - self.ck_1_4),
            ]

            # biphase mark decoder and preamble detection

            m.d.sync += self.gap.eq(3) # error condition : default
            # transition at ~1/2 bit period is between 1/4 and 3/4
            with m.If((self.delta_period > self.ck_1_4) & (self.delta_period <= self.ck_3_4)):
                m.d.sync += self.gap.eq(0)
            # transition at ~1 bit period is between 3/4 and 5/4
            with m.If((self.delta_period > self.ck_3_4) & (self.delta_period <= self.ck_5_4)):
                m.d.sync += self.gap.eq(1)
            # transition at 3/2 bits, is between 5/4 and 7/4
            with m.If((self.delta_period > self.ck_5_4) & (self.delta_period <= self.ck_7_4)):
                m.d.sync += self.gap.eq(2)

        def capture_bit(bit):
            m.d.sync += [
                self.sr.eq((self.sr << 1) + bit),
                self.parity.eq(self.parity ^ bit),
                self.bit.eq(self.bit + 1),
                self.pair.eq(0),
                self.rd.eq(1),
            ]

        with m.FSM(reset="DETECT"):

            with m.State("DETECT"):
                # waits for next delta
                with m.If(self.delta):
                    m.next = "CALC_RANGE"

            with m.State("CALC_RANGE"):
                with m.If(self.gap == 2):
                    # 3/2 bit period, must be in the preamble
                    m.d.sync += [
                        self.preamble_section.eq(0),
                        self.preamble_code.eq(0),
                        self.preamble.eq(1),
                        self.parity.eq(0),
                    ]
                    m.next = "PREAMBLE"
                with m.Else():
                    m.next = "DISCRIMINATE"

            with m.State("PREAMBLE"):
                with m.If(self.preamble_section == 3):
                    # end of preamble
                    m.d.sync += [
                        self.pair.eq(0),
                        self.bit.eq(0),
                        self.preamble.eq(0),
                        self.sr.eq(0),
                    ]
                    m.next = "DETECT"
                with m.If(self.delta):
                    # wait for next delta
                    m.next = "PREAMBLE_CHECK"

            with m.State("PREAMBLE_CHECK"):
                m.d.sync += [
                    self.preamble_section.eq(self.preamble_section + 1),
                    self.preamble_code.eq((self.preamble_code << 2) + self.gap),
                ]
                m.next = "PREAMBLE"

            with m.State("DISCRIMINATE"):

                with m.If(self.gap == 1):
                    capture_bit(0)
                with m.Elif(self.gap == 0):
                    with m.If(self.pair):
                        capture_bit(1)
                    with m.Else():
                        m.d.sync += self.pair.eq(1)

                m.next = "DETECT"

        return m

#
#

class SubframeReader(_SubframeReader):

    def __init__(self, counter_bits=10):
        _SubframeReader.__init__(self, counter_bits, data_bits=28)
        self.o = Stream(layout=subframe_layout, name="o")

    def elaborate(self, platform):
        m = _SubframeReader.elaborate(self, platform)

        # Send output 
        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        # All bits captured, write to output
        with m.If(self.bit == 28):
            m.d.sync += [
                self.bit.eq(0),
                self.o.valid.eq(1),

                self.o.P.eq(self.sr[0]),
                self.o.C.eq(self.sr[1]),
                self.o.U.eq(self.sr[2]),
                self.o.V.eq(self.sr[3]),
                self.o.audio.eq(self.sr[23:3:-1]),
                self.o.aux.eq(self.sr[:23:-1]),
                self.o.check.eq(self.parity ^ self.sr[0]),
            ]
            # gap between deltas is measured in 1/2 bits - 1 {0,1,2}
            # this is shifted in for each delta in the preamble
            # the initial 3/2 delta is common to all preambles, so is ignored.
            # The resulting codes in binary are :
            # B = 00 00 10 = 0x02
            # M = 10 00 00 = 0x20
            # W = 01 00 01 = 0x11
            with m.If(self.preamble_code == 0x11):
                m.d.sync += self.o.preamble.eq(PREAMBLE.W)
            with m.Elif(self.preamble_code == 0x20):
                m.d.sync += self.o.preamble.eq(PREAMBLE.M)
            with m.Elif(self.preamble_code == 0x02):
                m.d.sync += self.o.preamble.eq(PREAMBLE.B)
            with m.Else():
                # any other pattern is an error condition
                m.d.sync += self.o.preamble.eq(PREAMBLE.E)

        return m


#
#   Take a stream of 1-bit data (from the User and ChannelStatus fields)
#   and generate a 24 * 8-bit packet.

class BitsReader(Elaboratable):

    def __init__(self):
        self.i = Stream(layout=bit_layout, name="i")
        self.o = Stream(layout=status_layout, name="o")

        self.bit = Signal(range((16 * 12) + 1))
        self.sr = Signal(16)
        self.last = Signal()

    def elaborate(self, platform):
        m = Module()

        with m.If(self.o.valid & self.o.ready):
            m.d.sync += self.o.valid.eq(0)

        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        with m.If(self.i.valid & self.i.ready):

            m.d.sync += [
                self.i.ready.eq(0),
                self.bit.eq(self.bit + 1),
                self.sr.eq(Cat(self.i.data, self.sr)),
            ]

            with m.If(self.i.first):
                m.d.sync += [
                    self.bit.eq(1),
                ]

            with m.If(self.i.last | ((~self.i.first) & ((self.bit & 0x0f) == 0))):
                # 8-bits ready
                m.d.sync += [
                    self.o.valid.eq(1),
                    self.o.data.eq(self.sr),
                    self.o.first.eq(self.bit == 16),
                    self.o.last.eq(self.i.last),
                    self.last.eq(self.i.last),
                ]

        return m
               
#
#

class BlockReader(Elaboratable):

    def __init__(self):
        self.i = Stream(layout=subframe_layout, name="i")
        self.audio = Stream(layout=audio_layout, name="audio")
        self.status = Stream(layout=status_layout, name="status")
        self.user = Stream(layout=status_layout, name="user")
        self.aux = Stream(layout=status_layout, name="aux")

        self.status_reader = BitsReader()
        self.user_reader = BitsReader()

        self.FRAMES = 192
        self.frame = Signal(range(self.FRAMES + 1))
        self.sr_c = Signal(8)
        self.sr_u = Signal(8)

        self.chan_a = Signal(20)
        self.chan_b = Signal(20)
        self.chan_a_ok = Signal()
        self.chan_b_ok = Signal()
        self.tx = Signal()

        self.mods = [
            self.status_reader,
            self.user_reader,
        ]

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.mods

        m.d.comb += Stream.connect(self.status_reader.o, self.status)
        m.d.comb += Stream.connect(self.user_reader.o, self.user)

        # Tx audio output
        with m.If(self.audio.valid & self.audio.ready):
            m.d.sync += self.audio.valid.eq(0)

        # Tx aux output
        with m.If(self.aux.valid & self.aux.ready):
            m.d.sync += self.aux.valid.eq(0)

        with m.If(~self.i.ready):
            m.d.sync += self.i.ready.eq(1)

        subframe1 = Signal()
        subframe2 = Signal()
        block = Signal()

        m.d.comb += [
            subframe1.eq((self.i.preamble == PREAMBLE.M) | (self.i.preamble == PREAMBLE.B)),
            subframe2.eq(self.i.preamble == PREAMBLE.W),
            block.eq(self.i.preamble == PREAMBLE.B),
        ]

        # read subframe stream
        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                self.i.ready.eq(0),
            ]

            m.d.sync += [
                # Send Aux data every frame
                self.aux.valid.eq(1),
                self.aux.data.eq(self.i.aux),
                self.aux.first.eq(block),
                self.aux.last.eq((self.frame == (self.FRAMES - 1)) & subframe2),
            ]

            with m.If(subframe1):
                # start of frame
                m.d.sync += [
                    self.chan_a.eq(self.i.audio),
                    self.chan_a_ok.eq((self.i.P == self.i.check) & ~self.i.V),
                    self.sr_c.eq(Cat(self.i.C, self.sr_c)),
                    self.sr_u.eq(Cat(self.i.U, self.sr_c)),
                    self.frame.eq(self.frame + 1),
                ]

            with m.If(block):
                # start of block
                m.d.sync += [
                    self.frame.eq(0),
                    self.sr_c.eq(self.i.C),
                ]

            with m.If(subframe2):
                # second subframe
                m.d.sync += [
                    self.chan_b.eq(self.i.audio),
                    self.chan_b_ok.eq((self.i.P == self.i.check) & ~self.i.V),
                    self.sr_c.eq(Cat(self.i.C, self.sr_c)),
                    self.sr_u.eq(Cat(self.i.U, self.sr_u)),
                    self.tx.eq(1),
                ]
            # ignore any PREAMBLE.E (error) subframes

        with m.If(self.tx):
            # send audio frame
            m.d.sync += [
                self.tx.eq(0),
                self.audio.left.eq(self.chan_a),
                self.audio.right.eq(self.chan_b),
                self.audio.good.eq(self.chan_a_ok & self.chan_b_ok),
                self.audio.valid.eq(1),
                self.audio.first.eq(self.frame == 0),
                self.audio.last.eq(self.frame == (self.FRAMES - 1)),
            ]
            # TODO : pass user / status bits to submodules

        return m

#
#

class SPDIF_Rx(Elaboratable):

    def __init__(self, width=16):
        self.i = Signal()
        self.audio = Stream(layout=audio_layout, name="audio")
        self.status = Stream(layout=status_layout, name="status")
        self.user = Stream(layout=status_layout, name="user")
        self.aux = Stream(layout=aux_layout, name="aux")

        self.subframe_reader = SubframeReader()
        self.block_reader = BlockReader()

        self.mods = [
            self.subframe_reader,
            self.block_reader,
        ]

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.mods

        m.d.comb += self.subframe_reader.i.eq(self.i)
        m.d.comb += Stream.connect(self.subframe_reader.o, self.block_reader.i)
        m.d.comb += Stream.connect(self.block_reader.audio, self.audio)
        m.d.comb += Stream.connect(self.block_reader.status, self.status)
        m.d.comb += Stream.connect(self.block_reader.user, self.user)
        m.d.comb += Stream.connect(self.block_reader.aux, self.aux)

        return m

#
#

class SubframeWriter(Elaboratable):

    def __init__(self):
        self.i = Stream(layout=_subframe_layout, name="i")
        self.en = Signal() # 2 * bit rate
        self.o = Signal() # S/PDIF output

        self.preamble_code = Signal(1 + (4 * 2))
        self.sr = Signal(28)
        self.hbit = Signal(range(28 * 2))
        self.parity = Signal()

    def elaborate(self, platform):
        m = Module()

        with m.FSM(reset="WAIT"):

            with m.State("WAIT"):

                with m.If(~self.i.ready):
                    m.d.sync += self.i.ready.eq(1)

                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += [
                        self.i.ready.eq(0),
                        self.sr.eq(Cat(
                            self.i.aux,
                            self.i.audio,
                            self.i.V, 
                            self.i.U, 
                            self.i.C, 
                            0 # generate parity
                        )),
                    ]

                    # (0x01 << 8) is a termination marker
                    # 0x2 == 3 half-bits, 0x01 == 2 half-bits, 0x0 == 1 half-bit transition period
                    with m.If(self.i.preamble == PREAMBLE.B):
                        m.d.sync += self.preamble_code.eq((0x2 << 0) + (0x0 << 2) + (0x0 << 4) + (0x2 << 6) + (0x1 << 8))
                    with m.If(self.i.preamble == PREAMBLE.M):
                        m.d.sync += self.preamble_code.eq((0x2 << 0) + (0x2 << 2) + (0x0 << 4) + (0x0 << 6) + (0x1 << 8))
                    with m.If(self.i.preamble == PREAMBLE.W):
                        m.d.sync += self.preamble_code.eq((0x2 << 0) + (0x1 << 2) + (0x0 << 4) + (0x1 << 6) + (0x1 << 8))
                    m.next = "START"

            with m.State("START"):

                with m.If(self.en):
                    m.d.sync += self.o.eq(~self.o)
                    m.next = "PREAMBLE"

            with m.State("PREAMBLE"):

                with m.If(self.en):
                    # termination marker
                    with m.If(self.preamble_code == 0x4):
                        m.d.sync += [
                            self.o.eq(~self.o),
                            self.hbit.eq(1),
                            self.parity.eq(0),
                        ]
                        m.next = "SHIFT"

                    # end of this 1/2, 1, 3/2 half-bit seq
                    with m.If((self.preamble_code & 0x03) == 0):
                        m.d.sync += [
                            self.o.eq(~self.o),
                            self.preamble_code.eq(self.preamble_code >> 2),
                        ]
                        
                    with m.Else():
                        m.d.sync += self.preamble_code.eq(self.preamble_code - 1)

            with m.State("SHIFT"):

                with m.If(self.en):
                    m.d.sync += self.hbit.eq(self.hbit + 1)
                    with m.If(self.hbit & 0x01):
                        with m.If(self.sr[0]):
                            m.d.sync += [
                                self.o.eq(~self.o),
                                self.parity.eq(~self.parity),
                            ]
                    with m.Else():
                        m.d.sync += [
                            self.o.eq(~self.o),
                            self.sr.eq(self.sr >> 1),
                        ]

                    with m.If(self.hbit == ((27 * 2))):
                        # generate parity for the P bit
                        m.d.sync += self.sr.eq(self.parity)

                    with m.If(self.hbit == ((28 * 2) - 1)):
                        # end of the subframe
                        m.d.sync += self.i.ready.eq(1)
                        m.next = "WAIT"

        return m

#
#

class SPDIF_Tx(Elaboratable):

    def __init__(self, iwidth=16, bits=20, block_size=192):
        self.iwidth = iwidth
        self.bits = bits

        # purely for test purposes, allow different block sizes
        self.block_size = block_size
        if block_size != 192:
            print("non-standard SPDIF block size:", block_size)

        self.i = Stream(layout=[ ("left", iwidth), ("right", iwidth), ], name="i")
        self.en = Signal() # 1/2 bit clock for SPDIF output
        self.o = Signal() # SPDIF output

        # TODO : Handle all the other signals ...
        #self.status = Stream(layout=status_layout, name="status")
        #self.user = Stream(layout=status_layout, name="user")
        #self.aux_i = Stream(layout=aux_layout, name="aux")

        self.wr = SubframeWriter()
        self.frame = Signal(range(self.block_size))

        self.preamble = Signal(PREAMBLE)
        self.aux = Signal(4)
        self.left = Signal(bits)
        self.right = Signal(bits)

        self.mods = [
            self.wr,
        ]

    def elaborate(self, platform):
        m = Module()
        m.submodules += self.mods

        m.d.comb += self.o.eq(self.wr.o)
        m.d.comb += self.wr.en.eq(self.en)

        # send data to the subframe writer
        with m.If(self.wr.i.ready & self.wr.i.valid):
            m.d.sync += self.wr.i.valid.eq(0)

        # read data from the input
        with m.If(self.i.ready & self.i.valid):
            m.d.sync += self.i.ready.eq(0)

        def tx(audio, v, u, c):
            m.d.sync += [
                self.wr.i.valid.eq(1),
                self.wr.i.preamble.eq(self.preamble),
                self.wr.i.aux.eq(self.aux),
                self.wr.i.audio.eq(audio),
                self.wr.i.V.eq(v),
                self.wr.i.U.eq(u),
                self.wr.i.C.eq(c),
            ]

        shift = self.bits - self.iwidth
        assert shift >= 0, shift
        # TODO : handle >20 bits case, using AUX

        with m.FSM(reset="WAIT"):

            with m.State("WAIT"):

                with m.If(~self.i.ready):
                    m.d.sync += self.i.ready.eq(1)

                with m.If(self.i.ready & self.i.valid):
                    m.d.sync += [
                        self.left.eq(self.i.left << shift),
                        self.right.eq(self.i.right << shift),
                        self.aux.eq(0), # TODO
                    ]
                    with m.If(self.frame == 0):
                        m.d.sync += self.preamble.eq(PREAMBLE.B)
                    with m.Else():
                        m.d.sync += self.preamble.eq(PREAMBLE.M)
                    m.next = "SF1"

            with m.State("SF1"):
                with m.If(~self.wr.i.valid):
                    tx(self.left, 0, 0, 0)
                    m.d.sync += [
                        self.preamble.eq(PREAMBLE.W),
                        self.aux.eq(0), # TODO
                    ]
                    m.next = "SF2"

            with m.State("SF2"):
                with m.If(~self.wr.i.valid):
                    tx(self.right, 0, 0, 0)
                    m.d.sync += self.frame.eq(self.frame + 1)
                    with m.If(self.frame == (self.block_size-1)):
                        m.d.sync += self.frame.eq(0)
                    m.next = "WAIT"

        return m

#   FIN
