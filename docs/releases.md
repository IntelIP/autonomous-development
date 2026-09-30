# Source releases

Prereleases distribute source only, with a manifest and SHA-256 checksum. Coding-agent CLIs, images, model accounts, and the external lead service are installed separately under their own terms. A source release does not establish fresh-host support or unattended reliability.

From a clean checkout:

```sh
python3 scripts/package-alpha.py --stack-root "$PWD" --version 0.1.0-alpha.3 --output /tmp/autonomous-development-0.1.0-alpha.3.tar.gz
shasum -a 256 /tmp/autonomous-development-0.1.0-alpha.3.tar.gz
```

The manifest binds source revisions and each distributed file. Extract to a new directory and verify the manifest before running. See the quickstart and runtime evidence for the actual validation scope.
