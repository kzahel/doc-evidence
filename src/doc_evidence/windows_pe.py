"""Small, dependency-free PE identity and import-table reader.

The desktop release audit needs to inspect final Windows program bytes without
depending on Visual Studio, LLVM, or a package installed on the build host.
This module intentionally reads only the bounded PE fields required for
architecture and dynamic-library closure validation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

PE_X86_64_MACHINE = 0x8664
_PE32_MAGIC = 0x10B
_PE32_PLUS_MAGIC = 0x20B
_IMPORT_DIRECTORY_INDEX = 1
_DELAY_IMPORT_DIRECTORY_INDEX = 13


@dataclass(frozen=True)
class PortableExecutable:
    """The native identity and directly imported DLLs of one PE file."""

    machine: int
    format: str
    imports: tuple[str, ...]
    delay_imports: tuple[str, ...]


@dataclass(frozen=True)
class _Section:
    virtual_address: int
    virtual_size: int
    raw_offset: int
    raw_size: int


class _PEReader:
    def __init__(self, data: bytes, *, description: str) -> None:
        self.data = data
        self.description = description

    def require(self, offset: int, size: int, purpose: str) -> None:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise RuntimeError(
                f"truncated PE {purpose} in {self.description}: "
                f"offset={offset}, size={size}, bytes={len(self.data)}"
            )

    def u16(self, offset: int, purpose: str) -> int:
        self.require(offset, 2, purpose)
        return struct.unpack_from("<H", self.data, offset)[0]

    def u32(self, offset: int, purpose: str) -> int:
        self.require(offset, 4, purpose)
        return struct.unpack_from("<I", self.data, offset)[0]

    def u64(self, offset: int, purpose: str) -> int:
        self.require(offset, 8, purpose)
        return struct.unpack_from("<Q", self.data, offset)[0]

    def c_string(self, offset: int, purpose: str) -> str:
        self.require(offset, 1, purpose)
        end = self.data.find(b"\0", offset)
        if end < 0:
            raise RuntimeError(f"unterminated PE {purpose} in {self.description}")
        try:
            value = self.data[offset:end].decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError(
                f"non-ASCII PE {purpose} in {self.description}"
            ) from error
        if not value:
            raise RuntimeError(f"empty PE {purpose} in {self.description}")
        return value


def _rva_to_offset(
    reader: _PEReader,
    rva: int,
    sections: tuple[_Section, ...],
    *,
    size_of_headers: int,
) -> int:
    if rva < size_of_headers:
        reader.require(rva, 1, "header RVA")
        return rva
    for section in sections:
        span = max(section.virtual_size, section.raw_size)
        if section.virtual_address <= rva < section.virtual_address + span:
            relative = rva - section.virtual_address
            if relative >= section.raw_size:
                raise RuntimeError(
                    f"PE RVA points outside raw section data in {reader.description}: "
                    f"0x{rva:x}"
                )
            offset = section.raw_offset + relative
            reader.require(offset, 1, "section RVA")
            return offset
    raise RuntimeError(
        f"PE RVA is outside declared sections in {reader.description}: 0x{rva:x}"
    )


def _directory(
    reader: _PEReader,
    *,
    data_directories_offset: int,
    directory_count: int,
    index: int,
) -> tuple[int, int]:
    if index >= directory_count:
        return (0, 0)
    offset = data_directories_offset + index * 8
    return (
        reader.u32(offset, f"data directory {index} RVA"),
        reader.u32(offset + 4, f"data directory {index} size"),
    )


def _import_names(
    reader: _PEReader,
    directory: tuple[int, int],
    sections: tuple[_Section, ...],
    *,
    size_of_headers: int,
) -> tuple[str, ...]:
    rva, size = directory
    if rva == 0 or size == 0:
        return ()
    offset = _rva_to_offset(reader, rva, sections, size_of_headers=size_of_headers)
    maximum = max(1, size // 20)
    names: list[str] = []
    for index in range(maximum):
        descriptor = offset + index * 20
        reader.require(descriptor, 20, "import descriptor")
        fields = struct.unpack_from("<IIIII", reader.data, descriptor)
        if not any(fields):
            break
        name_rva = fields[3]
        name_offset = _rva_to_offset(
            reader, name_rva, sections, size_of_headers=size_of_headers
        )
        names.append(reader.c_string(name_offset, "import DLL name"))
    else:
        raise RuntimeError(
            f"PE import descriptors lack a terminator in {reader.description}"
        )
    return tuple(dict.fromkeys(names))


def _delay_import_names(
    reader: _PEReader,
    directory: tuple[int, int],
    sections: tuple[_Section, ...],
    *,
    size_of_headers: int,
    image_base: int,
) -> tuple[str, ...]:
    rva, size = directory
    if rva == 0 or size == 0:
        return ()
    offset = _rva_to_offset(reader, rva, sections, size_of_headers=size_of_headers)
    maximum = max(1, size // 32)
    names: list[str] = []
    for index in range(maximum):
        descriptor = offset + index * 32
        reader.require(descriptor, 32, "delay-import descriptor")
        fields = struct.unpack_from("<IIIIIIII", reader.data, descriptor)
        if not any(fields):
            break
        attributes, encoded_name = fields[:2]
        name_rva = encoded_name if attributes & 1 else encoded_name - image_base
        if name_rva <= 0:
            raise RuntimeError(
                f"invalid PE delay-import DLL address in {reader.description}"
            )
        name_offset = _rva_to_offset(
            reader, name_rva, sections, size_of_headers=size_of_headers
        )
        names.append(reader.c_string(name_offset, "delay-import DLL name"))
    else:
        raise RuntimeError(
            f"PE delay-import descriptors lack a terminator in {reader.description}"
        )
    return tuple(dict.fromkeys(names))


def inspect_pe_bytes(
    data: bytes, *, description: str = "PE bytes"
) -> PortableExecutable:
    """Inspect architecture and imported DLL names from a PE byte string."""

    reader = _PEReader(data, description=description)
    reader.require(0, 64, "DOS header")
    if data[:2] != b"MZ":
        raise RuntimeError(f"Windows native file lacks a DOS header: {description}")
    pe_offset = reader.u32(0x3C, "PE header offset")
    reader.require(pe_offset, 24, "COFF header")
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise RuntimeError(f"Windows native file lacks a PE header: {description}")

    machine = reader.u16(pe_offset + 4, "COFF machine")
    section_count = reader.u16(pe_offset + 6, "COFF section count")
    optional_size = reader.u16(pe_offset + 20, "COFF optional-header size")
    optional = pe_offset + 24
    reader.require(optional, optional_size, "optional header")
    magic = reader.u16(optional, "optional-header magic")
    if magic == _PE32_PLUS_MAGIC:
        format_name = "PE32+"
        image_base = reader.u64(optional + 24, "image base")
        directory_count_offset = 108
        data_directories_offset = 112
    elif magic == _PE32_MAGIC:
        format_name = "PE32"
        image_base = reader.u32(optional + 28, "image base")
        directory_count_offset = 92
        data_directories_offset = 96
    else:
        raise RuntimeError(
            f"unsupported PE optional-header magic in {description}: 0x{magic:x}"
        )
    if optional_size < data_directories_offset:
        raise RuntimeError(f"truncated PE optional header in {description}")
    size_of_headers = reader.u32(optional + 60, "size of headers")
    directory_count = min(
        reader.u32(optional + directory_count_offset, "data-directory count"),
        (optional_size - data_directories_offset) // 8,
    )

    section_offset = optional + optional_size
    sections: list[_Section] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        reader.require(offset, 40, "section header")
        sections.append(
            _Section(
                virtual_size=reader.u32(offset + 8, "section virtual size"),
                virtual_address=reader.u32(offset + 12, "section virtual address"),
                raw_size=reader.u32(offset + 16, "section raw size"),
                raw_offset=reader.u32(offset + 20, "section raw offset"),
            )
        )
    section_tuple = tuple(sections)
    imports = _import_names(
        reader,
        _directory(
            reader,
            data_directories_offset=optional + data_directories_offset,
            directory_count=directory_count,
            index=_IMPORT_DIRECTORY_INDEX,
        ),
        section_tuple,
        size_of_headers=size_of_headers,
    )
    delay_imports = _delay_import_names(
        reader,
        _directory(
            reader,
            data_directories_offset=optional + data_directories_offset,
            directory_count=directory_count,
            index=_DELAY_IMPORT_DIRECTORY_INDEX,
        ),
        section_tuple,
        size_of_headers=size_of_headers,
        image_base=image_base,
    )
    return PortableExecutable(
        machine=machine,
        format=format_name,
        imports=imports,
        delay_imports=delay_imports,
    )


def inspect_pe(path: Path) -> PortableExecutable:
    """Inspect one PE file from disk."""

    return inspect_pe_bytes(path.read_bytes(), description=path.name)
