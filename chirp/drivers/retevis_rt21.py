# Copyright 2021 Jim Unroe <rock.unroe@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import time
import os
import struct
import logging

from chirp import (
    bitwise,
    chirp_common,
    directory,
    errors,
    memmap,
    util,
)
from chirp.settings import (
    RadioSetting,
    RadioSettingGroup,
    RadioSettings,
    RadioSettingValueBoolean,
    RadioSettingValueInteger,
    RadioSettingValueList,
    RadioSettingValueString,
)

LOG = logging.getLogger(__name__)

MEM_FORMAT = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];       // RX Frequency           0-3
  lbcd txfreq[4];       // TX Frequency           4-7
  ul16 rx_tone;         // PL/DPL Decode          8-9
  ul16 tx_tone;         // PL/DPL Encode          A-B
  u8 unknown1:3,        //                        C
     bcl:2,             // Busy Lock
     unknown2:3;
  u8 unknown3:2,        //                        D
     highpower:1,       // Power Level
     wide:1,            // Bandwidth
     unknown4:4;
  u8 unknown7:1,        //                        E
     scramble_type:3,   // Scramble Type
     unknown5:4;
  u8 unknown6:5,
     scramble_type2:3;  // Scramble Type 2        F
} memory[16];

#seekto 0x011D;
struct {
  u8 unused:4,
     pf1:4;             // Programmable Function Key 1
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;      // Scramble Enable
  u8 unknown1[2];
  u8 voice;             // Voice Annunciation
  u8 tot;               // Time-out Timer
  u8 totalert;          // Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;           // Squelch Level
  u8 save;              // Battery Saver
  u8 unknown3[3];
  u8 use_vox;           // VOX Enable
  u8 vox;               // VOX Gain
} settings;

#seekto 0x017E;
u8 skipflags[2];       // SCAN_ADD
"""

MEM_FORMAT_RB17A = """
struct memory {
  lbcd rxfreq[4];      // 0-3
  lbcd txfreq[4];      // 4-7
  ul16 rx_tone;        // 8-9
  ul16 tx_tone;        // A-B
  u8 unknown1:1,       // C
     compander:1,      // Compand
     bcl:2,            // Busy Channel Lock-out
     cdcss:1,          // Cdcss Mode
     scramble_type:3;  // Scramble Type
  u8 unknown2:4,       // D
     middlepower:1,    // Power Level-Middle
     unknown3:1,       //
     highpower:1,      // Power Level-High/Low
     wide:1;           // Bandwidth
  u8 unknown4;         // E
  u8 unknown5;         // F
};

#seekto 0x0010;
  struct memory lomems[16];

#seekto 0x0200;
  struct memory himems[14];

#seekto 0x011D;
struct {
  u8 pf1;              // 011D PF1 Key
  u8 topkey;           // 011E Top Key
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;     // 012C Scramble Enable
  u8 channel;          // 012D Channel Number
  u8 alarm;            // 012E Alarm Type
  u8 voice;            // 012F Voice Annunciation
  u8 tot;              // 0130 Time-out Timer
  u8 totalert;         // 0131 Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;          // 0134 Squelch Level
  u8 save;             // 0135 Battery Saver
  u8 unknown3[3];
  u8 use_vox;          // 0139 VOX Enable
  u8 vox;              // 013A VOX Gain
} settings;

#seekto 0x017E;
u8 skipflags[4];       // Scan Add
"""

MEM_FORMAT_RB26 = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 compander:1,      // Compander              C
     unknown1:1,       //
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     bcl:1,            // Busy Lock  OFF=0 ON=1
     unknown2:3;       //
  u8 reserved[3];      // Reserved               D-F
} memory[30];

#seekto 0x002D;
struct {
  u8 unknown_1:1,      //                        002D
     chnumberd:1,      // Channel Number Disable
     gain:1,           // MIC Gain
     savem:1,          // Battery Save Mode
     save:1,           // Battery Save
     beep:1,           // Beep
     voice:1,          // Voice Prompts
     unknown_2:1;      //
  u8 squelch;          // Squelch                002E
  u8 tot;              // Time-out Timer         002F
  u8 channel_4[13];    //                        0030-003C
  u8 unknown_3[3];     //                        003D-003F
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_4;        //                        004D
  u8 unknown_5[2];     //                        004E-004F
  u8 channel_6[13];    //                        0050-005C
  u8 unknown_6;        //                        005D
  u8 unknown_7[2];     //                        005E-005F
  u8 channel_7[13];    //                        0060-006C
  u8 warn;             // Warn Mode              006D
  u8 pf1;              // Key Set PF1            006E
  u8 pf2;              // Key Set PF2            006F
  u8 channel_8[13];    //                        0070-007C
  u8 unknown_8;        //                        007D
  u8 tail;             // QT/DQT Tail(inverted)  007E
} settings;

#seekto 0x01F0;
u8 skipflags[4];       // Scan Add

#seekto 0x029F;
struct {
  u8 chnumber;         // Channel Number         029F
} settings2;

#seekto 0x031D;
struct {
  u8 unused:7,         //                        031D
     vox:1;            // Vox
  u8 voxl;             // Vox Level              031E
  u8 voxd;             // Vox Delay              031F
} settings3;
"""

