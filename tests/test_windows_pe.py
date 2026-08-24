from __future__ import annotations

import struct
import unittest

from doc_evidence.windows_pe import PE_X86_64_MACHINE, inspect_pe_bytes


def _synthetic_pe(*, pe32: bool = False, terminated: bool = True) -> bytes:
    pe_offset = 0x80
    optional_size = 0xE0 if pe32 else 0xF0
    section_offset = pe_offset + 24 + optional_size
    raw_offset = 0x200
    data = bytearray(0x600)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<HH", data, pe_offset + 4, PE_X86_64_MACHINE, 1)
    struct.pack_into("<H", data, pe_offset + 20, optional_size)
    optional = pe_offset + 24
    if pe32:
        struct.pack_into("<H", data, optional, 0x10B)
        struct.pack_into("<I", data, optional + 28, 0x400000)
        count_offset = 92
        directories_offset = 96
    else:
        struct.pack_into("<H", data, optional, 0x20B)
        struct.pack_into("<Q", data, optional + 24, 0x140000000)
        count_offset = 108
        directories_offset = 112
    struct.pack_into("<I", data, optional + 60, raw_offset)
    struct.pack_into("<I", data, optional + count_offset, 16)
    import_rva = 0x1000
    delay_rva = 0x1080
    struct.pack_into("<II", data, optional + directories_offset + 8, import_rva, 40)
    struct.pack_into("<II", data, optional + directories_offset + 13 * 8, delay_rva, 64)
    data[section_offset : section_offset + 8] = b".rdata\0\0"
    struct.pack_into(
        "<IIII",
        data,
        section_offset + 8,
        0x400,
        0x1000,
        0x400,
        raw_offset,
    )

    name_rva = 0x1100
    struct.pack_into("<IIIII", data, raw_offset, 1, 0, 0, name_rva, 1)
    if terminated:
        struct.pack_into("<IIIII", data, raw_offset + 20, 0, 0, 0, 0, 0)
    else:
        struct.pack_into("<IIIII", data, raw_offset + 20, 1, 0, 0, name_rva, 1)
    data[raw_offset + 0x100 : raw_offset + 0x10D] = b"KERNEL32.dll\0"

    delay_name_rva = 0x1120
    struct.pack_into(
        "<IIIIIIII",
        data,
        raw_offset + 0x80,
        1,
        delay_name_rva,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    data[raw_offset + 0xA0 : raw_offset + 0xC0] = bytes(32)
    data[raw_offset + 0x120 : raw_offset + 0x12C] = b"USER32.dll\0"
    return bytes(data)


class WindowsPETest(unittest.TestCase):
    def test_reads_x64_import_and_delay_import_tables(self) -> None:
        result = inspect_pe_bytes(_synthetic_pe(), description="fixture.exe")

        self.assertEqual(result.machine, PE_X86_64_MACHINE)
        self.assertEqual(result.format, "PE32+")
        self.assertEqual(result.imports, ("KERNEL32.dll",))
        self.assertEqual(result.delay_imports, ("USER32.dll",))

    def test_reads_pe32_layout_without_claiming_x64_format(self) -> None:
        result = inspect_pe_bytes(_synthetic_pe(pe32=True))

        self.assertEqual(result.machine, PE_X86_64_MACHINE)
        self.assertEqual(result.format, "PE32")

    def test_rejects_non_pe_and_unterminated_import_table(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "DOS header"):
            inspect_pe_bytes(bytes(64), description="foreign.bin")
        with self.assertRaisesRegex(RuntimeError, "lack a terminator"):
            inspect_pe_bytes(_synthetic_pe(terminated=False))
