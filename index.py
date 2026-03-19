#!/usr/bin/env python3
"""
AWS IoT Thing Provisioner
Reads serial numbers (names) from a JSON file, creates AWS IoT Things,
generates certificates, and stores them in per-device folders.
"""

import json
import os
import sys
import argparse
import configparser
import boto3
from pathlib import Path


def load_aws_profiles() -> list[str]:
    """Load available AWS profiles from ~/.aws/credentials."""
    credentials_path = Path.home() / ".aws" / "credentials"
    if not credentials_path.exists():
        print("ERROR: ~/.aws/credentials file not found.")
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(credentials_path)
    profiles = config.sections()

    if not profiles:
        print("ERROR: No profiles found in ~/.aws/credentials.")
        sys.exit(1)

    return profiles


def select_profile(profiles: list[str]) -> str:
    """Prompt the user to select an AWS profile."""
    print("\nAvailable AWS profiles:")
    for i, profile in enumerate(profiles, start=1):
        print(f"  [{i}] {profile}")

    while True:
        choice = input("\nSelect a profile (number or name): ").strip()

        # Accept a number
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]
            else:
                print(f"  Invalid number. Choose between 1 and {len(profiles)}.")

        # Accept a profile name directly
        elif choice in profiles:
            return choice

        else:
            print("  Invalid selection. Try again.")


def load_serial_numbers(filepath: str) -> list[str]:
    """Load serial numbers from a JSON file."""
    path = Path(filepath)
    if not path.exists():
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)

    with open(path, "r") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("ERROR: JSON file must contain a top-level array of serial number strings.")
        sys.exit(1)

    serials = [s.strip() for s in data if isinstance(s, str) and s.strip()]
    if not serials:
        print("ERROR: No valid serial numbers found in the file.")
        sys.exit(1)

    return serials


def provision_thing(iot_client, serial: str, output_dir: Path) -> bool:
    """
    Create an IoT Thing, generate a certificate, attach a policy stub,
    and save all credential files into output_dir/<serial>/.

    Returns True on success, False on failure.
    """
    thing_dir = output_dir / serial
    thing_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Create the Thing ──────────────────────────────────────────────────
    try:
        iot_client.create_thing(thingName=serial)
        print(f"  ✓ Thing created: {serial}")
    except iot_client.exceptions.ResourceAlreadyExistsException:
        print(f"  ~ Thing already exists: {serial}")
    except Exception as e:
        print(f"  ✗ Failed to create thing '{serial}': {e}")
        return False

    # ── 2. Create keys and certificate ──────────────────────────────────────
    try:
        cert_response = iot_client.create_keys_and_certificate(setAsActive=True)
    except Exception as e:
        print(f"  ✗ Failed to create certificate for '{serial}': {e}")
        return False

    certificate_arn  = cert_response["certificateArn"]
    certificate_id   = cert_response["certificateId"]
    certificate_pem  = cert_response["certificatePem"]
    public_key_pem   = cert_response["keyPair"]["PublicKey"]
    private_key_pem  = cert_response["keyPair"]["PrivateKey"]

    print(f"  ✓ Certificate created: {certificate_id[:12]}…")

    # ── 3. Attach the certificate to the Thing ───────────────────────────────
    try:
        iot_client.attach_thing_principal(
            thingName=serial,
            principal=certificate_arn,
        )
        print(f"  ✓ Certificate attached to thing")
    except Exception as e:
        print(f"  ✗ Failed to attach certificate to '{serial}': {e}")
        # Non-fatal – files are still saved below

    # ── 4. Save credential files ─────────────────────────────────────────────
    files = {
        f"{serial}-certificate.pem.crt": certificate_pem,
        f"{serial}-public.pem.key":      public_key_pem,
        f"{serial}-private.pem.key":     private_key_pem,
    }

    for filename, content in files.items():
        filepath = thing_dir / filename
        filepath.write_text(content)
        # Restrict private key permissions
        if "private" in filename:
            filepath.chmod(0o600)

    # Save certificate metadata
    meta = {
        "thingName":      serial,
        "certificateArn": certificate_arn,
        "certificateId":  certificate_id,
    }
    (thing_dir / "certificate-meta.json").write_text(
        json.dumps(meta, indent=2)
    )

    print(f"  ✓ Files saved to: {thing_dir}/")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Provision AWS IoT Things from a JSON file of serial numbers."
    )
    parser.add_argument(
        "serials_file",
        help="Path to the JSON file containing serial numbers (e.g. serials.json)",
    )
    parser.add_argument(
        "--output-dir",
        default="iot_certs",
        help="Directory where per-device certificate folders are created (default: ./iot_certs)",
    )
    parser.add_argument(
        "--profile",
        help="AWS profile name to use (skips interactive selection)",
    )
    parser.add_argument(
        "--region",
        default="eu-central-1",
        help="AWS region (overrides profile default)",
    )
    args = parser.parse_args()

    # ── Profile selection ────────────────────────────────────────────────────
    profiles = load_aws_profiles()

    if args.profile:
        if args.profile not in profiles:
            print(f"ERROR: Profile '{args.profile}' not found in ~/.aws/credentials.")
            print(f"Available profiles: {', '.join(profiles)}")
            sys.exit(1)
        profile = args.profile
    else:
        profile = select_profile(profiles)

    print(f"\nUsing AWS profile: {profile}")

    # ── Load serial numbers ──────────────────────────────────────────────────
    serials = load_serial_numbers(args.serials_file)
    print(f"Found {len(serials)} serial number(s) to provision.")

    # ── Build boto3 session ──────────────────────────────────────────────────
    session_kwargs = {"profile_name": profile}
    if args.region:
        session_kwargs["region_name"] = args.region

    session    = boto3.Session(**session_kwargs)
    iot_client = session.client("iot")

    # ── Provision each device ────────────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    succeeded, failed = [], []

    for i, serial in enumerate(serials, start=1):
        print(f"\n[{i}/{len(serials)}] Provisioning: {serial}")
        ok = provision_thing(iot_client, serial, output_dir)
        (succeeded if ok else failed).append(serial)

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"Done.  Succeeded: {len(succeeded)}  |  Failed: {len(failed)}")
    if failed:
        print("\nFailed serial numbers:")
        for s in failed:
            print(f"  - {s}")
    print(f"\nCertificates stored in: {output_dir.resolve()}/")


if __name__ == "__main__":
    main()