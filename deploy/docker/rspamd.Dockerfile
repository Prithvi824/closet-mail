# Official Rspamd with this project's local.d overrides baked in, so the host needs no config files.
FROM rspamd/rspamd:4.2.1
COPY deploy/rspamd/ /etc/rspamd/local.d/