MEM_FORMAT_RT76 = """
#seekto 0x0000;
struct {
  lbcd rxfreq[4];      // RX Frequency           0-3
  lbcd txfreq[4];      // TX Frequency           4-7
  ul16 rx_tone;        // PL/DPL Decode          8-9
  ul16 tx_tone;        // PL/DPL Encode          A-B
  u8 compander:1,      // Compander              C
     unknown1:1,       //
     highpower:1,      // Power Level
     wide:1,           // Bandwidth
     unknown2:4;       //
  u8 reserved[3];      // Reserved               D-F
} memory[30];

#seekto 0x002D;
struct {
  u8 unknown_1:1,      //                        002D
     chnumberd:1,      // Channel Number Disable
     gain:1,           // MIC Gain                                 ---
     savem:1,          // Battery Save Mode                        ---
     save:1,           // Battery Save                             ---
     beep:1,           // Beep                                     ---
     voice:2;          // Voice Prompts                            ---
  u8 squelch;          // Squelch                002E              ---
  u8 tot;              // Time-out Timer         002F              ---
  u8 channel_4[13];    //                        0030-003C
  u8 unused:7,         //                        003D
     vox:1;            // Vox                                      ---
  u8 voxl;             // Vox Level              003E              ---
  u8 voxd;             // Vox Delay              003F              ---
  u8 channel_5[13];    //                        0040-004C
  u8 unknown_4;        //                        004D
  u8 unknown_5[2];     //                        004E-004F
  u8 channel_6[13];    //                        0050-005C
  u8 chnumber;         // Channel Number         005D              ---
  u8 unknown_7[2];     //                        005E-005F
  u8 channel_7[13];    //                        0060-006C
  u8 warn;             //                        006D              ---
} settings;
"""

MEM_FORMAT_RT29 = """
#seekto 0x0010;
struct {
  lbcd rxfreq[4];       // RX Frequency           0-3
  lbcd txfreq[4];       // TX Frequency           4-7
  ul16 rx_tone;         // PL/DPL Decode          8-9
  ul16 tx_tone;         // PL/DPL Encode          A-B
  u8 unknown1:2,        //                        C
     compander:1,       // Compander
     bcl:2,             // Busy Lock
     unknown2:3;
  u8 unknown3:1,        //                        D
     txpower:2,         // Power Level
     wide:1,            // Bandwidth
     unknown4:3,
     cdcss:1;           // Cdcss Mode
  u8 unknown5;          //                        E
  u8 unknown6:5,
     scramble_type:3;   // Scramble Type          F
} memory[16];

#seekto 0x011D;
struct {
  u8 unused1:4,
     pf1:4;             // Programmable Function Key 1
  u8 unused2:4,
     pf2:4;             // Programmable Function Key 2
} keys;

#seekto 0x012C;
struct {
  u8 use_scramble;      // Scramble Enable
  u8 unknown1[2];
  u8 voice;             // Voice Annunciation
  u8 tot;               // Time-out Timer
  u8 totalert;          // Time-out Timer Pre-alert
  u8 unknown2[2];
  u8 squelch;           // Squelch Level
  u8 save;              // Battery Saver
  u8 unknown3[3];
  u8 use_vox;           // VOX Enable
  u8 vox;               // VOX Gain
  u8 voxd;              // Vox Delay
} settings;

#seekto 0x017E;
u8 skipflags[2];       // SCAN_ADD

#seekto 0x01B8;
u8 fingerprint[5];     // Fingerprint
"""

CMD_ACK = "\x06"

ALARM_LIST = ["Local Alarm", "Remote Alarm"]
BCL_LIST = ["Off", "Carrier", "QT/DQT"]
CDCSS_LIST = ["Normal Code", "Special Code 2", "Special Code 1"]
CDCSS2_LIST = ["Normal Code", "Special Code"]  # RT29 UHF and RT29 VHF
GAIN_LIST = ["Standard", "Enhanced"]
PFKEY_LIST = ["None", "Monitor", "Lamp", "Warn", "VOX", "VOX Delay",
              "Key Lock", "Scan"]
SAVE_LIST = ["Standard", "Super"]
TIMEOUTTIMER_LIST = ["Off"] + ["%s seconds" % x for x in range(15, 615, 15)]
TOTALERT_LIST = ["Off"] + ["%s seconds" % x for x in range(1, 11)]
VOICE_LIST = ["Off", "Chinese", "English"]
VOICE_LIST2 = ["Off", "English"]
VOICE_LIST3 = VOICE_LIST2 + ["Chinese"]
VOX_LIST = ["OFF"] + ["%s" % x for x in range(1, 17)]
VOXD_LIST = ["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"]
VOXL_LIST = ["OFF"] + ["%s" % x for x in range(1, 9)]
WARN_LIST = ["OFF", "Native Warn", "Remote Warn"]
PF1_CHOICES = ["None", "Monitor", "Scan", "Scramble", "Alarm"]
PF1_VALUES = [0x0F, 0x04, 0x06, 0x08, 0x0C]
PF1_17A_CHOICES = ["None", "Monitor", "Scan", "Scramble"]
PF1_17A_VALUES = [0x0F, 0x04, 0x06, 0x08]
PFKEY_CHOICES = ["None", "Monitor", "Scan", "Scramble", "VOX", "Alarm"]
PFKEY_VALUES = [0x0F, 0x04, 0x06, 0x08, 0x09, 0x0A]
TOPKEY_CHOICES = ["None", "Alarming"]
TOPKEY_VALUES = [0xFF, 0x0C]

SETTING_LISTS = {
    "alarm": ALARM_LIST,
    "bcl": BCL_LIST,
    "cdcss": CDCSS_LIST,
    "cdcss": CDCSS2_LIST,
    "gain": GAIN_LIST,
    "pfkey": PFKEY_LIST,
    "save": SAVE_LIST,
    "tot": TIMEOUTTIMER_LIST,
    "totalert": TOTALERT_LIST,
    "voice": VOICE_LIST,
    "voice": VOICE_LIST2,
    "voice": VOICE_LIST3,
    "vox": VOX_LIST,
    "voxd": VOXD_LIST,
    "voxl": VOXL_LIST,
    "warn": WARN_LIST,
    }

