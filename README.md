# llm-rosetta-shim-opendesign

Open Design Cloud as a provider for
[llm-rosetta](https://github.com/Oaklight/llm-rosetta), delivered as a **plugin
package** rather than as a built-in shim.

Open Design Cloud serves its models on a single HTTPS gateway. The three chat
formats this package exposes all talk to that gateway; only the authentication
header and the wire body differ.

## Install

Declare the preset in the gateway config:

```jsonc
{
  "shims": { "presets": ["opendesign"] }
}
```

The preset resolves to this repository and its bundled provider directory
through llm-rosetta's catalogue. The equivalent explicit entry is:

```jsonc
{
  "shims": {
    "remotes": [
      {
        "url": "https://github.com/Oaklight/llm-rosetta-shim-opendesign",
        "path": "src/llm_rosetta_shim_opendesign/providers"
      }
    ]
  }
}
```

Installing the distribution directly also works; llm-rosetta discovers the
`llm_rosetta.shim_providers` entry point on its own:

```bash
pip install llm-rosetta-shim-opendesign
```

## Configure a provider

```jsonc
{
  "shims": { "presets": ["opendesign"] },
  "providers": {
    "opendesign": {
      "type": "opendesign--chat_completions",
      "api_key": "${OPENDESIGN_API_KEY}"
    }
  },
  "models": {
    "deepseek-v4.1-flash": { "provider": "opendesign" }
  }
}
```

The vendor manifest supplies the base URL, the `OPENDESIGN_API_KEY` environment
default, and the model-list URL. A provider entry may still override any of
them.

## The shims

| Shim | Format | Endpoint | Credential header |
|:---|:---|:---|:---|
| `opendesign--chat_completions` | `chat_completions` | `/v1/chat/completions` | `Authorization: Bearer sk-amr-…` |
| `opendesign--open_responses` | `open_responses` | `/v1/responses` | `Authorization: Bearer sk-amr-…` |
| `opendesign--messages` | `messages` | `/v1/messages` | `x-api-key: sk-amr-…` + `anthropic-version: 2023-06-01` |

Base URL: `https://amr-link.open-design.ai/v1`.
Model listing: `https://amr-link.open-design.ai/v1/models`.

The runtime API key (`sk-amr-…`) is the credential for every model request.
Open Design serves every model on all three APIs, so pick the format the
client speaks; the shim signs the request the way that endpoint expects.

## Quota

This release does **not** read the Coding Plan allowance. Open Design reports
that allowance on a separate control plane that does not accept a runtime API
key. Quota support needs a second credential and is tracked as a follow-up.

The gateway therefore reports the provider's quota as unsupported, and the
provider hint says the same.

## Archive and mirror

Every release publishes one archive of the bundled shims, so a gateway can load
them from a host other than GitHub. `main` never carries it: `dist/` is build
output and is in `.gitignore`.

- `v<version>/opendesign.tar.gz` and `v<version>/opendesign.tar.gz.sha256` live
  on the orphan `dist` branch.
- The same bytes are attached to the GitHub Release, with the digest in its
  notes.

The archive's root is `providers/`, the layout the package ships under
`src/llm_rosetta_shim_opendesign/providers`, so a gateway source declares
`path: "providers"`:

```jsonc
{
  "shims": {
    "remotes": [
      {
        "url": "https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-opendesign@dist/v<version>/opendesign.tar.gz",
        "path": "providers",
        "archive": "tar.gz",
        "sha256": "<digest from v<version>/opendesign.tar.gz.sha256>"
      }
    ]
  }
}
```

## Live behavior

The endpoint, header split, and model-list path follow the documented Open
Design cloud surface. They have not been exercised against a live account in
this repository's tests; the test suite covers package registration and the
bundled manifests only.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e . pytest pyyaml
pytest tests -q
python scripts/build_shim_archive.py
```
