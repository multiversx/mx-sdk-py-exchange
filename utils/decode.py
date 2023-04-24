from typing import Protocol, Any, List, Dict, Union


class ByteReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, size: int) -> bytes:
        assert self.offset + size <= len(self.data), "No remaining byte to read."
        result = self.data[self.offset:self.offset+size]
        self.offset += size
        return result

    def read_all(self) -> bytes:
        return self.read(len(self.data) - self.offset)

    def is_consumed(self) -> bool:
        return self.offset == len(self.data)


class Decoder(Protocol):
    def top_decode(self, b: ByteReader) -> Any:
        pass

    def nest_decode(self, b: ByteReader) -> Any:
        pass


class UintDecoder:
    byte_len: int

    def __init__(self, byte_len: int):
        self.byte_len = byte_len

    def top_decode(self, b: ByteReader) -> int:
        return int.from_bytes(b.read(self.byte_len), "big")

    def nest_decode(self, b: ByteReader) -> int:
        return self.top_decode(b)


class BigUintDecoder:
    def top_decode(self, b: ByteReader) -> int:
        return int.from_bytes(b.read_all(), "big")

    def nest_decode(self, b: ByteReader) -> int:
        length = int.from_bytes(b.read(4), "big")
        return int.from_bytes(b.read(length), "big")


class AddressDecoder:
    def top_decode(self, b: ByteReader) -> bytes:
        return b.read(32)

    def nest_decode(self, b: ByteReader) -> bytes:
        return self.top_decode(b)


class StringDecoder:
    def top_decode(self, b: ByteReader) -> str:
        return b.read_all().decode()

    def nest_decode(self, b: ByteReader) -> str:
        length = int.from_bytes(b.read(4), "big")
        return b.read(length).decode()


class BooleanDecoder:
    def top_decode(self, b: ByteReader) -> bool:
        return bool(int.from_bytes(b.read(1), "big"))

    def nest_decode(self, b: ByteReader) -> bool:
        return self.top_decode(b)


class OptionDecoder:
    decoder: Decoder

    def __init__(self, decoder: Decoder):
        self.decoder = decoder

    def top_decode(self, b: ByteReader) -> Any:
        if b.is_consumed():
            return None
        flag = b.read(1)
        if flag == b'\x01':
            return self.decoder.nest_decode(b)
        else:
            raise ValueError("Invalid Option flag")

    def nest_decode(self, b: ByteReader) -> Any:
        flag = b.read(1)
        if flag == b'\x01':
            return self.decoder.nest_decode(b)
        elif flag == b'\x00':
            return None
        else:
            raise ValueError("Invalid Option flag")


class TupleDecoder:
    decoders: Union[List[Decoder], Dict[str, Decoder]]

    def __init__(self, decoders: Union[List[Decoder], Dict[str, Decoder]]):
        self.decoders = decoders

    def top_decode(self, b: ByteReader) -> Union[List[Any], Dict[str, Any]]:
        if isinstance(self.decoders, list):
            result = []
            for decoder in self.decoders:
                result.append(decoder.nest_decode(b))
            return result
        elif isinstance(self.decoders, dict):
            result = {}
            for key, decoder in self.decoders.items():
                result[key] = decoder.nest_decode(b)
            return result
        else:
            raise ValueError("Invalid decoders.")

    def nest_decode(self, b: ByteReader) -> Dict[str, Any]:
        return self.top_decode(b)


class ListDecoder:
    decoder: Decoder

    def __init__(self, decoder: Decoder):
        self.decoder = decoder

    def top_decode(self, b: ByteReader) -> List[Any]:
        result = []
        while not b.is_consumed():
            result.append(self.decoder.nest_decode(b))
        return result

    def nest_decode(self, b: ByteReader) -> List[Any]:
        length = int.from_bytes(b.read(4), 'big')
        result = []
        for i in range(length):
            result.append(self.decoder.nest_decode(b))
        return result


class d:
    @classmethod
    def U8(cls):
        return UintDecoder(1)

    @classmethod
    def U16(cls):
        return UintDecoder(2)

    @classmethod
    def U32(cls):
        return UintDecoder(4)

    @classmethod
    def U64(cls):
        return UintDecoder(8)

    @classmethod
    def U(cls):
        return BigUintDecoder()

    @classmethod
    def Addr(cls):
        return AddressDecoder()

    @classmethod
    def Str(cls):
        return StringDecoder()

    @classmethod
    def Bool(cls):
        return BooleanDecoder()

    @classmethod
    def Option(cls, decoder: Decoder):
        return OptionDecoder(decoder)

    @classmethod
    def Tuple(cls, decoders: Dict[str, Decoder]):
        return TupleDecoder(decoders)

    @classmethod
    def List(cls, decoder: Decoder):
        return ListDecoder(decoder)


def top_dec_bytes(b: bytes, decoder: Decoder):
    return decoder.top_decode(ByteReader(b))


def top_dec_hex_str(hex_str: str, decoder: Decoder):
    return top_dec_bytes(bytes.fromhex(hex_str), decoder)
