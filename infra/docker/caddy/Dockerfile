# Caddy build kèm plugin Cloudflare DNS để cấp Let's Encrypt
# qua DNS-01 challenge — không cần mở port 80 trên VPS, hoạt động
# kể cả khi domain đứng sau Cloudflare proxy (orange cloud).
#
# Tham khảo:
# - https://github.com/caddy-dns/cloudflare
# - https://caddyserver.com/docs/build

FROM caddy:2-builder AS builder
RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare

FROM caddy:2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
