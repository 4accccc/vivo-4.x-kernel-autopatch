"""Raw AArch64 kernel validation, version checks and file handling."""

import logging
import os
import re
from dataclasses import dataclass

from vmlinux_to_elf.core.elf_symbolizer import ElfSymbolizer

from errors import Unsupported, one, require

MAX_KERNEL_SIZE = 512 * 1024 * 1024


def validate_raw_kernel(raw: bytes) -> None:
    require(0 < len(raw) <= MAX_KERNEL_SIZE, "Input exceeds size limit")
    require(
        not raw.startswith(b"ANDROID!"),
        "Android boot images are not supported; provide an extracted kernel",
    )
    require(
        not raw.startswith(b"\x1f\x8b"),
        "gzip kernels are not supported; provide an uncompressed raw kernel",
    )
    require(
        len(raw) >= 64 and raw[56:60] == b"ARM\x64",
        "Expected an uncompressed AArch64 raw kernel",
    )


# Linux's NUL-terminated banner, not an arbitrary occurrence of "4.9" (which
# may instead be the compiler version). Some vendor images contain two exact
# copies of this banner. Conflicting banners are deliberately not guessed at.
BANNER = re.compile(
    rb"Linux version ([0-9]+)\.([0-9]+)\.([0-9]+)([^\s\x00]*) "
    rb"[\x20-\x7e\t\r\n]{1,2048}\x00"
)


@dataclass(frozen=True)
class KernelRelease:
    major: int
    minor: int
    patchlevel: int
    suffix: str
    banner: str
    offsets: tuple[int, ...]

    @classmethod
    def read(cls, raw):
        matches = list(BANNER.finditer(raw))
        require(matches, "Missing or malformed Linux version banner")
        banner = one({m.group(0) for m in matches}, "consistent Linux version banner")
        match = matches[0]
        suffix = match.group(4)
        require(all(33 <= c < 127 for c in suffix), "Invalid Linux release suffix")
        return cls(
            *(int(match.group(n)) for n in (1, 2, 3)),
            suffix.decode("ascii"),
            banner[:-1].decode("ascii").rstrip("\n"),
            tuple(m.start() for m in matches),
        )

    @property
    def name(self):
        return f"{self.major}.{self.minor}.{self.patchlevel}{self.suffix}"

    def require_supported(self):
        require(
            (self.major, self.minor) == (4, 9),
            f"Only Linux 4.9 kernels are supported; input is {self.name}",
        )

    def verify_symbol(self, program):
        # CONFIG_KALLSYMS_ALL=n (e.g. Y91i) omits data symbols. When present,
        # linux_banner must corroborate one of the identical raw banners.
        if "linux_banner" in program.symbols:
            offset = program.symbol("linux_banner") - program.base
            require(offset in self.offsets, "linux_banner symbol does not match the input release")

    def record(self):
        return dict(
            release=self.name,
            series=f"{self.major}.{self.minor}",
            banner=self.banner,
            raw_offsets=[hex(o) for o in self.offsets],
        )


def create_file(path, content):
    # Never overwrite inputs or previous artifacts. An interrupted write is
    # removed; only paths opened successfully by this call may be removed.
    with path.open("xb") as stream:
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise


def extract_symbols(raw, elf_path, log_path):
    # The dependency logs through the root logger; restore its state after extraction.
    logger = logging.getLogger()
    level = logger.level
    with log_path.open("w", encoding="utf-8") as log:
        handler = logging.StreamHandler(log)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            ElfSymbolizer(raw, output_file=str(elf_path), override_relative=False)
            require(elf_path.is_file(), "Symbol extraction did not produce an ELF")
        except Exception as error:
            logger.exception("Automatic kallsyms extraction failed")
            raise Unsupported(
                f"Automatic kallsyms extraction failed: {error} (see extraction log)"
            ) from error
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
            handler.close()