GMRS_FREQS1 = [462.5625, 462.5875, 462.6125, 462.6375, 462.6625,
               462.6875, 462.7125]
GMRS_FREQS2 = [467.5625, 467.5875, 467.6125, 467.6375, 467.6625,
               467.6875, 467.7125]
GMRS_FREQS3 = [462.5500, 462.5750, 462.6000, 462.6250, 462.6500,
               462.6750, 462.7000, 462.7250]
GMRS_FREQS = GMRS_FREQS1 + GMRS_FREQS2 + GMRS_FREQS3 * 2


def _enter_programming_mode(radio):
    serial = radio.pipe

    exito = False
    for i in range(0, 5):
        serial.write(radio._magic)
        ack = serial.read(1)
        if ack == "\x00":
            ack = serial.read(1)

        try:
            if ack == CMD_ACK:
                exito = True
                break
        except:
            LOG.debug("Attempt #%s, failed, trying again" % i)
            pass

    # check if we had EXITO
    if exito is False:
        msg = "The radio did not accept program mode after five tries.\n"
        msg += "Check you interface cable and power cycle your radio."
        raise errors.RadioError(msg)

    try:
        serial.write("\x02")
        ident = serial.read(8)
    except:
        raise errors.RadioError("Error communicating with radio")

    if not ident == radio._fingerprint:
        LOG.debug(util.hexprint(ident))
        raise errors.RadioError("Radio returned unknown identification string")

    try:
        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Error communicating with radio")

    if ack != CMD_ACK:
        raise errors.RadioError("Radio refused to enter programming mode")


def _exit_programming_mode(radio):
    serial = radio.pipe
    try:
        serial.write("E")
    except:
        raise errors.RadioError("Radio refused to exit programming mode")


def _read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        serial.write(CMD_ACK)
        ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if ack != CMD_ACK:
        raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _rb26_read_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'R', block_addr, block_size)
    expectedresponse = "W" + cmd[1:]
    LOG.debug("Reading block %04x..." % (block_addr))

    try:
        serial.write(cmd)
        response = serial.read(4 + block_size)
        if response[:4] != expectedresponse:
            raise Exception("Error reading block %04x." % (block_addr))

        block_data = response[4:]

        if block_addr != 0:
            serial.write(CMD_ACK)
            ack = serial.read(1)
    except:
        raise errors.RadioError("Failed to read block at %04x" % block_addr)

    if block_addr != 0:
        if ack != CMD_ACK:
            raise Exception("No ACK reading block %04x." % (block_addr))

    return block_data


def _write_block(radio, block_addr, block_size):
    serial = radio.pipe

    cmd = struct.pack(">cHb", 'W', block_addr, block_size)
    data = radio.get_mmap()[block_addr:block_addr + block_size]

    LOG.debug("Writing Data:")
    LOG.debug(util.hexprint(cmd + data))

    try:
        serial.write(cmd + data)
        if serial.read(1) != CMD_ACK:
            raise Exception("No ACK")
    except:
        raise errors.RadioError("Failed to send block "
                                "to radio at %04x" % block_addr)


def do_download(radio):
    LOG.debug("download")
    _enter_programming_mode(radio)

    data = ""

    status = chirp_common.Status()
    status.msg = "Cloning from radio"

    status.cur = 0
    status.max = radio._memsize

    for addr in range(0, radio._memsize, radio.BLOCK_SIZE):
        status.cur = addr + radio.BLOCK_SIZE
        radio.status_fn(status)

        if radio.MODEL == "RB26" or radio.MODEL == "RT76":
            block = _rb26_read_block(radio, addr, radio.BLOCK_SIZE)
        else:
            block = _read_block(radio, addr, radio.BLOCK_SIZE)
        data += block

        LOG.debug("Address: %04x" % addr)
        LOG.debug(util.hexprint(block))

    _exit_programming_mode(radio)

    return memmap.MemoryMap(data)


def do_upload(radio):
    status = chirp_common.Status()
    status.msg = "Uploading to radio"

    _enter_programming_mode(radio)

    status.cur = 0
    status.max = radio._memsize

    for start_addr, end_addr in radio._ranges:
        for addr in range(start_addr, end_addr, radio.BLOCK_SIZE_UP):
            status.cur = addr + radio.BLOCK_SIZE_UP
            radio.status_fn(status)
            _write_block(radio, addr, radio.BLOCK_SIZE_UP)

    _exit_programming_mode(radio)


def model_match(cls, data):
    """Match the opened/downloaded image to the correct version"""
    rid = data[0x01B8:0x01BE]

    return rid.startswith("P3207")


