#!/usr/bin/env python3
"""
CCM Tool v0.58.2 — Release Package Creator (Phase 4)

Bundles all project files into a release ZIP with verification.

Usage:
  python create_release_package.py --version 0.58 --output-dir releases/

Output:
  CCM_Tool_v0.58.zip (verified, checksummed)
  CCM_Tool_v0.58.sha256 (integrity checksum)
  release_manifest_v0.58.txt (file listing)
"""

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set


class ReleasePackager:
    """Creates and verifies release packages."""

    # Files/directories to include in release
    INCLUDE_PATTERNS = {
        "*.py",  # Python modules
        "*.pyt",  # ArcGIS toolbox
        "*.pyt.xml",  # Toolbox metadata
        "*.docx",  # User manual
        "*.md",  # Markdown documentation
        "*.html",  # HTML documentation
        "*.txt",  # Text files
        "*.bat",  # Batch scripts
        "*.sh",  # Shell scripts
        "LICENSE",  # License file
    }

    # Directories to include
    INCLUDE_DIRS = {
        "tests",
        "examples",
        "docs",
        "verification_artifacts",
        "verification_logs",
    }

    # Files/patterns to exclude
    EXCLUDE_PATTERNS = {
        "__pycache__",
        ".git",
        ".pytest_cache",
        "*.pyc",
        ".DS_Store",
        "*.tmp",
        ".backup",
        "~*",
    }

    def __init__(self, version: str, project_root: Path = None, output_dir: Path = None):
        self.version = version
        self.project_root = project_root or Path(__file__).parent
        self.output_dir = output_dir or (self.project_root / "releases")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.release_name = f"CCM_Tool_v{version}"
        self.zip_path = self.output_dir / f"{self.release_name}.zip"
        self.sha256_path = self.output_dir / f"{self.release_name}.sha256"
        self.manifest_path = self.output_dir / f"release_manifest_v{version}.txt"

        self.files_included = []
        self.files_excluded = []

    def should_include_file(self, file_path: Path) -> bool:
        """Determine if file should be included in release."""
        # Check exclude patterns first
        for pattern in self.EXCLUDE_PATTERNS:
            if pattern.startswith("*"):
                if file_path.name.endswith(pattern[1:]):
                    return False
            else:
                if pattern in str(file_path):
                    return False

        # Check if it's a top-level root file
        if file_path.parent == self.project_root:
            for include_pattern in self.INCLUDE_PATTERNS:
                if file_path.match(include_pattern):
                    return True

        # Check if in included directories
        for include_dir in self.INCLUDE_DIRS:
            if include_dir in file_path.parts:
                return True

        return False

    def collect_files(self) -> List[Path]:
        """Recursively collect files for release."""
        files = []

        for file_path in self.project_root.rglob("*"):
            if file_path.is_file() and self.should_include_file(file_path):
                files.append(file_path)

        # Verify minimum file count
        if len(files) < 20:
            raise ValueError(
                f"Too few files collected ({len(files)}). "
                "Likely pattern matching issue."
            )

        return sorted(files)

    def create_zip(self, files: List[Path]) -> None:
        """Create release ZIP file."""
        print(f"\nCreating ZIP: {self.zip_path.name}")

        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in files:
                # Archive path: strip project root, prefix with release name
                archive_path = f"{self.release_name}/{file_path.relative_to(self.project_root)}"

                try:
                    zf.write(file_path, arcname=archive_path)
                    self.files_included.append(archive_path)
                except Exception as e:
                    print(f"  ⚠ Could not add {file_path}: {e}")
                    self.files_excluded.append((file_path, str(e)))

        zip_size = self.zip_path.stat().st_size / (1024 * 1024)  # Convert to MB
        print(f"✓ ZIP created: {self.zip_path.name} ({zip_size:.1f} MB)")

    def compute_checksum(self) -> str:
        """Compute SHA256 checksum of ZIP."""
        print(f"\nComputing SHA256 checksum...")

        sha256 = hashlib.sha256()
        with open(self.zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)

        checksum = sha256.hexdigest()

        # Write checksum file
        self.sha256_path.write_text(f"{checksum}  {self.zip_path.name}\n")
        print(f"✓ Checksum: {checksum[:16]}...")
        print(f"✓ Checksum file: {self.sha256_path.name}")

        return checksum

    def create_manifest(self) -> None:
        """Create release manifest listing."""
        print(f"\nCreating manifest...")

        manifest_lines = [
            "=" * 70,
            f"CCM Tool v{self.version} — Release Manifest",
            "=" * 70,
            "",
            f"Release Date: {datetime.now().isoformat()}",
            f"Release Name: {self.release_name}",
            f"ZIP File: {self.zip_path.name}",
            f"ZIP Size: {self.zip_path.stat().st_size / (1024*1024):.1f} MB",
            "",
            "Files Included",
            "-" * 70,
        ]

        manifest_lines.extend(sorted(self.files_included))

        manifest_lines.extend([
            "",
            "=" * 70,
            f"Total: {len(self.files_included)} files",
            "=" * 70,
        ])

        if self.files_excluded:
            manifest_lines.extend([
                "",
                "Files Excluded (reason)",
                "-" * 70,
            ])
            for file_path, reason in self.files_excluded:
                manifest_lines.append(f"{file_path} ({reason})")

        self.manifest_path.write_text("\n".join(manifest_lines))
        print(f"✓ Manifest: {self.manifest_path.name} ({len(self.files_included)} files)")

    def verify_zip(self) -> bool:
        """Verify ZIP integrity."""
        print(f"\nVerifying ZIP integrity...")

        try:
            with zipfile.ZipFile(self.zip_path, "r") as zf:
                bad_file = zf.testzip()
                if bad_file:
                    print(f"✗ ZIP validation failed: {bad_file}")
                    return False

                file_count = len(zf.namelist())
                print(f"✓ ZIP valid ({file_count} entries)")
                return True

        except Exception as e:
            print(f"✗ ZIP verification failed: {e}")
            return False

    def verify_manifest(self) -> bool:
        """Verify manifest file contents."""
        print(f"\nVerifying manifest...")

        if not self.manifest_path.exists():
            print(f"✗ Manifest file not found")
            return False

        content = self.manifest_path.read_text()
        line_count = len(content.split("\n"))

        if line_count < 10:
            print(f"✗ Manifest appears empty or incomplete")
            return False

        print(f"✓ Manifest valid ({line_count} lines)")
        return True

    def verify_checksum(self) -> bool:
        """Verify checksum file contents."""
        print(f"\nVerifying checksum...")

        if not self.sha256_path.exists():
            print(f"✗ Checksum file not found")
            return False

        content = self.sha256_path.read_text().strip()
        parts = content.split()

        if len(parts) < 2:
            print(f"✗ Checksum file format invalid")
            return False

        checksum, filename = parts[0], parts[1]

        if not checksum or len(checksum) != 64:
            print(f"✗ Checksum format invalid")
            return False

        print(f"✓ Checksum valid: {checksum[:16]}...")
        return True

    def run(self) -> bool:
        """Execute full release packaging."""
        print("\n" + "=" * 70)
        print("CCM Tool Release Package Creator")
        print("=" * 70)
        print(f"Version: {self.version}")
        print(f"Project: {self.project_root}")
        print(f"Output:  {self.output_dir}")

        try:
            # Collect files
            print(f"\n--- Collecting Files ---")
            files = self.collect_files()
            print(f"✓ Found {len(files)} files to package")

            # Create ZIP
            print(f"\n--- Creating ZIP ---")
            self.create_zip(files)

            # Verify ZIP
            if not self.verify_zip():
                print("✗ ZIP verification failed")
                return False

            # Compute checksum
            print(f"\n--- Computing Checksum ---")
            checksum = self.compute_checksum()

            # Create manifest
            print(f"\n--- Creating Manifest ---")
            self.create_manifest()

            # Verify all outputs
            print(f"\n--- Verifying Release Package ---")
            checks = [
                ("Checksum file", self.verify_checksum()),
                ("Manifest file", self.verify_manifest()),
            ]

            all_ok = all(ok for _, ok in checks)

            if not all_ok:
                print("✗ Some verification checks failed")
                return False

            # Summary
            print("\n" + "=" * 70)
            print("✓ Release Package Complete")
            print("=" * 70)
            print(f"\nFiles created in {self.output_dir}:")
            print(f"  • {self.zip_path.name}")
            print(f"  • {self.sha256_path.name}")
            print(f"  • {self.manifest_path.name}")
            print(f"\nNext steps:")
            print(f"  1. Verify release on test machine")
            print(f"  2. Tag release in Git: git tag -a v{self.version} -m 'v{self.version} release'")
            print(f"  3. Push tags: git push origin --tags")
            print(f"  4. Create GitHub release with ZIP artifact")
            print("=" * 70 + "\n")

            return True

        except Exception as e:
            print(f"\n✗ Release packaging failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """Parse arguments and run release packager."""
    parser = argparse.ArgumentParser(
        description="Create CCM Tool release package"
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Release version (e.g., 0.58)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for release files (default: releases/)"
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Project root directory (default: script directory)"
    )

    args = parser.parse_args()

    project_root = Path(args.project_root) if args.project_root else Path(__file__).parent
    output_dir = Path(args.output_dir) if args.output_dir else project_root / "releases"

    packager = ReleasePackager(args.version, project_root, output_dir)

    return packager.run()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

# <<< END OF FILE >>>
