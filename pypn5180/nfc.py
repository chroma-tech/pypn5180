import time
import struct
from machine import Pin

from . import iso_iec_15693
from . import pypn5180
from . import ndef


class NfcTag:
    def __init__(self, uid, block_size, num_blocks):
        self.uid = uid
        self.block_size = block_size
        self.num_blocks = num_blocks


class NfcTlv:
    TypeNdef = 3
    TypeProprietary = 0xFD
    TypeTerminator = 0xFE

    def __init__(self, data):
        self.type = data[0]
        self.length = data[1]
        self.size = 2
        if self.length == 0xFF:
            self.length = struct.unpack_from("<H", data[2])
            self.size = 4


class NfcReader:
    def __init__(self, spi, cs, busy, rst):
        self.rst = Pin(rst, Pin.OUT)
        self.reset()
        device = pypn5180.PN5180(spi=spi, cs=cs, busy=busy)
        self.reader = iso_iec_15693.iso_iec_15693(device)
        self.tag = None

    def reset(self):
        self.rst.value(0)
        time.sleep_ms(50)
        self.rst.value(1)

    def read(self, tag, offset, bytes):
        skip = offset % tag.block_size
        offset -= skip
        start_block = offset // tag.block_size
        total_bytes = bytes + skip
        total_bytes += total_bytes % tag.block_size
        num_blocks = total_bytes // tag.block_size
        num_blocks -= 1
        data, err = self.reader.readMultipleBlocksCmd(start_block, num_blocks, tag.uid)
        return data[skip : skip + bytes]

    def write(self, tag, offset, data):
        delta = offset % tag.block_size
        data = ([0] * delta) + data
        data += [0] * (len(data) % tag.block_size)
        num_blocks = len(data) // tag.block_size
        num_blocks -= 1
        start_block = (offset - delta) % tag.block_size
        ret, err = self.reader.writeMultipleBlocksCmd(
            start_block, num_blocks, data, tag.uid
        )
        if ret != num_blocks:
            print(ret, err)
            raise Exception("Error in write")

    def readNdef(self, tag):
        # read CC, which is either 4 or 8 bytes. Lets assume 4 for now to keep it simple
        header = self.read(tag, 0, 8)
        if header[0] not in [0xE1, 0xE2] or header[1] & 0xFC != 0x40:
            raise Exception("Tag not formatted")

        # read TLV chunks until we find one with an Ndef message
        offset = 4
        mem_size = header[2]
        if mem_size == 0:
            mem_size = (header[6] << 8) | header[7]
            offset = 8
        mem_size *= 8

        # read TLV records starting from offset and no more than mem_size
        while offset < mem_size:
            tlv = NfcTlv(self.read(tag, offset, 4))
            offset += tlv.size

            if tlv.type == NfcTlv.TypeNdef:
                ndef_bytes = self.read(tag, offset, tlv.length)
                return ndef.NdefMessage(ndef_bytes)

            if tlv.type == NfcTlv.TypeProprietary:
                offset += tlv.length
                continue

            if tlv.type == NfcTlv.TypeTerminator:
                break

        return None

    def writeNdef(self, tag, ndefmsg):
        ndef_bytes = ndefmsg.to_buffer()

        buffer = []
        buffer.extend[0xE1, 0x40]
        buffer.append(NfcTlv.TypeNdef)
        buffer.append(len(ndef_bytes))
        buffer.extend(ndef_bytes)
        buffer.append(NfcTlv.TypeTerminator)

        self.write(tag, 0, buffer)

    def tick(self):
        current_uid, err = self.reader.inventoryCmd()
        last_uid = self.tag.uid if self.tag is not None else None

        if current_uid != last_uid:
            if self.tag is not None:
                self.tag = None
                # TODO: tag gone event
                print("Tag lost")

            if current_uid:
                # read tag info
                info, err = self.reader.getSystemInformationCmd(current_uid)
                if info:
                    self.tag = NfcTag(current_uid, info.block_size, info.num_blocks)
                    print("Ndef: ", self.readNdef(self.tag))
                    # TODO: new tag event
                    print("New tag", self.tag)
