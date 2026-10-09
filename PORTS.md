# Authoritative host port map

All web ports bind to the private `BIND_IP` address supplied to the installer. Database ports are private Docker-network ports and are never published.

| Application | Host port | Container port | Protocol | Access |
|---|---:|---:|---|---|
| Portainer | 9443 | 9443 | HTTPS | private LAN/Tailscale |
| Homepage | 3000 | 3000 | HTTP | private LAN/Tailscale |
| Uptime Kuma | 3002 | 3001 | HTTP | private LAN/Tailscale |
| Nextcloud | 8080 | 80 | HTTP | private LAN/Tailscale |
| ONLYOFFICE (on demand) | 8081 | 80 | HTTP | private LAN/Tailscale |
| Moodle (on demand) | 8082 | 80 | HTTP | private LAN/Tailscale |
| Stirling PDF (on demand) | 8083 | 8080 | HTTP | private LAN/Tailscale |
| Wiki.js | 8084 | 3000 | HTTP | private LAN/Tailscale |
| IT-Tools | 8085 | 80 | HTTP | private LAN/Tailscale |
| CyberChef | 8086 | 8080 | HTTP | private LAN/Tailscale |
| Paperless-ngx | 8087 | 8000 | HTTP | private LAN/Tailscale |
| Dozzle | 8088 | 8080 | HTTP | private LAN/Tailscale |
| Vaultwarden | 8089 | 80 | HTTP | private LAN/Tailscale |
| SearXNG | 8090 | 8080 | HTTP | private LAN/Tailscale |
| Excalidraw | 8091 | 80 | HTTP | private LAN/Tailscale |
| File Browser | 8092 | 80 | HTTP | private LAN/Tailscale |
| Calibre-Web | 8093 | 8083 | HTTP | private LAN/Tailscale |
| Kiwix | 8094 | 8080 | HTTP | private LAN/Tailscale |
| FreshRSS | 8095 | 80 | HTTP | private LAN/Tailscale |
| Jellyfin | 8096 | 8096 | HTTP | private LAN/Tailscale |
| n8n | 5678 | 5678 | HTTP | private LAN/Tailscale |
| Actual Budget | 5006 | 5006 | HTTP | private LAN/Tailscale |
| Navidrome | 4533 | 4533 | HTTP | private LAN/Tailscale |
| Jupyter (on demand) | 8888 | 8888 | HTTP | private LAN/Tailscale |
| Code Server | 8443 | 8443 | HTTP | private LAN/Tailscale |
| Syncthing | 8384 | 8384 | HTTP | private LAN/Tailscale |
| Syncthing | 22000 | 22000 | TCP/UDP | private peer traffic |
| Pi-hole | 8053 | 80 | HTTP | private LAN/Tailscale |
| Pi-hole | 53 | 53 | TCP/UDP | private DNS |
| Gitea | 3001 | 3000 | HTTP | private LAN/Tailscale |
| Gitea | 2222 | 22 | TCP | private SSH |
| Tailscale Homepage (after configuration) | 3003 | 3000 | HTTP | exact Tailscale IPv4 only |
| Beszel | 8098 | 8090 | HTTP | private LAN/Tailscale |
| Scrutiny | 8099 | 8080 | HTTP | private LAN/Tailscale |
| Homebox | 7745 | 7745 | HTTP | private LAN/Tailscale |
| Linkding | 9090 | 9090 | HTTP | private LAN/Tailscale |
| ChangeDetection.io (on demand) | 5000 | 5000 | HTTP | private LAN/Tailscale |
| PairDrop | 3004 | 3000 | HTTP | private LAN/Tailscale |
| Localsendy | 8100 | host network | HTTP | private LAN |
| Localsendy transfer/discovery | 53317 | host network | TCP/UDP | private LAN |
| Home Assistant | 8123 | host network | HTTP | private LAN |
| NetAlertX (on demand) | 20211 | host network | HTTP | private LAN |
| NetAlertX backend (on demand) | 20212 | host network | HTTP/token | protect with firewall |
| Permanent server settings | 8788 | host service | HTTPS | exact private address |

Docker Socket Proxy, Autoheal and Diun expose no host port. Internal Beszel/Autoheal socket proxies are not published. Port collision checks cover Compose and declared host-network listeners before a project starts. If the host already uses DNS port 53, resolve that deliberately before starting Pi-hole.
