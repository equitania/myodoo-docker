FROM myodoo/prepare-v18:26.05.19-3.13.13
LABEL maintainer=info@ownerp.com
# Mit diesem Skript überprüft das passende Dockerimage gemäß des Releasefiles
# Date 17.03.2026 - Added HEALTHCHECK directive
# Date 14.07.2026 - Replaced ADD with COPY for bin/ (security hardening, avoid unintended tar auto-extraction)
# Date 17.08.2026 - ca-certificates/ carries an installation's internal CA (LDAP over STARTTLS)

# create the odoo user
RUN adduser --home=/opt/odoo --disabled-password --gecos "" --shell=/bin/bash odoo
RUN chown -R odoo:odoo /opt/odoo/

# changing user is required by odoo which won't start with root
# makes the container more unlikely to be unwillingly changed in interactive mode
USER odoo

RUN /bin/bash -c "mkdir -p /opt/odoo/{odoo-server/odoo,etc,data,data/filestore} && mkdir -p /opt/odoo/var/log"

COPY build_odoo.py /opt/odoo/
COPY release.file /opt/odoo/
COPY odoo.conf /opt/odoo/etc/
# Uncomment to bake customer modules into the image; the pattern also matches
# customer-specific archives like xy_custom_modules.zip (build fails if no file matches)
#COPY *custom_modules.* /opt/odoo/


# The release archives pre-fetched by odoo_build_cache.py are bind-mounted from
# the build context instead of COPYed. Docker layers are additive: a COPY of
# ~270MB stays in the image no matter what a later RUN deletes, so the archives
# would inflate every image by their full size. A bind mount exists only for the
# duration of this RUN and leaves no layer behind.
#
# Requires BuildKit, which update_docker_odoo.py enforces via DOCKER_BUILDKIT=1.
# The directory must exist in the context; 'odoo_build_cache.py sync' creates it
# even when empty, and update_docker_odoo.py does so as a fallback.
RUN --mount=type=bind,source=zips,target=/opt/odoo/zips \
    cd /opt/odoo/ && \
    python3 build_odoo.py

# Execution environment
USER 0
WORKDIR /app

# Trust the installation's own CA certificates. This must come after USER 0:
# update-ca-certificates writes to /etc/ssl/certs and would fail as 'odoo'.
#
# Odoo's auth_ldap only calls start_tls_s() and sets no TLS options at all, so
# an LDAP/AD server whose certificate comes from an internal CA fails with
# "unable to get local issuer certificate" unless that CA is in THIS trust
# store. The host's store does not apply inside the container.
#
# The directory ships empty. Either drop the CA into it, or let the instance
# keep it in sync with the host via docker2update.yaml:
#   pre_build_files:
#     - source: "/usr/local/share/ca-certificates"
#       target: "."
COPY ca-certificates/ /usr/local/share/ca-certificates/
RUN update-ca-certificates

VOLUME ["/opt/odoo/var", "/opt/odoo/etc", "/opt/odoo/data"]
# Healthcheck: Verify Odoo responds on /web/health
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD wget -q --spider http://localhost:8069/web/health || exit 1

# Set the default entrypoint (non overridable) to run when starting the container
ENTRYPOINT ["/app/bin/boot"]
CMD ["help"]

# Expose the odoo ports (for linked containers)
EXPOSE 8069 8072
COPY bin /app/bin/
