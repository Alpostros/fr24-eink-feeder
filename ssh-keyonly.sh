#!/bin/bash
[ "$(id -u)" -eq 0 ] || exec sudo -- bash "$0" "$@"
set -euo pipefail

TARGET=${SUDO_USER:?run this as your normal user, not as root}
HOME_DIR=$(getent passwd "$TARGET" | cut -d: -f6)
[ -s "$HOME_DIR/.ssh/authorized_keys" ] || { echo "no $HOME_DIR/.ssh/authorized_keys - refusing to disable password SSH"; exit 1; }

printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/00-keyonly.conf
sshd -t
systemctl reload ssh
sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication) '
