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

        self.header_size = 0
        self.mem_size = 0

    def __repr__(self):
        return f"UID: {self.uid}  Block size: {self.block_size}  Num blocks: {self.num_blocks}  Mem size: {self.mem_size}  Header size: {self.header_size}"


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


def chunks(buffer, block_size):
    # This function yields chunks of the buffer of size block_size.
    for i in range(0, len(buffer), block_size):
        yield buffer[i : i + block_size]


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

    def read(self, offset, bytes):
        if self.tag is None:
            raise Exception("No tag")

        skip = offset % self.tag.block_size
        offset -= skip
        start_block = offset // self.tag.block_size
        total_bytes = bytes + skip
        total_bytes += total_bytes % self.tag.block_size
        num_blocks = total_bytes // self.tag.block_size
        num_blocks -= 1
        data, err = self.reader.readMultipleBlocksCmd(
            start_block, num_blocks, self.tag.uid
        )
        return data[skip : skip + bytes]

    def write(self, offset, data):
        if self.tag is None:
            raise Exception("No tag")

        print(f"Write. Offset: {offset}. Len: {len(data)}")

        # make sure our data is aligned to block size
        delta_pre = offset % self.tag.block_size
        data = ([0] * delta_pre) + data
        delta_post = self.tag.block_size - (len(data) % self.tag.block_size)
        data += [0] * delta_post

        # loop through block_size chunks of the data
        start_block = (offset - delta_pre) // self.tag.block_size
        for block_num, block_data in enumerate(
            chunks(data, self.tag.block_size), start=start_block
        ):
            data, err = self.reader.writeSingleBlockCmd(
                block_num, block_data, self.tag.uid
            )
            if data:
                raise Exception(f"Error writing block {block_num}: {err}")

    def readHeader(self, format=True):
        if self.tag is None:
            raise Exception("No tag")

        # read CC, which is either 4 or 8 bytes. Lets assume 4 for now to keep it simple
        header = self.read(0, 8)
        if header[0] not in [0xE1, 0xE2] or header[1] & 0xFC != 0x40:
            if format:
                print(f"Formating tag. Old header: {header}")
                mem_size = (self.tag.block_size * self.tag.num_blocks) // 8
                header = [0xE1, 0x40, mem_size, 0x1, 0, 0, 0, 0]
                self.write(0, header[:4])
            else:
                raise Exception("Tag not formatted")

        # read TLV chunks until we find one with an Ndef message
        header_size = 4
        mem_size = header[2]
        if mem_size == 0:
            mem_size = (header[6] << 8) | header[7]
            header_size = 8
        mem_size *= 8

        self.tag.header_size = header_size
        self.tag.mem_size = mem_size

    def readNdef(self):
        if self.tag is None:
            raise Exception("No tag")

        if self.tag.header_size == 0:
            raise Exception("Tag not formatted")

        # read TLV records starting from offset and no more than mem_size
        offset = self.tag.header_size
        while offset < self.tag.mem_size:
            tlv = NfcTlv(self.read(offset, 4))
            offset += tlv.size

            if tlv.type == NfcTlv.TypeNdef:
                ndef_bytes = self.read(offset, tlv.length)
                return ndef.NdefMessage(ndef_bytes)

            if tlv.type == NfcTlv.TypeProprietary:
                offset += tlv.length
                continue

            if tlv.type == NfcTlv.TypeTerminator:
                break

        return None

    def writeNdef(self, ndefmsg):
        """Writes NdefMessage to tag, erasing all existing tag contents"""

        if self.tag is None:
            raise Exception("No tag")

        ndef_bytes = ndefmsg.to_buffer()

        # TODO: doesn't yet deal with messages > 255 bytes
        if len(ndef_bytes) > 255:
            raise NotImplemented("No support for long ndef messages")

        # format the tag if we need to
        if self.tag.header_size == 0:
            self.readHeader(format=True)

        buffer = []
        buffer.append(NfcTlv.TypeNdef)
        buffer.append(len(ndef_bytes))
        buffer.extend(ndef_bytes)
        buffer.append(NfcTlv.TypeTerminator)

        self.write(self.tag.header_size, buffer)

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
                    self.readHeader()

                    # TODO: new tag event
                    print("New tag", self.tag)

                    already_added = False
                    try:
                        ndefmsg = self.readNdef()
                        print("Ndef message:")
                        for r in ndefmsg.records:
                            if r.id == b"CT":
                                already_added = True
                            print(r.payload)
                    except:
                        ndefmsg = ndef.new_message(
                            (ndef.TNF_WELL_KNOWN, ndef.RTD_TEXT, "", b"\x02enboooom")
                        )

                    if not already_added:
                        print("Adding record")
                        r = ndef.NdefRecord()
                        r.tnf = ndef.TNF_WELL_KNOWN
                        r.set_type(ndef.RTD_TEXT)
                        r.set_id(b"CT")
                        r.set_payload(b"\x02enPlease work")

                        ndefmsg.records.append(r)
                        ndefmsg.fix()
                        self.writeNdef(ndefmsg)
                        print("Added")
