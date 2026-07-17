FROM myodoo/prepare-v18:26.05.19-3.13.13
LABEL maintainer=info@ownerp.com
# Mit diesem Skript überprüft das passende Dockerimage gemäß des Releasefiles
# Date 17.03.2026 - Added HEALTHCHECK directive
# Date 14.07.2026 - Replaced ADD with COPY for bin/ (security hardening, avoid unintended tar auto-extraction)

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

RUN cd /opt/odoo/ && \
    python3 build_odoo.py

# Execution environment
USER 0
WORKDIR /app
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