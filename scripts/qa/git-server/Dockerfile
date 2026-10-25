# Git-хост для ручного E2E-тестирования (docs/qa_e2e_manual.md): bare-репозитории
# в /srv/git, доступ по SSH только ключами из /keys/*.pub, пользователь git
# с git-shell. Не для продакшена.
FROM alpine:3.20

RUN apk add --no-cache git openssh \
    && adduser -D -h /home/git -s /usr/bin/git-shell git \
    && passwd -u git \
    && mkdir -p /srv/git /home/git/.ssh \
    && chown -R git:git /srv/git /home/git

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
