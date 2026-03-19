# AWS IoT Thing Provisioner

A command-line Python script that reads serial numbers from a JSON file, creates AWS IoT Things, generates X.509 certificates for each device, and organises all credential files into per-device folders — ready to flash to your hardware.

---

## Prerequisites

- Python 3.8+
- AWS credentials configured in `~/.aws/credentials`
- An IAM user/role with the following permissions:
  - `iot:CreateThing`
  - `iot:CreateKeysAndCertificate`
  - `iot:AttachThingPrincipal`

Install the only Python dependency:

```bash
pip install boto3
```

---

## Input File Format

Create a JSON file containing a flat array of serial number strings:

```json
[
  "SER-D01-123-456-78",
  "SER-D01-321-654-98",
  "SER-D01-xxx-xxx-xx",
  "SER-D01-xxx-xxx-xx"
]
```

---

## Usage

### Basic — interactive profile selection

```bash
python index.py serials.json
```

The script will list all profiles found in `~/.aws/credentials` and prompt you to pick one.

### Pass the profile directly

```bash
python index.py serials.json --profile my-profile
```

### Specify a region and a custom output folder

```bash
python index.py serials.json --profile prod --region eu-central-1 --output-dir ./device_certs
```

### All options

| Argument       | Default         | Description                                      |
| -------------- | --------------- | ------------------------------------------------ |
| `serials_file` | _(required)_    | Path to the JSON file with serial numbers        |
| `--profile`    | interactive     | AWS profile name from `~/.aws/credentials`       |
| `--region`     | profile default | AWS region to use (e.g. `us-east-1`)             |
| `--output-dir` | `./iot_certs`   | Root folder where device sub-folders are created |

---

## Output Structure

For each serial number the script creates a sub-folder and writes four files:

```
iot_certs/
├── A12345678/
│   ├── A12345678-certificate.pem.crt   # Device certificate
│   ├── A12345678-public.pem.key         # Public key
│   ├── A12345678-private.pem.key        # Private key (chmod 600)
│   └── certificate-meta.json                     # ARN & certificate ID
├── B12345678/
│   └── ...
```

`certificate-meta.json` contains:

```json
{
  "thingName": "A12345678",
  "certificateArn": "arn:aws:iot:...",
  "certificateId": "abc123..."
}
```

---

## What the Script Does Per Device

1. **Creates an AWS IoT Thing** with the serial number as its name.
2. **Generates a key pair and X.509 certificate** (set to Active immediately).
3. **Attaches the certificate** to the Thing.
4. **Saves all credential files** locally into `<output-dir>/<serial>/`.

If a Thing already exists it is skipped, and a fresh certificate is still generated and attached.

---

## End-of-Run Summary

After processing all devices, the script prints a summary:

```
============================================================
Done.  Succeeded: 4  |  Failed: 0

Certificates stored in: /Users/you/project/iot_certs/
```

If any devices fail, their serial numbers are listed so you can re-run just those.

---

## Security Notes

- Private key files are saved with `chmod 600` (owner read/write only).
- Never commit the `iot_certs/` folder to source control — add it to `.gitignore`.
- Consider storing certificates in AWS Secrets Manager or a secrets vault for production use.

---

## Troubleshooting

| Problem                        | Solution                                                                |
| ------------------------------ | ----------------------------------------------------------------------- |
| `~/.aws/credentials not found` | Run `aws configure` or create the file manually                         |
| `ProfileNotFound`              | Check the profile name matches exactly (case-sensitive)                 |
| `AccessDeniedException`        | Ensure your IAM user/role has the required IoT permissions listed above |
| `EndpointResolutionError`      | Verify the `--region` flag matches where your IoT Core is set up        |
