#!/bin/sh
# derive_channels.sh — map a CalVer tag to the moving channel pointers it advances.
#
# Channels CASCADE BY MATURITY (stable ⊃ beta ⊃ alpha): a release advances its
# own channel and every LESS-mature one. There is no unconditional "latest".
#
#   tag class        channels advanced
#   --------------   -----------------------------
#   *-alpha.N        alpha
#   *-beta.N         beta alpha
#   *-rc.N           rc
#   <no pre-release> stable beta alpha   (a final/stable release)
#
# USAGE
#   GITHUB_REF_NAME=v2026.6.25-beta.2 sh scripts/derive_channels.sh
#   # or pass the tag explicitly:
#   sh scripts/derive_channels.sh v2026.6.25
#   # print only the single most-mature ("primary") channel this build advances:
#   sh scripts/derive_channels.sh --primary v2026.6.25-beta.2   # -> beta
#
# Prints the space-separated channel list on stdout (or just the primary
# channel with --primary). The cascade is emitted most-mature-first, so the
# primary channel is always the first token (alpha->alpha, beta->beta,
# rc->rc, stable->stable).
#
# Follows the module-calver-release-channels kit. The channel NAMES are
# conventional, but the cascade property is mandatory: a more mature release
# must also advance every less-mature channel.

set -eu

primary_only=false
if [ "${1:-}" = "--primary" ]; then
    primary_only=true
    shift
fi

raw="${1:-${GITHUB_REF_NAME:-}}"
if [ -z "$raw" ]; then
    echo "::error::no tag supplied (pass as arg or set GITHUB_REF_NAME)" >&2
    exit 2
fi
ref="${raw#v}"

case "$ref" in
    *-alpha.*) channels="alpha" ;;
    *-beta.*)  channels="beta alpha" ;;
    *-rc.*)    channels="rc" ;;
    *)         channels="stable beta alpha" ;;   # no pre-release == stable
esac

if $primary_only; then
    # The primary channel is the most-mature one, always the first token.
    set -- $channels
    printf '%s\n' "$1"
else
    printf '%s\n' "$channels"
fi
