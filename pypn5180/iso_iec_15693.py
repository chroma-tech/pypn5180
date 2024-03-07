from . import pypn5180
import binascii
import collections

"""
Implementation of ISO-IEC-15693 norm for PN5180 chipset
"""


class iso_iec_15693(object):

    CMD_CODE = {
        "INVENTORY": 0x01,
        "STAY_QUIET": 0x02,
        "READ_SINGLE_BLOCK": 0x20,
        "WRITE_SINGLE_BLOCK": 0x21,
        "LOCK_BLOCK": 0x22,
        "READ_MULTIPLE_BLOCK": 0x23,
        "WRITE_MULTIPLE_BLOCK": 0x24,
        "SELECT": 0x25,
        "RESET_READY": 0x26,
        "WRITE_AFI": 0x27,
        "LOCK_AFI": 0x28,
        "WRITE_DSFID": 0x29,
        "LOCK_DSFID": 0x2A,
        "GET_SYSTEM_INFORMATION": 0x2B,
        "GET_MULTIPLE_BLOCK_SECURITY_STATUS": 0x2C,
        "GET_SYSTEM_INFORMATION_EXT": 0x3B,
        "CUSTOM_READ_SINGLE": 0xC0,
        "CUSTOM_WRITE_SINGLE": 0xC1,
        "CUSTOM_LOCK_BLOCK": 0xC2,
        "CUSTOM_READ_MULTIPLE": 0xC3,
        "CUSTOM_WRITE_MULTIPLE": 0xC4,
    }

    ERROR_CODE = {
        0x00: "ERROR CODE ZERO",
        0x01: "The command is not supported, i.e. the request code is not recognised.",
        0x02: "The command is not recognised, for example: a format error occurred.",
        0x03: "The option is not supported.",
        0x0F: "Unknown error.",
        0x10: "The specified block is not available (doesn t exist).",
        0x11: "The specified block is already -locked and thus cannot be locked again",
        0x12: "The specified block is locked and its content cannot be changed.",
        0x13: "The specified block was not successfully programmed.",
        0x14: "The specified block was not successfully locked",
        0xA7: "CUSTOM ERROR 0xA7",
    }

    def __init__(self, pn5180):
        self.pn5180 = pn5180
        # print("PN5180 Self test:")
        # self.pn5180.selfTest()
        # print("\nConfiguring device for ISO IEC 15693")
        self.pn5180.configureIsoIec15693Mode()

        # Set default frame flags byte:
        # [Extract From ISO_IEC_15693]
        # Bit 1 Sub-carrier_flag  0 A single sub-carrier frequency shall be used by the VICC
        #                         1 Two sub-carriers shall be used by the VICC
        # Bit 2 Data_rate_flag    0 Low data rate shall be used
        #                         1 High data rate shall be used
        # Bit 3 Inventory_flag    0 Flags 5 to 8 meaning is according to table 4
        #                         1 Flags 5 to 8 meaning is according to table 5
        # Bit 4 Protocol          0 No protocol format extension
        #       Extension_flag    1 Protocol format is extended. Reserved for future use
        self.flags = 0x02

    """
    configureFlags(self, flags)
    Configure the flags byte to be used for next transmissions
    flags: 1 byte, following ISO_IEC_15693 requirements
    """

    def configureFlags(self, flags):
        self.flags = flags

    """
    getError(self, flags, data)
    analyse error code returned by the RFID chip
    """

    def getError(self, flags, data):

        if flags == 0xFF:
            return "Transaction ERROR: No Answer from tag"
        elif flags != 0:
            return "Transaction ERROR: %s" % self.ERROR_CODE.get(data[0], str(data[0]))
        return "Transaction OK"

    async def inventoryCmd(self):
        frame = []
        frame.insert(0, 0x26)  # flags for get inventory. get a single UID
        frame.insert(1, self.CMD_CODE["INVENTORY"])
        frame.insert(2, 0x00)  # mask length
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        if flags == 0 and len(data) < 9:
            flags = 0xFF
        if flags != 0:
            error = self.getError(flags, data)
            return None, error
        format, uid = data[0], data[1:9]
        return uid, ""

    async def stayQuietCmd(self, uid):
        frame = []
        frame.insert(0, self.flags | 0x20)
        frame.insert(1, self.CMD_CODE["STAY_QUIET"])
        frame.extend(uid)

    async def readSingleBlockCmd(self, blockNumber, uid=[]):
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["READ_SINGLE_BLOCK"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.append(blockNumber)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    def disconnect(self):
        self.pn5180.rfOff()

    async def writeSingleBlockCmd(self, blockNumber, data, uid=[]):
        #'21'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["WRITE_SINGLE_BLOCK"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.append(blockNumber)
        frame.extend(data)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def lockBlockCmd(self, numberOfBlocks, uid=[]):
        #'22'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["LOCK_BLOCK"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.append(numberOfBlocks)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def readMultipleBlocksCmd(self, firstBlockNumber, numberOfBlocks, uid=[]):
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["READ_MULTIPLE_BLOCK"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.append(firstBlockNumber)
        frame.append(numberOfBlocks)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def writeMultipleBlocksCmd(self, blockNumber, numBlocks, data, uid=[]):
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["WRITE_MULTIPLE_BLOCK"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.append(blockNumber)
        frame.append(numBlocks)
        frame.extend(data)

        print(
            f"WMB CMD. Offset block: {blockNumber} Num blocks: {numBlocks}. Data len: {len(data)}"
        )

        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        print(f"Return from write. Flags: {flags}. Data: {data}")
        error = self.getError(flags, data)
        return data, error

    async def selectCmd(self, uid):
        #'25'
        frame = []
        frame.insert(0, self.flags | 0x20)
        frame.insert(1, self.CMD_CODE["SELECT"])
        frame.extend(uid)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def resetToReadyCmd(self, uid=[]):
        #'26'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["RESET_READY"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def writeAfiCmd(self, afi, uid=[]):
        # 27'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["WRITE_AFI"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.extend(afi)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def lockAfiCmd(self, uid=[]):
        #'28'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["LOCK_AFI"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def writeDsfidCmd(self, dsfid, uid=[]):
        #'29'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["WRITE_DSFID"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.extend(dsfid)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def locckDsfidCmd(self, uid=[]):
        #'2A'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["LOCK_DSFID"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def getSystemInformationCmd(self, uid=[]):
        #'2B'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["GET_SYSTEM_INFORMATION"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        if flags != 0:
            error = self.getError(flags, data)
            return "", error

        dsfid = afi = num_blocks = block_size = 0
        info_flags = data[0]

        p = 9
        if info_flags & 0x1:
            dsfid = data[p]
            p += 1
        if info_flags & 0x2:
            afi = data[p]
            p += 1
        if info_flags & 0x4:
            num_blocks = data[p] + 1
            block_size = (data[p + 1] & 0x1F) + 1
            p += 2

        TagInfo = collections.namedtuple(
            "TagInfo", ["dsfid", "afi", "num_blocks", "block_size"]
        )
        return TagInfo(dsfid, afi, num_blocks, block_size), ""

    async def getSystemInformationExtCmd(self, uid=[]):
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["GET_SYSTEM_INFORMATION_EXT"])
        frame.insert(2, 0x1F)  # info flags
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def getMultipleBlockSecurityStatusCmd(
        self, firstBlockNumber, numberOfBlocks, uid=[]
    ):
        #'2C'
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["GET_MULTIPLE_BLOCK_SECURITY_STATUS"])
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.append(firstBlockNumber)
        frame.append(numberOfBlocks)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    async def customCommand(self, cmdCode, mfCode, data):
        # 'A0' - 'DF' Custom IC Mfg dependent
        # 'E0' - 'FF' Proprietary IC Mfg dependent
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, cmdCode)
        frame.insert(2, mfCode)
        if data is not []:
            frame[0] |= 0x20
            frame.extend(data)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    """
    Note: firstBlockNumber: 2 bytes, LSB first
    """

    async def customReadSinlge(self, mfCode, firstBlockNumber, uid=[]):
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, self.CMD_CODE["CUSTOM_READ_SINGLE"])
        frame.insert(2, mfCode)
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        if len(firstBlockNumber) == 1:
            frame.extend(0)
        frame.extend(firstBlockNumber)
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error

    """
    Note: firstBlockNumber: 2 bytes, LSB first
    """

    def customWriteSinlge(self, cmdCode, mfCode, firstBlockNumber, data, uid=[]):
        pass

    async def rfuCommand(self, cmdCode, data, uid=[]):
        frame = []
        frame.insert(0, self.flags)
        frame.insert(1, cmdCode)
        if uid is not []:
            frame[0] |= 0x20
            frame.extend(uid)
        frame.extend(map(ord, data))
        flags, data = await self.pn5180.transactionIsoIec15693(frame)
        error = self.getError(flags, data)
        return data, error
