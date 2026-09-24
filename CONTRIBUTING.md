# Contributing

Use Python 3.11 or newer. Install FFmpeg and ExifTool, then:

```bash
python3 skills/rawly/scripts/bootstrap.py
skills/rawly/.venv/bin/python -m unittest discover -s tests -v
```

Runtime code lives in `skills/rawly/scripts/rawly_core`. Keep the skill portable:
relative resources, no service credentials, no machine-specific paths and no
required account. Tests should generate small synthetic media; do not commit user files.

For a bug, include the command, OS, `doctor` output and a minimal reproduction.
Remove personal paths and metadata before posting. See the issue template.

The D transform is intentionally fixed. Changes to resize filters, rounding, noise,
seed or post-processing change its output. Include an image-quality comparison and
reproducible measurements when proposing a new recipe. A successful detector result
on one image is not a general evaluation. Do not silently replace D with a new method.

For video changes, compare encoded packet hashes and metadata before/after.
For batch/installer changes, test failures and existing files as well as a clean run.
Keep English and Russian installation examples consistent.

Pull requests should state the problem, resulting behavior and checks performed.
Contributions are made under the repository's MIT license.