@directory.register
class RT21Radio(chirp_common.CloneModeRadio):
    """RETEVIS RT21"""
    VENDOR = "Retevis"
    MODEL = "RT21"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x10
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=1.00),
                    chirp_common.PowerLevel("High", watts=2.50)]

    VALID_BANDS = [(400000000, 480000000)]

    _magic = "PRMZUNE"
    _fingerprint = "P3207s\xF8\xFF"
    _upper = 16
    _skipflags = True
    _reserved = False
    _gmrs = False

    _ranges = [
               (0x0000, 0x0400),
              ]
    _memsize = 0x0400

    def get_features(self):
        rf = chirp_common.RadioFeatures()
        rf.has_settings = True
        rf.has_bank = False
        rf.has_ctone = True
        rf.has_cross = True
        rf.has_rx_dtcs = True
        rf.has_tuning_step = False
        rf.can_odd_split = True
        rf.has_name = False
        if self.MODEL == "RT76":
            rf.valid_skips = []
        else:
            rf.valid_skips = ["", "S"]
        rf.valid_tmodes = ["", "Tone", "TSQL", "DTCS", "Cross"]
        rf.valid_cross_modes = ["Tone->Tone", "Tone->DTCS", "DTCS->Tone",
                                "->Tone", "->DTCS", "DTCS->", "DTCS->DTCS"]
        rf.valid_power_levels = self.POWER_LEVELS
        rf.valid_duplexes = ["", "-", "+", "split", "off"]
        rf.valid_modes = ["NFM", "FM"]  # 12.5 KHz, 25 kHz.
        rf.memory_bounds = (1, self._upper)
        rf.valid_tuning_steps = [2.5, 5., 6.25, 10., 12.5, 25.]
        rf.valid_bands = self.VALID_BANDS

        return rf

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT, self._mmap)

    def validate_memory(self, mem):
        msgs = ""
        msgs = chirp_common.CloneModeRadio.validate_memory(self, mem)

        _msg_freq = 'Memory location cannot change frequency'
        _msg_simplex = 'Memory location only supports Duplex:(None)'
        _msg_duplex = 'Memory location only supports Duplex: +'
        _msg_offset = 'Memory location only supports Offset: 5.000000'
        _msg_nfm = 'Memory location only supports Mode: NFM'
        _msg_txp = 'Memory location only supports Power: Low'

        # GMRS models
        if self._gmrs:
            # range of memories with values set by FCC rules
            if mem.freq != int(GMRS_FREQS[mem.number - 1] * 1000000):
                # warn user can't change frequency
                msgs.append(chirp_common.ValidationError(_msg_freq))

            # channels 1 - 22 are simplex only
            if mem.number <= 22:
                if str(mem.duplex) != "":
                    # warn user can't change duplex
                    msgs.append(chirp_common.ValidationError(_msg_simplex))

            # channels 23 - 30 are +5 MHz duplex only
            if mem.number >= 23:
                if str(mem.duplex) != "+":
                    # warn user can't change duplex
                    msgs.append(chirp_common.ValidationError(_msg_duplex))

                if str(mem.offset) != "5000000":
                    # warn user can't change offset
                    msgs.append(chirp_common.ValidationError(_msg_offset))

            # channels 8 - 14 are low power NFM only
            if mem.number >= 8 and mem.number <= 14:
                if mem.mode != "NFM":
                    # warn user can't change mode
                    msgs.append(chirp_common.ValidationError(_msg_nfm))

                if mem.power != "Low":
                    # warn user can't change power
                    msgs.append(chirp_common.ValidationError(_msg_txp))

        return msgs

    def sync_in(self):
        """Download from radio"""
        try:
            data = do_download(self)
        except errors.RadioError:
            # Pass through any real errors we raise
            raise
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during download')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')
        self._mmap = data
        self.process_mmap()

    def sync_out(self):
        """Upload to radio"""
        try:
            do_upload(self)
        except:
            # If anything unexpected happens, make sure we raise
            # a RadioError and log the problem
            LOG.exception('Unexpected error during upload')
            raise errors.RadioError('Unexpected error communicating '
                                    'with the radio')

    def get_raw_memory(self, number):
        return repr(self._memobj.memory[number - 1])

    def _get_tone(self, _mem, mem):
        def _get_dcs(val):
            code = int("%03o" % (val & 0x07FF))
            pol = (val & 0x8000) and "R" or "N"
            return code, pol

        if _mem.tx_tone != 0xFFFF and _mem.tx_tone > 0x2000:
            tcode, tpol = _get_dcs(_mem.tx_tone)
            mem.dtcs = tcode
            txmode = "DTCS"
        elif _mem.tx_tone != 0xFFFF:
            mem.rtone = _mem.tx_tone / 10.0
            txmode = "Tone"
        else:
            txmode = ""

        if _mem.rx_tone != 0xFFFF and _mem.rx_tone > 0x2000:
            rcode, rpol = _get_dcs(_mem.rx_tone)
            mem.rx_dtcs = rcode
            rxmode = "DTCS"
        elif _mem.rx_tone != 0xFFFF:
            mem.ctone = _mem.rx_tone / 10.0
            rxmode = "Tone"
        else:
            rxmode = ""

        if txmode == "Tone" and not rxmode:
            mem.tmode = "Tone"
        elif txmode == rxmode and txmode == "Tone" and mem.rtone == mem.ctone:
            mem.tmode = "TSQL"
        elif txmode == rxmode and txmode == "DTCS" and mem.dtcs == mem.rx_dtcs:
            mem.tmode = "DTCS"
        elif rxmode or txmode:
            mem.tmode = "Cross"
            mem.cross_mode = "%s->%s" % (txmode, rxmode)

        if mem.tmode == "DTCS":
            mem.dtcs_polarity = "%s%s" % (tpol, rpol)

        LOG.debug("Got TX %s (%i) RX %s (%i)" %
                  (txmode, _mem.tx_tone, rxmode, _mem.rx_tone))

    def get_memory(self, number):
        if self._skipflags:
            bitpos = (1 << ((number - 1) % 8))
            bytepos = ((number - 1) / 8)
            LOG.debug("bitpos %s" % bitpos)
            LOG.debug("bytepos %s" % bytepos)
            _skp = self._memobj.skipflags[bytepos]

        mem = chirp_common.Memory()

        mem.number = number

        if self.MODEL == "RB17A":
            if mem.number < 17:
                _mem = self._memobj.lomems[number - 1]
            else:
                _mem = self._memobj.himems[number - 17]
        else:
            _mem = self._memobj.memory[number - 1]

        if self._reserved:
            _rsvd = _mem.reserved.get_raw()

        mem.freq = int(_mem.rxfreq) * 10

        # We'll consider any blank (i.e. 0MHz frequency) to be empty
        if mem.freq == 0:
            mem.empty = True
            return mem

        if _mem.rxfreq.get_raw() == "\xFF\xFF\xFF\xFF":
            mem.freq = 0
            mem.empty = True
            return mem

        if _mem.get_raw() == ("\xFF" * 16):
            LOG.debug("Initializing empty memory")
            if self.MODEL == "RB17A":
                _mem.set_raw("\x00" * 13 + "\x04\xFF\xFF")
            if self.MODEL == "RB26" or self.MODEL == "RT76":
                _mem.set_raw("\x00" * 13 + _rsvd)
            else:
                _mem.set_raw("\x00" * 13 + "\x30\x8F\xF8")

        if int(_mem.rxfreq) == int(_mem.txfreq):
            mem.duplex = ""
            mem.offset = 0
        else:
            mem.duplex = int(_mem.rxfreq) > int(_mem.txfreq) and "-" or "+"
            mem.offset = abs(int(_mem.rxfreq) - int(_mem.txfreq)) * 10

        mem.mode = _mem.wide and "FM" or "NFM"

        self._get_tone(_mem, mem)

        if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
            # set the power level
            if _mem.txpower == self.TXPOWER_LOW:
                mem.power = self.POWER_LEVELS[2]
            elif _mem.txpower == self.TXPOWER_MED:
                mem.power = self.POWER_LEVELS[1]
            elif _mem.txpower == self.TXPOWER_HIGH:
                mem.power = self.POWER_LEVELS[0]
            else:
                LOG.error('%s: get_mem: unhandled power level: 0x%02x' %
                          (mem.name, _mem.txpower))
        else:
            mem.power = self.POWER_LEVELS[_mem.highpower]

        if self.MODEL != "RT76":
            mem.skip = "" if (_skp & bitpos) else "S"
            LOG.debug("mem.skip %s" % mem.skip)

        mem.extra = RadioSettingGroup("Extra", "extra")

        if self.MODEL == "RT21" or self.MODEL == "RB17A" or \
                self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
            rs = RadioSettingValueList(BCL_LIST, BCL_LIST[_mem.bcl])
            rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
            mem.extra.append(rset)

            rs = RadioSettingValueInteger(1, 8, _mem.scramble_type + 1)
            rset = RadioSetting("scramble_type", "Scramble Type", rs)
            mem.extra.append(rset)

            if self.MODEL == "RB17A":
                rs = RadioSettingValueList(CDCSS_LIST, CDCSS_LIST[_mem.cdcss])
                rset = RadioSetting("cdcss", "Cdcss Mode", rs)
                mem.extra.append(rset)

            if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
                rs = RadioSettingValueList(CDCSS2_LIST,
                                           CDCSS2_LIST[_mem.cdcss])
                rset = RadioSetting("cdcss", "Cdcss Mode", rs)
                mem.extra.append(rset)

            if self.MODEL == "RB17A" or self.MODEL == "RT29_UHF" or \
                    self.MODEL == "RT29_VHF":
                rs = RadioSettingValueBoolean(_mem.compander)
                rset = RadioSetting("compander", "Compander", rs)
                mem.extra.append(rset)

        if self.MODEL == "RB26" or self.MODEL == "RT76":
            if self.MODEL == "RB26":
                rs = RadioSettingValueBoolean(_mem.bcl)
                rset = RadioSetting("bcl", "Busy Channel Lockout", rs)
                mem.extra.append(rset)

            rs = RadioSettingValueBoolean(_mem.compander)
            rset = RadioSetting("compander", "Compander", rs)
            mem.extra.append(rset)

        if self._gmrs:
            GMRS_IMMUTABLE = ["freq", "duplex", "offset"]
            if mem.number >= 8 and mem.number <= 14:
                mem.immutable = GMRS_IMMUTABLE + ["power", "mode"]
            else:
                mem.immutable = GMRS_IMMUTABLE

        return mem

    def _set_tone(self, mem, _mem):
        def _set_dcs(code, pol):
            val = int("%i" % code, 8) + 0x2800
            if pol == "R":
                val += 0x8000
            return val

        rx_mode = tx_mode = None
        rx_tone = tx_tone = 0xFFFF

        if mem.tmode == "Tone":
            tx_mode = "Tone"
            rx_mode = None
            tx_tone = int(mem.rtone * 10)
        elif mem.tmode == "TSQL":
            rx_mode = tx_mode = "Tone"
            rx_tone = tx_tone = int(mem.ctone * 10)
        elif mem.tmode == "DTCS":
            tx_mode = rx_mode = "DTCS"
            tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            rx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[1])
        elif mem.tmode == "Cross":
            tx_mode, rx_mode = mem.cross_mode.split("->")
            if tx_mode == "DTCS":
                tx_tone = _set_dcs(mem.dtcs, mem.dtcs_polarity[0])
            elif tx_mode == "Tone":
                tx_tone = int(mem.rtone * 10)
            if rx_mode == "DTCS":
                rx_tone = _set_dcs(mem.rx_dtcs, mem.dtcs_polarity[1])
            elif rx_mode == "Tone":
                rx_tone = int(mem.ctone * 10)

        _mem.rx_tone = rx_tone
        _mem.tx_tone = tx_tone

        LOG.debug("Set TX %s (%i) RX %s (%i)" %
                  (tx_mode, _mem.tx_tone, rx_mode, _mem.rx_tone))

    def set_memory(self, mem):
        if self._skipflags:
            bitpos = (1 << ((mem.number - 1) % 8))
            bytepos = ((mem.number - 1) / 8)
            LOG.debug("bitpos %s" % bitpos)
            LOG.debug("bytepos %s" % bytepos)
            _skp = self._memobj.skipflags[bytepos]

        if self.MODEL == "RB17A":
            if mem.number < 17:
                _mem = self._memobj.lomems[mem.number - 1]
            else:
                _mem = self._memobj.himems[mem.number - 17]
        else:
            _mem = self._memobj.memory[mem.number - 1]

        if self._reserved:
            _rsvd = _mem.reserved.get_raw()

        if mem.empty:
            if self.MODEL == "RB17A":
                _mem.set_raw("\xFF" * 12 + "\x00\x00\xFF\xFF")
            elif self.MODEL == "RB26" or self.MODEL == "RT76":
                _mem.set_raw("\xFF" * 13 + _rsvd)
            else:
                _mem.set_raw("\xFF" * (_mem.size() / 8))

            if self._gmrs:
                GMRS_FREQ = int(GMRS_FREQS[mem.number - 1] * 100000)
                if mem.number > 22:
                    _mem.rxfreq = GMRS_FREQ
                    _mem.txfreq = int(_mem.rxfreq) + 500000
                    _mem.wide = True
                else:
                    _mem.rxfreq = _mem.txfreq = GMRS_FREQ
                if mem.number >= 8 and mem.number <= 14:
                    _mem.wide = False
                    _mem.highpower = False
                else:
                    _mem.wide = True
                    _mem.highpower = True

            return

        if self.MODEL == "RB17A":
            _mem.set_raw("\x00" * 13 + "\x00\xFF\xFF")
        elif self.MODEL == "RB26" or self.MODEL == "RT76":
            _mem.set_raw("\x00" * 13 + _rsvd)
        else:
            _mem.set_raw("\x00" * 13 + "\x30\x8F\xF8")

        _mem.rxfreq = mem.freq / 10

        if mem.duplex == "off":
            for i in range(0, 4):
                _mem.txfreq[i].set_raw("\xFF")
        elif mem.duplex == "split":
            _mem.txfreq = mem.offset / 10
        elif mem.duplex == "+":
            _mem.txfreq = (mem.freq + mem.offset) / 10
        elif mem.duplex == "-":
            _mem.txfreq = (mem.freq - mem.offset) / 10
        else:
            _mem.txfreq = mem.freq / 10

        _mem.wide = mem.mode == "FM"

        self._set_tone(mem, _mem)

        if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
            # set the power level
            if mem.power == self.POWER_LEVELS[2]:
                _mem.txpower = self.TXPOWER_LOW
            elif mem.power == self.POWER_LEVELS[1]:
                _mem.txpower = self.TXPOWER_MED
            elif mem.power == self.POWER_LEVELS[0]:
                _mem.txpower = self.TXPOWER_HIGH
            else:
                LOG.error('%s: set_mem: unhandled power level: %s' %
                          (mem.name, mem.power))
        else:
            _mem.highpower = mem.power == self.POWER_LEVELS[1]

        if self.MODEL != "RT76":
            if mem.skip != "S":
                _skp |= bitpos
            else:
                _skp &= ~bitpos
            LOG.debug("_skp %s" % _skp)

        for setting in mem.extra:
            if setting.get_name() == "scramble_type":
                setattr(_mem, setting.get_name(), int(setting.value) - 1)
                if self.MODEL == "RT21":
                    setattr(_mem, "scramble_type2", int(setting.value) - 1)
            else:
                setattr(_mem, setting.get_name(), setting.value)

    def get_settings(self):
        _settings = self._memobj.settings
        basic = RadioSettingGroup("basic", "Basic Settings")
        top = RadioSettings(basic)

        if self.MODEL == "RT21" or self.MODEL == "RB17A" or \
                self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
            _keys = self._memobj.keys

            rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                       TIMEOUTTIMER_LIST[_settings.tot])
            rset = RadioSetting("tot", "Time-out timer", rs)
            basic.append(rset)

            rs = RadioSettingValueList(TOTALERT_LIST,
                                       TOTALERT_LIST[_settings.totalert])
            rset = RadioSetting("totalert", "TOT Pre-alert", rs)
            basic.append(rset)

            rs = RadioSettingValueInteger(0, 9, _settings.squelch)
            rset = RadioSetting("squelch", "Squelch Level", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOICE_LIST, VOICE_LIST[_settings.voice])
            rset = RadioSetting("voice", "Voice Annumciation", rs)
            basic.append(rset)

            if self.MODEL == "RB17A":
                rs = RadioSettingValueList(ALARM_LIST,
                                           ALARM_LIST[_settings.alarm])
                rset = RadioSetting("alarm", "Alarm Type", rs)
                basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.save)
            rset = RadioSetting("save", "Battery Saver", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.use_scramble)
            rset = RadioSetting("use_scramble", "Scramble", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.use_vox)
            rset = RadioSetting("use_vox", "VOX", rs)
            basic.append(rset)

            rs = RadioSettingValueList(VOX_LIST, VOX_LIST[_settings.vox])
            rset = RadioSetting("vox", "VOX Gain", rs)
            basic.append(rset)

            if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
                rs = RadioSettingValueList(VOXD_LIST,
                                           VOXD_LIST[_settings.voxd])
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

            def apply_pf1_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(
                          setting.value) + " from list")
                val = str(setting.value)
                index = PF1_CHOICES.index(val)
                val = PF1_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RT21":
                if _keys.pf1 in PF1_VALUES:
                    idx = PF1_VALUES.index(_keys.pf1)
                else:
                    idx = LIST_DTMF_SPECIAL_VALUES.index(0x04)
                rs = RadioSettingValueList(PF1_CHOICES, PF1_CHOICES[idx])
                rset = RadioSetting("keys.pf1", "PF1 Key Function", rs)
                rset.set_apply_callback(apply_pf1_listvalue, _keys.pf1)
                basic.append(rset)

            def apply_pf1_17a_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(
                          setting.value) + " from list")
                val = str(setting.value)
                index = PF1_17A_CHOICES.index(val)
                val = PF1_17A_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RB17A":
                if _keys.pf1 in PF1_17A_VALUES:
                    idx = PF1_17A_VALUES.index(_keys.pf1)
                else:
                    idx = LIST_DTMF_SPECIAL_VALUES.index(0x04)
                rs = RadioSettingValueList(PF1_17A_CHOICES,
                                           PF1_17A_CHOICES[idx])
                rset = RadioSetting("keys.pf1", "PF1 Key Function", rs)
                rset.set_apply_callback(apply_pf1_17a_listvalue, _keys.pf1)
                basic.append(rset)

            def apply_topkey_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = TOPKEY_CHOICES.index(val)
                val = TOPKEY_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RB17A":
                if _keys.topkey in TOPKEY_VALUES:
                    idx = TOPKEY_VALUES.index(_keys.topkey)
                else:
                    idx = TOPKEY_VALUES.index(0x0C)
                rs = RadioSettingValueList(TOPKEY_CHOICES, TOPKEY_CHOICES[idx])
                rset = RadioSetting("keys.topkey", "Top Key Function", rs)
                rset.set_apply_callback(apply_topkey_listvalue, _keys.topkey)
                basic.append(rset)

            def apply_pfkey_listvalue(setting, obj):
                LOG.debug("Setting value: " + str(setting.value) +
                          " from list")
                val = str(setting.value)
                index = PFKEY_CHOICES.index(val)
                val = PFKEY_VALUES[index]
                obj.set_value(val)

            if self.MODEL == "RT29_UHF" or self.MODEL == "RT29_VHF":
                if _keys.pf1 in PFKEY_VALUES:
                    idx = PFKEY_VALUES.index(_keys.pf1)
                else:
                    idx = PFKEY_VALUES.index(0x04)
                rs = RadioSettingValueList(PFKEY_CHOICES, PFKEY_CHOICES[idx])
                rset = RadioSetting("keys.pf1", "PF1 Key Function", rs)
                rset.set_apply_callback(apply_pfkey_listvalue, _keys.pf1)
                basic.append(rset)

                if _keys.pf2 in PFKEY_VALUES:
                    idx = PFKEY_VALUES.index(_keys.pf2)
                else:
                    idx = PFKEY_VALUES.index(0x0A)
                rs = RadioSettingValueList(PFKEY_CHOICES, PFKEY_CHOICES[idx])
                rset = RadioSetting("keys.pf2", "PF2 Key Function", rs)
                rset.set_apply_callback(apply_pfkey_listvalue, _keys.pf2)
                basic.append(rset)

        if self.MODEL == "RB26" or self.MODEL == "RT76":
            if self.MODEL == "RB26":
                _settings2 = self._memobj.settings2
                _settings3 = self._memobj.settings3

            rs = RadioSettingValueInteger(0, 9, _settings.squelch)
            rset = RadioSetting("squelch", "Squelch Level", rs)
            basic.append(rset)

            rs = RadioSettingValueList(TIMEOUTTIMER_LIST,
                                       TIMEOUTTIMER_LIST[_settings.tot])
            rset = RadioSetting("tot", "Time-out timer", rs)
            basic.append(rset)

            if self.MODEL == "RT76":
                rs = RadioSettingValueList(VOICE_LIST3,
                                           VOICE_LIST3[_settings.voice])
                rset = RadioSetting("voice", "Voice Annumciation", rs)
                basic.append(rset)

            if self.MODEL == "RB26":
                rs = RadioSettingValueList(VOICE_LIST2,
                                           VOICE_LIST2[_settings.voice])
                rset = RadioSetting("voice", "Voice Annumciation", rs)
                basic.append(rset)

                rs = RadioSettingValueBoolean(not _settings.chnumberd)
                rset = RadioSetting("chnumberd", "Channel Number Enable", rs)
                basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.save)
            rset = RadioSetting("save", "Battery Save", rs)
            basic.append(rset)

            rs = RadioSettingValueBoolean(_settings.beep)
            rset = RadioSetting("beep", "Beep", rs)
            basic.append(rset)

            if self.MODEL == "RB26":
                rs = RadioSettingValueBoolean(not _settings.tail)
                rset = RadioSetting("tail", "QT/DQT Tail", rs)
                basic.append(rset)

            rs = RadioSettingValueList(SAVE_LIST, SAVE_LIST[_settings.savem])
            rset = RadioSetting("savem", "Battery Save Mode", rs)
            basic.append(rset)

            rs = RadioSettingValueList(GAIN_LIST, GAIN_LIST[_settings.gain])
            rset = RadioSetting("gain", "MIC Gain", rs)
            basic.append(rset)

            rs = RadioSettingValueList(WARN_LIST, WARN_LIST[_settings.warn])
            rset = RadioSetting("warn", "Warn Mode", rs)
            basic.append(rset)

            if self.MODEL == "RB26":
                rs = RadioSettingValueBoolean(_settings3.vox)
                rset = RadioSetting("settings3.vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           VOXL_LIST[_settings3.voxl])
                rset = RadioSetting("settings3.voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           VOXD_LIST[_settings3.voxd])
                rset = RadioSetting("settings3.voxd", "Vox Delay", rs)
                basic.append(rset)

                rs = RadioSettingValueList(PFKEY_LIST,
                                           PFKEY_LIST[_settings.pf1])
                rset = RadioSetting("pf1", "PF1 Key Set", rs)
                basic.append(rset)

                rs = RadioSettingValueList(PFKEY_LIST,
                                           PFKEY_LIST[_settings.pf2])
                rset = RadioSetting("pf2", "PF2 Key Set", rs)
                basic.append(rset)

                rs = RadioSettingValueInteger(1, 30, _settings2.chnumber + 1)
                rset = RadioSetting("settings2.chnumber", "Channel Number", rs)
                basic.append(rset)

            if self.MODEL == "RT76":
                rs = RadioSettingValueBoolean(_settings.vox)
                rset = RadioSetting("vox", "Vox Function", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXL_LIST,
                                           VOXL_LIST[_settings.voxl])
                rset = RadioSetting("voxl", "Vox Level", rs)
                basic.append(rset)

                rs = RadioSettingValueList(VOXD_LIST,
                                           VOXD_LIST[_settings.voxd])
                rset = RadioSetting("voxd", "Vox Delay", rs)
                basic.append(rset)

                rs = RadioSettingValueInteger(1, 30, _settings.chnumber + 1)
                rset = RadioSetting("chnumber", "Channel Number", rs)
                basic.append(rset)

        return top

    def set_settings(self, settings):
        for element in settings:
            if not isinstance(element, RadioSetting):
                self.set_settings(element)
                continue
            else:
                try:
                    if "." in element.get_name():
                        bits = element.get_name().split(".")
                        obj = self._memobj
                        for bit in bits[:-1]:
                            obj = getattr(obj, bit)
                        setting = bits[-1]
                    else:
                        obj = self._memobj.settings
                        setting = element.get_name()

                    if element.has_apply_callback():
                        LOG.debug("Using apply callback")
                        element.run_apply_callback()
                    elif setting == "channel":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "chnumber":
                        setattr(obj, setting, int(element.value) - 1)
                    elif setting == "chnumberd":
                        setattr(obj, setting, not int(element.value))
                    elif setting == "tail":
                        setattr(obj, setting, not int(element.value))
                    elif element.value.get_mutable():
                        LOG.debug("Setting %s = %s" % (setting, element.value))
                        setattr(obj, setting, element.value)
                except Exception, e:
                    LOG.debug(element.get_name())
                    raise

    @classmethod
    def match_model(cls, filedata, filename):
        if cls.MODEL == "RT21":
            # The RT21 is pre-metadata, so do old-school detection
            match_size = False
            match_model = False

            # testing the file data size
            if len(filedata) in [0x0400, ]:
                match_size = True

            # testing the model fingerprint
            match_model = model_match(cls, filedata)

            if match_size and match_model:
                return True
            else:
                return False
        else:
            # Radios that have always been post-metadata, so never do
            # old-school detection
            return False


@directory.register
class RB17ARadio(RT21Radio):
    """RETEVIS RB17A"""
    VENDOR = "Retevis"
    MODEL = "RB17A"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=5.00)]

    _magic = "PROA8US"
    _fingerprint = "P3217s\xF8\xFF"
    _upper = 30
    _skipflags = True
    _reserved = False
    _gmrs = True

    _ranges = [
               (0x0000, 0x0300),
              ]
    _memsize = 0x0300

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB17A, self._mmap)


