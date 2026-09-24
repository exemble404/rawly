# Security

Please report vulnerabilities privately through GitHub's
[Report a vulnerability](https://github.com/exemble404/rawly/security/advisories/new) flow.
Do not include private media, credentials or unredacted metadata in public issues.

Rawly runs local image decoders, FFmpeg and ExifTool. Keep these tools updated and
use an isolated environment when processing files from untrusted sources.
The runtime does not upload files; dependency installation downloads Python packages.
