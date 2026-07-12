# Releasing

Quartermaster releases are **CalVer-tag-driven** and follow **cascading
channel pointers**, per the `module-calver-release-channels` kit. Pushing a
version tag publishes a container image to GHCR
(`ghcr.io/exhuma/quartermaster`) — there is no `latest` tag.

## Cut a release

Push a tag in the form `vYYYY.M.D[-alpha.N | -beta.N | -rc.N]`:

```bash
git tag -a v2026.6.25-beta.1 -m "Quartermaster v2026.6.25-beta.1"
git push origin v2026.6.25-beta.1
```

The [`build-push`](https://github.com/exhuma/quartermaster/blob/main/.github/workflows/build-push.yml) workflow runs the tests,
then builds and publishes:

- the **immutable full version**, e.g. `:2026.6.25-beta.1`, and
- the **moving channel pointer(s)** that release advances.

## Channels (cascade by maturity)

`stable ⊃ beta ⊃ alpha` — a more mature release also advances every
less-mature channel, so each channel always points at the newest build that
is *at least* that mature. Derived by
[`scripts/derive_channels.sh`](https://github.com/exhuma/quartermaster/blob/main/scripts/derive_channels.sh):

| Tag                    | Channel tags moved          |
|------------------------|-----------------------------|
| `vYYYY.M.D-alpha.N`    | `alpha`                     |
| `vYYYY.M.D-beta.N`     | `beta`, `alpha`             |
| `vYYYY.M.D-rc.N`       | `rc`                        |
| `vYYYY.M.D` (no suffix)| `stable`, `beta`, `alpha`   |

So operators can track a channel and pull the latest build at that maturity:

```bash
docker pull ghcr.io/exhuma/quartermaster:stable   # newest stable
docker pull ghcr.io/exhuma/quartermaster:beta     # newest beta-or-better
docker pull ghcr.io/exhuma/quartermaster:alpha    # newest alpha-or-better
```

…or pin the immutable full version for reproducibility:

```bash
docker pull ghcr.io/exhuma/quartermaster:2026.6.25
```

## Why no `latest`

CalVer has no semantic ordering for a tool to anchor `latest` on, so the
workflow sets `flavor: latest=false`. The channel pointers are the moving
references instead. (A `:latest` published before this scheme existed is now
stale and can be deleted from the GHCR package.)

## Branch builds

Pushes to `main` run the full test suite and validate the Docker build, but
**publish nothing** — only tag pushes produce images.

## Not adopted (yet)

The kit also ships a cross-manifest version-sync guard (fail the release
unless every manifest's version equals the tag). Quartermaster's
`pyproject.toml` / `package.json` versions are intentionally decoupled from
the CalVer image tags (the packages aren't published), so that guard is not
wired in. Add it if you start coupling those versions to releases.
