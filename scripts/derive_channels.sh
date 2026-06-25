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
#
# Prints the space-separated channel list on stdout.
#
# Follows the module-calver-release-channels kit. The channel NAMES are
# conventional, but the cascade property is mandatory: a more mature release
# must also advance every less-mature channel.

set -eu

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

printf '%s\n' "$channels"
