#!/usr/bin/env python3
"""Patch vivo Linux 4.9 raw kernels and publish analysis reports."""

import argparse
import hashlib
import json
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from elftools.common.exceptions import ELFError

from analyzer import Analyzer
from errors import RuleFailure, Unsupported, require
from kernel import MAX_KERNEL_SIZE, KernelRelease, create_file, extract_symbols, validate_raw_kernel
from patch import apply
from program import Program
from verify import verify


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Patch vivo Linux 4.9 only: uncompressed raw kernel in / raw kernel out.",
        epilog="Accepts only uncompressed AArch64 raw kernels.",
    )
    parser.add_argument("input", type=Path, help="uncompressed 4.9 AArch64 raw kernel")
    parser.add_argument("output", nargs="?", type=Path, help="new uncompressed raw kernel output")
    parser.add_argument(
        "--elf", type=Path, help="matching symbolized ELF; otherwise extract kallsyms automatically"
    )
    parser.add_argument("--report", type=Path, help="new JSON report (default: OUTPUT.json)")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--patches", help="patch numbers, e.g. 1234, 12346 or 1,2,3,4 (default: 123456)"
    )
    selection.add_argument("--magisk-version", type=int, help="Magisk major version, e.g. 24 or 25")
    parser.add_argument("--bits", type=int, choices=(32, 64), help="Magisk userspace bitness")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="4.9 rule diagnosis only; requires --report and cannot write an image",
    )
    args = parser.parse_args(argv)
    require(
        (args.magisk_version is None) == (args.bits is None),
        "--magisk-version and --bits must be supplied together",
    )
    numbers = "123456" if args.patches is None else args.patches.replace(",", "")
    if args.magisk_version is not None:
        require(args.magisk_version > 0, "Magisk version must be a positive major version")
        require(
            args.bits != 64 or args.magisk_version >= 24,
            "No selection table for 64-bit Magisk < 24; use --patches explicitly",
        )
        numbers = "1234"
        if args.magisk_version >= 25:
            numbers += "5"
        if args.bits == 64:
            numbers += "6"
    require(
        bool(numbers) and set(numbers) <= set("123456") and len(set(numbers)) == len(numbers),
        "--patches must contain unique patch numbers from 1 to 6",
    )
    args.patches = {f"P{number}" for number in numbers}
    require(not (args.diagnose and args.output), "--diagnose cannot be combined with OUTPUT")
    if args.report is None:
        require(args.output is not None, "Analysis without an output requires --report")
        args.report = args.output.with_name(args.output.name + ".json")
    paths = [args.input, args.elf, args.report, args.output]
    present = [p.resolve() for p in paths if p is not None]
    require(
        len(present) == len(set(present)), "Input, ELF, report and output must be distinct paths"
    )
    for path in (args.report, args.output):
        if path:
            require(not path.exists(), "Refusing to overwrite " + str(path))
            require(path.parent.is_dir(), "Output parent directory must exist: " + str(path.parent))
    return args


def analyze_kernel(args, raw, report, log):
    with tempfile.TemporaryDirectory(prefix="vivo-semantic-") as directory:
        elf = args.elf
        if elf is None:
            log("Extracting embedded kallsyms (no address override)")
            root = Path(directory)
            elf, extraction_log = root / "symbols.elf", root / "extraction.log"
            try:
                extract_symbols(raw, elf, extraction_log)
            finally:
                report["symbol_extraction_log"] = (
                    extraction_log.read_text(errors="replace") if extraction_log.exists() else ""
                )
        program = Program.from_elf(raw, elf)
        analyzer = Analyzer(program, log)
        if args.diagnose:
            groups = analyzer.diagnose(args.patches)
            report.update(
                groups=groups,
                status="diagnosed",
                all_groups_identified=all(
                    group["status"] == "identified" for group in groups.values()
                ),
            )
            return None

        patches = analyzer.analyze(args.patches)
        patched = apply(raw, program.base, patches, args.patches)
        report.update(
            patches=[patch.record(program.base) for patch in patches],
            raw_output_sha256=hashlib.sha256(patched).hexdigest(),
            changed_kernel_bytes=sum(a != b for a, b in zip(raw, patched)),
            raw_size=len(raw),
            base_address=hex(program.base),
        )
        report["verification"] = verify(program, patches, patched, log)
        if args.output:
            validate_raw_kernel(patched)
            report.update(
                status="patched",
                output=str(args.output.resolve()),
                output_sha256=report["raw_output_sha256"],
                output_kind="kernel",
            )
            return patched
        report["status"] = "analyzed"
        return None


def main(argv=None):
    args = parse_args(argv)

    def log(message):
        print(message, file=sys.stderr)

    report = dict(
        schema_version=1,
        supported_kernel_series="4.9",
        status="unsupported",
        input=str(args.input.resolve()),
        selected_patches=sorted(args.patches),
        versions={
            name: version(name)
            for name in ("capstone", "networkx", "pyelftools", "vmlinux-to-elf", "unicorn")
        },
        python=sys.version.split()[0],
    )
    output = None
    try:
        require(args.input.stat().st_size <= MAX_KERNEL_SIZE, "Input exceeds size limit")
        raw = args.input.read_bytes()
        validate_raw_kernel(raw)
        fingerprint = hashlib.sha256(raw).hexdigest()
        report.update(
            input_sha256=fingerprint,
            raw_input_sha256=fingerprint,
            image=dict(kind="kernel", container="kernel"),
            input_kind="kernel",
        )
        release = KernelRelease.read(raw)
        report["kernel_version"] = release.record()
        release.require_supported()
        output = analyze_kernel(args, raw, report, log)
    except RuleFailure as error:
        report.update(error.record())
        error.emit(log)
    except (OSError, ValueError, ELFError) as error:
        report["error"] = str(error)
        log("REFUSED: " + str(error))
    except Exception as error:
        report.update(status="error", error=f"{type(error).__name__}: {error}")
        log("ANALYZER ERROR: " + report["error"])

    if output is not None and report["status"] == "patched":
        create_file(args.output, output)
    create_file(args.report, (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode())
    summary = {
        key: report[key]
        for key in ("status", "error", "failed_rules", "raw_output_sha256", "changed_kernel_bytes")
        if key in report
    }
    print(json.dumps(summary))
    return (
        0
        if report["status"] in ("patched", "analyzed") or report.get("all_groups_identified")
        else 2
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Unsupported, OSError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
