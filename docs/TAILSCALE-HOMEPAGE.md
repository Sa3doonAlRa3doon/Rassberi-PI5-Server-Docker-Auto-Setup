# Independent Tailscale Homepage

The original Homepage remains the LAN dashboard. `homepage-tailscale` has its own configuration in `/srv/docker/configs/homepage-tailscale` and listens on the Pi's actual Tailscale IPv4 address at port `3003`. It has no wildcard bind, Docker socket or Docker API proxy access. It remains disabled until Tailscale is configured.

Install and authenticate Tailscale on the Pi host using its normal setup. Enable MagicDNS and HTTPS for the tailnet. The helper detects the Pi's own Tailscale IPv4 and `.ts.net` hostname and checks that the address is assigned locally. It does not log into an account or choose an invented address.

```bash
sudo /srv/docker/setup-tailscale-homepage.sh --dry-run
sudo /srv/docker/setup-tailscale-homepage.sh --apply
sudo /srv/docker/start-all.sh homepage-tailscale
```

The review shows every proposed mapping before `--apply` changes anything. The helper requires **Tailscale 1.92.0 or later** because that version supports explicit non-loopback proxy targets used by the LAN-bound application stacks. Earlier clients supported only loopback destinations. The helper preserves unrelated Serve settings and refuses an occupied port if its existing handler differs, includes extra paths, belongs to a foreground session or has Funnel enabled. It never resets Serve or enables Funnel. Newly created endpoints are removed if applying the plan fails.

After applying, open the generated `https://YOUR-PI.YOUR-TAILNET.ts.net/`. Direct dashboard access is also available at `http://TAILSCALE_IPV4:3003/`. The Homepage hostname allowlist contains the actual detected addresses. The direct HTTP connection travels through Tailscale; the generated dashboard URL additionally uses HTTPS.

Dashboard links are generated from installed application metadata and each application's actual `.env` bind address. A separate private HTTPS listener at `10000 + application web port` forwards to that real host listener. For example, Homebox on LAN port `7745` uses tailnet HTTPS port `17745`; a Beszel hub on `8098` uses `18098`. This works with services bound only to the LAN address: merely replacing a LAN IP with a Tailscale IP would not create a listener. DNS, SSH, sync protocols and Docker API ports are excluded. A stopped/on-demand application remains stopped when a mapping is added.

Settings changes to app bind addresses, Tailscale identity or ports require rerunning the review. The helper refuses to overwrite a previously different route, so review and remove only the obsolete endpoint with the appropriate `tailscale serve --https=PORT --set-path=/ off` command before applying its replacement. It saves a copy of the previous second-dashboard services list. Customize the LAN dashboard independently.

## Application trust settings

Private forwarding provides the network route and HTTPS. Applications retain their own login, trusted-host, origin and canonical-URL rules. Add the exact generated URL rather than a wildcard wherever the application requires it:

- Nextcloud: add the generated hostname/port to `trusted_domains`; set trusted proxies and overwrite URL/protocol according to its reverse-proxy documentation. Retain the LAN domain if both entry points are needed.
- Paperless: add the HTTPS origin to `PAPERLESS_CSRF_TRUSTED_ORIGINS` and set its public URL as appropriate.
- Home Assistant: configure its `http.use_x_forwarded_for` and narrowly scoped `http.trusted_proxies` for the reverse proxy address observed by Home Assistant. Never trust all addresses. A Docker bridge can change the source IP visible inside a container.
- Linkding: add the generated origin to its CSRF trusted-origin setting if needed.
- Vaultwarden, Gitea, n8n, Moodle and other applications with canonical URLs: update their documented public/root URL before using callbacks, absolute links, WebAuthn or integrations through Tailscale.

The helper intentionally does not rewrite those application settings or widen their trust boundaries. A reachable endpoint with an application trust error is not a successful login. Use the generated `configs/homepage-tailscale/routes.json` as the exact URL list for setup and testing. Tailnet ACLs/grants must permit the chosen HTTPS ports to the Pi.

Official references: [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve), [Tailscale v1.92 proxy-target implementation](https://github.com/tailscale/tailscale/blob/v1.92.0/ipn/serve.go), [Homepage Docker installation](https://gethomepage.dev/installation/docker/), [Nextcloud reverse proxy](https://docs.nextcloud.com/server/latest/admin_manual/configuration_server/reverse_proxy_configuration.html), [Home Assistant HTTP integration](https://www.home-assistant.io/integrations/http/), [Paperless configuration](https://docs.paperless-ngx.com/configuration/), and [Linkding options](https://linkding.link/options/).

The package's route/conflict checks were tested with fixtures. Tailscale login, tailnet policy, certificate provisioning and application logins must be verified on the actual Pi and a remote Tailscale client.