@directory.register
class RB26Radio(RT21Radio):
    """RETEVIS RB26"""
    VENDOR = "Retevis"
    MODEL = "RB26"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=3.00)]

    _magic = "PHOGR" + "\x01" + "0"
    _fingerprint = "P32073" + "\x02\xFF"
    _upper = 30
    _skipflags = True
    _reserved = True
    _gmrs = True

    _ranges = [
               (0x0000, 0x0320),
              ]
    _memsize = 0x0320

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RB26, self._mmap)


@directory.register
class RT76Radio(RT21Radio):
    """RETEVIS RT76"""
    VENDOR = "Retevis"
    MODEL = "RT76"
    BAUD_RATE = 9600
    BLOCK_SIZE = 0x20
    BLOCK_SIZE_UP = 0x10

    POWER_LEVELS = [chirp_common.PowerLevel("Low", watts=0.50),
                    chirp_common.PowerLevel("High", watts=5.00)]

    _magic = "PHOGR\x14\xD4"
    _fingerprint = "P32073" + "\x02\xFF"
    _upper = 30
    _skipflags = False
    _reserved = True
    _gmrs = True

    _ranges = [
               (0x0000, 0x01E0),
              ]
    _memsize = 0x01E0

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT76, self._mmap)


@directory.register
class RT29UHFRadio(RT21Radio):
    """RETEVIS RT29UHF"""
    VENDOR = "Retevis"
    MODEL = "RT29_UHF"
    BLOCK_SIZE = 0x40
    BLOCK_SIZE_UP = 0x10

    TXPOWER_MED = 0x00
    TXPOWER_HIGH = 0x01
    TXPOWER_LOW = 0x02

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=10.00),
                    chirp_common.PowerLevel("Mid", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]

    _magic = "PROHRAM"
    _fingerprint = "P3207" + "\x13\xF8\xFF"  # UHF model
    _upper = 16
    _skipflags = True
    _reserved = False

    _ranges = [
               (0x0000, 0x0300),
              ]
    _memsize = 0x0400

    def process_mmap(self):
        self._memobj = bitwise.parse(MEM_FORMAT_RT29, self._mmap)


@directory.register
class RT29VHFRadio(RT29UHFRadio):
    """RETEVIS RT29VHF"""
    VENDOR = "Retevis"
    MODEL = "RT29_VHF"

    TXPOWER_MED = 0x00
    TXPOWER_HIGH = 0x01
    TXPOWER_LOW = 0x02

    POWER_LEVELS = [chirp_common.PowerLevel("High", watts=10.00),
                    chirp_common.PowerLevel("Mid", watts=5.00),
                    chirp_common.PowerLevel("Low", watts=1.00)]

    VALID_BANDS = [(136000000, 174000000)]

    _magic = "PROHRAM"
    _fingerprint = "P2207" + "\x01\xF8\xFF"  # VHF model
