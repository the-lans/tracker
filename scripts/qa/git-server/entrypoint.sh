#!/bin/sh
# Ключи доступа — все *.pub из /keys; ключи хоста создаются при первом старте.
set -eu

ssh-keygen -A >/dev/null
cat /keys/*.pub > /home/git/.ssh/authorized_keys
chown -R git:git /home/git/.ssh
chmod 700 /home/git/.ssh
chmod 600 /home/git/.ssh/authorized_keys

exec /usr/sbin/sshd -D -e \
    -o PasswordAuthentication=no \
    -o PermitRootLogin=no \
    -o AllowUsers=git
